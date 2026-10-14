from __future__ import annotations

import logging
import math
from copy import deepcopy
from threading import Event, Lock
from typing import Any

from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.rtd_client import BaseRTDClient
from thlpro_client.timezone_utils import now_iso_sp


EXCEL_ERROR_LIMIT = -2140000000

OPTION_FIELDS = ["ULT", "OCP", "OVD"]
ASSET_FIELDS = ["ULT"]


def to_float(value: Any) -> float | None:
    """
    Converte valores RTD numéricos ou strings para float.

    Aceita:
    - 200.15
    - 200,15
    - 1.234,56
    - 1,234.56
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None

        return number if math.isfinite(number) else None

    if not isinstance(value, str):
        return None

    normalized = value.strip()

    if not normalized or normalized.startswith("#"):
        return None

    normalized = normalized.replace("R$", "").replace(" ", "")

    comma_count = normalized.count(",")
    dot_count = normalized.count(".")

    if comma_count and dot_count:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif comma_count:
        normalized = normalized.replace(",", ".")

    try:
        number = float(normalized)
    except (ValueError, OverflowError):
        return None

    return number if math.isfinite(number) else None


def is_valid_number(value: Any) -> bool:
    number = to_float(value)
    return number is not None and number > EXCEL_ERROR_LIMIT


def infer_asset(
    assets: list[dict[str, Any]],
    option_symbol: str,
) -> str:
    symbols = [
        str(asset.get("symbol") or "").strip().upper()
        for asset in assets
        if asset.get("symbol")
    ]

    def asset_root(symbol: str) -> str:
        index = len(symbol)

        while index > 0 and symbol[index - 1].isdigit():
            index -= 1

        return symbol[:index] if index > 0 else symbol

    roots = sorted(
        [(symbol, asset_root(symbol)) for symbol in symbols],
        key=lambda item: len(item[1]),
        reverse=True,
    )

    option_upper = option_symbol.strip().upper()

    for symbol, root in roots:
        if root and option_upper.startswith(root):
            return symbol

    return symbols[0] if symbols else "BOVA11"


class CaptureService:
    def __init__(
        self,
        logger: logging.Logger,
        rtd_client: BaseRTDClient,
        deduplicator: QuoteDeduplicator,
        queue_enqueue,
        queue_enqueue_asset,
        simulation_mode: bool,
    ):
        self.logger = logger
        self.rtd_client = rtd_client
        self.deduplicator = deduplicator
        self.queue_enqueue = queue_enqueue
        self.queue_enqueue_asset = queue_enqueue_asset
        self.simulation_mode = simulation_mode

        self._stop = Event()
        self._pause = Event()
        self._pause.set()

        self._lock = Lock()
        self._connected = False

        # Recebida pelo poller e aplicada somente pelo capture_worker.
        self._pending_replacement: dict[str, Any] | None = None
        self._config_generation = 0

        self._last_values: dict[str, dict[str, Any]] = {}
        self._asset_spots: dict[str, float] = {}
        self._logged_asset_spots: dict[str, float] = {}

        self._meta_by_rtd: dict[str, dict[str, Any]] = {}

        self._pending_series: list[dict[str, Any]] = []
        self._pending_assets: list[str] = []

        self._pending_series_symbols: set[str] = set()
        self._pending_asset_symbols: set[str] = set()

        self._configured_symbols: set[str] = set()
        self._asset_symbols: set[str] = set()

    def get_asset_spots(self) -> dict[str, float]:
        with self._lock:
            return dict(self._asset_spots)

    def replace_config(self, config_payload: dict[str, Any]) -> None:
        """
        Enfileira uma substituição completa de configuração.

        Não chama o RTD nem manipula o Excel na thread do poller.
        Se várias solicitações chegarem antes da aplicação, mantém a última.
        """
        payload = deepcopy(config_payload)

        with self._lock:
            self._config_generation += 1
            self._pending_replacement = payload

        self.logger.info(
            "Demanda enfileirada: ativo=%s strike=%s séries=%s. "
            "Será aplicada pelo capture_worker.",
            payload.get("asset"),
            payload.get("strike"),
            len(payload.get("active_series") or []),
        )

    def set_pending_config(self, config_payload: dict[str, Any]) -> None:
        """
        Compatibilidade com o callback usado no main.py.

        No modo sob demanda, configurações substituem a captura anterior,
        em vez de acumular séries de diferentes seleções.
        """
        self.replace_config(config_payload)

    def _normalize_config(
        self,
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        assets = payload.get("assets") or []
        active_series = payload.get("active_series") or []

        new_series: list[dict[str, Any]] = []
        new_assets: list[str] = []
        seen_series: set[str] = set()
        seen_assets: set[str] = set()

        demand_asset = str(payload.get("asset") or "").strip().upper()

        for row in active_series:
            option_symbol = str(
                row.get("option_symbol") or ""
            ).strip().upper()

            if not option_symbol or option_symbol in seen_series:
                continue

            seen_series.add(option_symbol)

            new_series.append(
                {
                    "id": row.get("id"),
                    "option_symbol": option_symbol,
                    "option_type": row.get("option_type"),
                    "strike": str(row.get("strike")),
                    "expiration_date": row.get("expiration_date"),
                    "asset": demand_asset or infer_asset(
                        assets,
                        option_symbol,
                    ),
                }
            )

        for asset in assets:
            symbol = str(asset.get("symbol") or "").strip().upper()

            if not symbol or symbol in seen_assets:
                continue

            seen_assets.add(symbol)
            new_assets.append(symbol)

        return new_series, new_assets

    def _apply_pending_replacement(self) -> bool:
        """
        Aplica a configuração exclusivamente na thread de captura.

        Em caso de falha no reset, mantém a solicitação para nova tentativa.
        """
        with self._lock:
            payload = self._pending_replacement
            generation = self._config_generation

        if payload is None:
            return False

        new_series, new_assets = self._normalize_config(payload)

        with self._lock:
            previous_series_count = len(self._configured_symbols)
            previous_asset_count = len(self._asset_symbols)

        try:
            # Antes da primeira conexão não há assinaturas a reiniciar.
            if self._connected:
                self.rtd_client.reset_subscriptions()
        except Exception:
            self.logger.exception(
                "Falha ao reiniciar RTD. Demanda permanece pendente."
            )
            raise

        self._connected = False

        self.deduplicator.reset_symbols(
            [row["option_symbol"] for row in new_series] + new_assets
        )

        with self._lock:
            self._last_values.clear()
            self._asset_spots.clear()
            self._logged_asset_spots.clear()

            self._configured_symbols.clear()
            self._meta_by_rtd.clear()
            self._asset_symbols.clear()

            self._pending_series = new_series
            self._pending_assets = new_assets

            self._pending_series_symbols = {
                row["option_symbol"] for row in new_series
            }
            self._pending_asset_symbols = set(new_assets)

            # Não remove uma demanda mais nova recebida durante o reset.
            if generation == self._config_generation:
                self._pending_replacement = None

        self.logger.info(
            "Demanda aplicada pelo capture_worker: ativo=%s strike=%s; "
            "séries=%s ativos-base=%s; substituídas=%s séries "
            "e %s ativos-base.",
            payload.get("asset"),
            payload.get("strike"),
            len(new_series),
            len(new_assets),
            previous_series_count,
            previous_asset_count,
        )

        return True

    def _configure_series_batch(self, batch_size: int = 100) -> int:
        with self._lock:
            batch = self._pending_series[:batch_size]

        if not batch:
            return 0

        symbols = [row["option_symbol"] for row in batch]

        try:
            for row in batch:
                option_series_id = row.get("id")

                if option_series_id is not None:
                    self.rtd_client.register_meta(
                        option_series_id,
                        row["option_symbol"],
                    )

            subscribed_symbols = set(
                self.rtd_client.subscribe_batch(symbols, OPTION_FIELDS)
            )
        except Exception:
            self.logger.exception(
                "Falha ao assinar lote de %s opções. "
                "Itens permanecem pendentes.",
                len(batch),
            )
            return 0

        confirmed_symbols = set(symbols) & subscribed_symbols

        with self._lock:
            for row in batch:
                symbol = row["option_symbol"]

                if symbol not in confirmed_symbols:
                    continue

                self._configured_symbols.add(symbol)
                self._meta_by_rtd[symbol] = dict(row)
                self._pending_series_symbols.discard(symbol)

            self._pending_series = [
                row
                for row in self._pending_series
                if row["option_symbol"] not in confirmed_symbols
            ]
            pending_count = len(self._pending_series)

        failed_symbols = [
            symbol for symbol in symbols
            if symbol not in confirmed_symbols
        ]

        if failed_symbols:
            self.logger.warning(
                "Opções ainda pendentes de assinatura: %s",
                ", ".join(failed_symbols[:10]),
            )

        self.logger.info(
            "Assinatura RTD de opções: solicitadas=%s confirmadas=%s "
            "pendentes=%s",
            len(batch),
            len(confirmed_symbols),
            pending_count,
        )

        return len(confirmed_symbols)

    def _configure_asset_batch(self, batch_size: int = 50) -> int:
        with self._lock:
            batch = self._pending_assets[:batch_size]

        if not batch:
            return 0

        try:
            for symbol in batch:
                self.rtd_client.register_asset(symbol)

            subscribed_symbols = set(
                self.rtd_client.subscribe_batch(batch, ASSET_FIELDS)
            )
        except Exception:
            self.logger.exception(
                "Falha ao assinar lote de %s ativos-base. "
                "Itens permanecem pendentes.",
                len(batch),
            )
            return 0

        confirmed_symbols = set(batch) & subscribed_symbols

        with self._lock:
            self._asset_symbols.update(confirmed_symbols)
            self._pending_asset_symbols.difference_update(
                confirmed_symbols
            )
            self._pending_assets = [
                symbol
                for symbol in self._pending_assets
                if symbol not in confirmed_symbols
            ]
            pending_count = len(self._pending_assets)

        failed_symbols = [
            symbol for symbol in batch
            if symbol not in confirmed_symbols
        ]

        if failed_symbols:
            self.logger.warning(
                "Ativos-base ainda pendentes de assinatura: %s",
                ", ".join(failed_symbols),
            )

        self.logger.info(
            "Assinatura RTD de ativos-base: solicitados=%s "
            "confirmados=%s pendentes=%s",
            len(batch),
            len(confirmed_symbols),
            pending_count,
        )

        return len(confirmed_symbols)

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True

        try:
            self.rtd_client.connect()
        except Exception:
            self.logger.exception(
                "Falha ao conectar RTD para captura sob demanda."
            )
            return False

        self._connected = True

        self.logger.info(
            "RTD conectado para captura sob demanda. source=%s",
            "SIMULATED" if self.simulation_mode else "Profit RTD",
        )

        return True

    def start_capture(self) -> None:
        self._pause.clear()

    def stop_capture(self) -> None:
        """
        Pausa a leitura.

        Não remove assinaturas nem libera leases.
        """
        self._pause.set()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        source = "SIMULATED" if self.simulation_mode else "Profit RTD"

        self.logger.info(
            "Serviço de captura iniciado em modo sob demanda. source=%s",
            source,
        )

        try:
            while not self._stop.is_set():
                try:
                    # Processa substituições mesmo enquanto pausado.
                    self._apply_pending_replacement()

                    if self._pause.is_set():
                        self._stop.wait(0.2)
                        continue

                    with self._lock:
                        replacement_waiting = (
                            self._pending_replacement is not None
                        )
                        has_symbols = bool(
                            self._pending_series
                            or self._pending_assets
                            or self._configured_symbols
                            or self._asset_symbols
                        )
                        generation = self._config_generation

                    if replacement_waiting:
                        continue

                    # Start sem configuração não abre o Excel.
                    if not has_symbols:
                        self._stop.wait(0.2)
                        continue

                    if not self._ensure_connected():
                        self._stop.wait(2.0)
                        continue

                    self._configure_asset_batch(batch_size=50)
                    self._configure_series_batch(batch_size=100)

                    if self._stop.is_set() or self._pause.is_set():
                        continue

                    with self._lock:
                        if generation != self._config_generation:
                            continue

                    updates = self.rtd_client.poll_updates(
                        timeout_seconds=0.5
                    )

                    option_rows: list[dict[str, Any]] = []
                    asset_rows: list[dict[str, Any]] = []

                    with self._lock:
                        # Ignora a leitura se chegou outra seleção.
                        if generation != self._config_generation:
                            continue

                        for update in updates:
                            if update.rtd_symbol in self._asset_symbols:
                                self._handle_asset_update(
                                    update,
                                    source,
                                    asset_rows,
                                )
                            else:
                                self._handle_option_update(
                                    update,
                                    source,
                                    option_rows,
                                )

                    if option_rows:
                        inserted = self.queue_enqueue(option_rows)
                        self.logger.info(
                            "Captura: %s cotações de opções processadas; "
                            "%s novas na fila.",
                            len(option_rows),
                            inserted,
                        )

                    if asset_rows:
                        inserted = self.queue_enqueue_asset(asset_rows)
                        self.logger.info(
                            "Captura: %s cotações de ativos-base "
                            "processadas; %s novas na fila.",
                            len(asset_rows),
                            inserted,
                        )

                except Exception:
                    self.logger.exception(
                        "Erro no ciclo de captura. "
                        "Nova tentativa em 2 segundos."
                    )
                    self._stop.wait(2.0)

        finally:
            # Encerra o RTD na mesma thread usada para captura.
            try:
                self.rtd_client.close()
            except Exception:
                self.logger.exception(
                    "Falha ao encerrar RTD no capture_worker."
                )
            finally:
                self._connected = False

    def _handle_option_update(
        self,
        update,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        meta = self._meta_by_rtd.get(update.rtd_symbol)

        if not meta or update.field not in OPTION_FIELDS:
            return

        if not is_valid_number(update.value):
            return

        value = to_float(update.value)

        bucket = self._last_values.setdefault(
            update.rtd_symbol,
            {"ULT": None, "OCP": None, "OVD": None},
        )
        bucket[update.field] = value

        last_price = bucket.get("ULT")
        bid = bucket.get("OCP")
        ask = bucket.get("OVD")

        if last_price is None and bid is None and ask is None:
            return

        payload = {
            "option_series_id": meta.get("id"),
            "asset": meta["asset"],
            "option_symbol": meta["option_symbol"],
            "option_type": meta.get("option_type"),
            "strike": meta.get("strike"),
            "expiration_date": meta.get("expiration_date"),
            "last_price": last_price,
            "bid": bid,
            "ask": ask,
            "premium": last_price,
            "quote_timestamp": update.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        if self.deduplicator.should_send(payload):
            rows.append(payload)

    def _handle_asset_update(
        self,
        update,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if update.field != "ULT":
            return

        if not is_valid_number(update.value):
            return

        spot = to_float(update.value)

        if spot is None or spot <= 0:
            return

        symbol = update.rtd_symbol.strip().upper()
        self._asset_spots[symbol] = spot

        logged_spot = self._logged_asset_spots.get(symbol)

        if logged_spot is None or not math.isclose(
            logged_spot,
            spot,
            rel_tol=0.0,
            abs_tol=0.000001,
        ):
            self.logger.info(
                "Spot RTD atualizado: %s = %.4f",
                symbol,
                spot,
            )
            self._logged_asset_spots[symbol] = spot

        payload = {
            "asset": symbol,
            "last_price": spot,
            "variation_points": None,
            "variation_pct": None,
            "high": None,
            "low": None,
            "quote_timestamp": update.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        if self.deduplicator.should_send(payload):
            rows.append(payload)