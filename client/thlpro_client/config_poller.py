from __future__ import annotations

import json
import logging
from copy import deepcopy
from threading import Event
from typing import Any, Callable

from thlpro_client.api_client import APIError, THLProAPIClient
from thlpro_client.capture_service import CaptureService


DEFAULT_DEMAND_INTERVAL_SECONDS = 2.0
MIN_DEMAND_INTERVAL_SECONDS = 1.0
MAX_DEMAND_INTERVAL_SECONDS = 2.0
MAX_ERROR_WAIT_SECONDS = 30.0


class ConfigPollerService:
    """
    Consulta exclusivamente a configuração de captura sob demanda.

    - Não consulta get_config().
    - Não solicita captura ampla por faixa de strikes.
    - Enfileira uma substituição quando a demanda muda.
    - Não reaplica configurações idênticas.
    - Enfileira a limpeza quando o backend retorna ausência de demanda.
    - Mantém a configuração atual quando a consulta falha.

    O CaptureService aplica a configuração e manipula o RTD
    exclusivamente no capture_worker.
    """

    def __init__(
        self,
        logger: logging.Logger,
        api_client: THLProAPIClient,
        capture_service: CaptureService,
        on_config: Callable[[dict[str, Any]], None],
        interval_seconds: int = 60,
    ):
        self.logger = logger
        self.api = api_client
        self.capture_service = capture_service

        # Mantido para compatibilidade com o main.py.
        # A substituição é feita por capture_service.replace_config().
        self.on_config = on_config

        try:
            requested_interval = float(interval_seconds)
        except (TypeError, ValueError, OverflowError):
            requested_interval = DEFAULT_DEMAND_INTERVAL_SECONDS

        if not 0 < requested_interval < float("inf"):
            requested_interval = DEFAULT_DEMAND_INTERVAL_SECONDS

        self.interval_seconds = max(
            MIN_DEMAND_INTERVAL_SECONDS,
            min(
                requested_interval,
                MAX_DEMAND_INTERVAL_SECONDS,
            ),
        )

        self._stop = Event()
        self._last_demand_signature: str | None = None
        self._last_mode: str | None = None

    def stop(self) -> None:
        self._stop.set()

    def _get_demand_signature(
        self,
        payload: dict[str, Any],
    ) -> str:
        """
        Compara o conteúdo relevante da configuração.

        Inclui metadados das séries e dos ativos, não apenas os símbolos.
        Campos externos de timestamp não provocam reinício por si só.
        """
        series = sorted(
            payload.get("active_series") or [],
            key=lambda item: (
                str(item.get("option_symbol") or ""),
                str(item.get("id") or ""),
            ),
        )

        assets = sorted(
            payload.get("assets") or [],
            key=lambda item: str(item.get("symbol") or ""),
        )

        relevant_payload = {
            "asset": payload.get("asset"),
            "strike": payload.get("strike"),
            "assets": assets,
            "active_series": series,
        }

        return json.dumps(
            relevant_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    def _set_idle(self, reason: str) -> None:
        """
        Enfileira a limpeza da configuração anterior.

        Não chama reset_subscriptions() nem close() nesta thread.
        """
        if self._last_demand_signature is not None:
            self.capture_service.replace_config(
                {
                    "asset": None,
                    "strike": None,
                    "assets": [],
                    "active_series": [],
                }
            )
            self._last_demand_signature = None

        if self._last_mode != reason:
            self.logger.info(
                "Cliente aguardando demanda: %s.",
                reason,
            )
            self._last_mode = reason

    def _apply_demand_config(self) -> bool:
        """
        Consulta e enfileira a demanda quando ela muda.

        Retorna True quando existe uma demanda com séries.
        Erros de consulta são propagados para run_forever().
        """
        demand = self.api.get_capture_config()

        if self._stop.is_set():
            return False

        if demand is None or demand == {}:
            self._set_idle("backend sem solicitação ativa")
            return False

        if not isinstance(demand, dict):
            raise ValueError(
                "Resposta inválida de capture-config: "
                "esperado objeto ou null."
            )

        active_series = demand.get("active_series") or []
        assets = demand.get("assets") or []

        if not isinstance(active_series, list):
            raise ValueError(
                "Resposta inválida: active_series deve ser uma lista."
            )

        if not isinstance(assets, list):
            raise ValueError(
                "Resposta inválida: assets deve ser uma lista."
            )

        if any(not isinstance(item, dict) for item in active_series):
            raise ValueError(
                "Resposta inválida: cada série deve ser um objeto."
            )

        if any(not isinstance(item, dict) for item in assets):
            raise ValueError(
                "Resposta inválida: cada ativo deve ser um objeto."
            )

        if not active_series:
            self._set_idle("seleção atual sem séries disponíveis")
            return False

        payload = deepcopy(demand)
        payload["active_series"] = active_series
        payload["assets"] = assets

        signature = self._get_demand_signature(payload)

        if signature == self._last_demand_signature:
            # Não chama start_capture() repetidamente.
            return True

        self.capture_service.replace_config(payload)
        self.capture_service.start_capture()

        self._last_demand_signature = signature
        self._last_mode = "demand"

        self.logger.info(
            "Demanda enviada ao capture_worker: "
            "ativo=%s strike=%s séries=%s símbolos=%s.",
            payload.get("asset"),
            payload.get("strike"),
            len(active_series),
            ", ".join(
                str(item.get("option_symbol") or "")
                for item in active_series
            ),
        )

        return True

    def run_forever(self) -> None:
        self.logger.info(
            "Serviço de consulta sob demanda iniciado "
            "(intervalo=%.1fs; sem captura ampla).",
            self.interval_seconds,
        )

        consecutive_errors = 0

        while not self._stop.is_set():
            wait_seconds = self.interval_seconds

            try:
                self._apply_demand_config()
                consecutive_errors = 0

            except APIError as exc:
                consecutive_errors += 1
                wait_seconds = min(
                    MAX_ERROR_WAIT_SECONDS,
                    self.interval_seconds
                    * (2 ** min(consecutive_errors, 4)),
                )

                self.logger.warning(
                    "Falha ao consultar demanda: %s. "
                    "Configuração atual mantida; "
                    "nova tentativa em %.1fs.",
                    exc,
                    wait_seconds,
                )

            except Exception:
                consecutive_errors += 1
                wait_seconds = min(
                    MAX_ERROR_WAIT_SECONDS,
                    self.interval_seconds
                    * (2 ** min(consecutive_errors, 4)),
                )

                self.logger.exception(
                    "Erro ao processar demanda. "
                    "Configuração atual mantida; "
                    "nova tentativa em %.1fs.",
                    wait_seconds,
                )

            self._stop.wait(wait_seconds)