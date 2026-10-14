from __future__ import annotations

import abc
import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

import requests

from thlpro_client.compat_windows import IS_WINDOWS
from thlpro_client.timezone_utils import now_iso_sp


try:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
except Exception:  # pragma: no cover
    pythoncom = None
    win32com = None


LEASE_RENEW_INTERVAL_SECONDS = 300
LEASE_RETRY_INTERVAL_SECONDS = 10
RTD_DIAGNOSTIC_INTERVAL_SECONDS = 30

LEASE_ACQUIRE_TIMEOUT_SECONDS = 15
LEASE_RELEASE_TIMEOUT_SECONDS = 8

RTD_SERVER_PROGID = "rtdtrading.rtdserver"

COM_MAX_ATTEMPTS = 5
COM_RETRY_INITIAL_SECONDS = 0.15
COM_RETRY_MAX_SECONDS = 0.60

RPC_E_CALL_REJECTED = 0x80010001
RPC_E_SERVERCALL_RETRYLATER = 0x8001010A

TRANSIENT_COM_HRESULTS = {
    RPC_E_CALL_REJECTED,
    RPC_E_SERVERCALL_RETRYLATER,
}

XL_CALCULATION_AUTOMATIC = -4105

ASSET_WARMUP_TIMEOUT_SECONDS = 3.0
OPTION_GROUP_SIZE = 2
OPTION_GROUP_WAIT_SECONDS = 0.20

INVALID_FIELD_GRACE_SECONDS = 8.0
INVALID_FIELD_RETRY_SECONDS = 10.0
INVALID_FIELD_MAX_RETRIES = 3
INVALID_FIELD_CLEAR_WAIT_SECONDS = 0.15

T = TypeVar("T")


@dataclass(slots=True)
class RTDUpdate:
    rtd_symbol: str
    field: str
    value: float | str | None
    timestamp: str


class BaseRTDClient(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def subscribe(
        self,
        rtd_symbol: str,
        fields: Iterable[str],
    ) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def register_meta(
        self,
        option_series_id: int,
        rtd_symbol: str,
    ) -> None:
        return None

    def register_asset(self, rtd_symbol: str) -> None:
        return None

    def reset_subscriptions(self) -> None:
        return None

    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        requested_fields = list(fields)
        configured: list[str] = []

        for symbol in rtd_symbols:
            self.subscribe(symbol, requested_fields)
            configured.append(symbol)

        return configured


class ComProbeRTDClient(BaseRTDClient):
    """Diagnóstico COM; não implementa captura de cotações."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._server = None
        self._com_initialized = False

    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError(
                "COM RTD disponível apenas no Windows com pywin32."
            )

        if not self._com_initialized:
            pythoncom.CoInitialize()
            self._com_initialized = True

        try:
            self._server = win32com.client.Dispatch(
                RTD_SERVER_PROGID
            )
        except Exception as exc:
            self.close()
            raise RuntimeError(
                f"Não foi possível criar {RTD_SERVER_PROGID}: {exc}"
            ) from exc

        self.logger.info(
            "Servidor COM %s criado sem Excel.",
            RTD_SERVER_PROGID,
        )

        raise RuntimeError(
            "com_probe confirmou o servidor COM, mas não "
            "implementa captura. Use excel_bridge."
        )

    def subscribe(
        self,
        rtd_symbol: str,
        fields: Iterable[str],
    ) -> None:
        raise RuntimeError("com_probe não assina símbolos.")

    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        return []

    def close(self) -> None:
        self._server = None

        if self._com_initialized and pythoncom:
            pythoncom.CoUninitialize()
            self._com_initialized = False


class ExcelBridgeRTDClient(BaseRTDClient):
    """
    Ponte RTD com Excel oculto mantido nas trocas de strike.

    Todas as operações Excel/COM devem ocorrer no capture_worker.
    A recuperação de Ativo Inválido é limitada por campo e demanda.
    """

    def __init__(
        self,
        logger: logging.Logger,
        server_url: str = "",
        api_key: str = "",
    ):
        self.logger = logger
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

        self._excel = None
        self._wb = None
        self._ws = None
        self._com_initialized = False

        self._subs: dict[tuple[str, str], str] = {}
        self._meta_by_symbol: dict[str, int] = {}
        self._asset_symbols: set[str] = set()

        self._leased_option_ids: set[int] = set()
        self._leases_to_release: set[int] = set()

        self._last_lease_renewal_at = 0.0
        self._next_lease_attempt_at = 0.0
        self._next_release_attempt_at = 0.0
        self._last_diagnostic_at = 0.0

        self._row = 1
        self._asset_warmup_done = False

        self._field_created_at: dict[tuple[str, str], float] = {}
        self._field_retry_count: dict[tuple[str, str], int] = {}
        self._field_next_retry_at: dict[tuple[str, str], float] = {}

        self._invalid_fields: set[tuple[str, str]] = set()
        self._retry_exhausted: set[tuple[str, str]] = set()

        # Campos limpos cuja reescrita falhou.
        self._restore_pending: set[tuple[str, str]] = set()

        self._http = requests.Session()

    @staticmethod
    def _get_hresult(exc: Exception) -> int | None:
        raw = getattr(exc, "hresult", None)

        if raw is None and exc.args:
            raw = exc.args[0]

        return raw & 0xFFFFFFFF if isinstance(raw, int) else None

    @classmethod
    def _is_transient_com_error(cls, exc: Exception) -> bool:
        return cls._get_hresult(exc) in TRANSIENT_COM_HRESULTS

    @staticmethod
    def _is_invalid_asset(value) -> bool:
        if not isinstance(value, str):
            return False

        normalized = " ".join(value.strip().casefold().split())
        return normalized in {"ativo inválido", "ativo invalido"}

    @staticmethod
    def _is_numeric(value) -> bool:
        if isinstance(value, bool):
            return False

        if isinstance(value, (int, float)):
            try:
                number = float(value)
            except (ValueError, OverflowError):
                return False
        elif isinstance(value, str):
            normalized = value.strip().replace("R$", "").replace(" ", "")

            if "," in normalized and "." in normalized:
                if normalized.rfind(",") > normalized.rfind("."):
                    normalized = normalized.replace(".", "").replace(",", ".")
                else:
                    normalized = normalized.replace(",", "")
            elif "," in normalized:
                normalized = normalized.replace(",", ".")

            try:
                number = float(normalized)
            except (ValueError, OverflowError):
                return False
        else:
            return False

        return math.isfinite(number) and number > -2140000000

    def _wait_with_message_pump(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)

        while True:
            if self._com_initialized and pythoncom:
                pythoncom.PumpWaitingMessages()

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                return

            time.sleep(min(0.05, remaining))

    def _com_call(
        self,
        action: str,
        operation: Callable[[], T],
    ) -> T:
        for attempt in range(1, COM_MAX_ATTEMPTS + 1):
            try:
                result = operation()

                if attempt > 1:
                    self.logger.info(
                        "Chamada COM recuperada: ação=%s tentativa=%s.",
                        action,
                        attempt,
                    )

                return result

            except Exception as exc:
                if (
                    not self._is_transient_com_error(exc)
                    or attempt >= COM_MAX_ATTEMPTS
                ):
                    raise

                delay = min(
                    COM_RETRY_MAX_SECONDS,
                    COM_RETRY_INITIAL_SECONDS * attempt,
                )

                self.logger.warning(
                    "Excel rejeitou chamada COM: ação=%s "
                    "HRESULT=0x%08X tentativa=%s/%s; espera=%.2fs.",
                    action,
                    self._get_hresult(exc),
                    attempt,
                    COM_MAX_ATTEMPTS,
                    delay,
                )

                self._wait_with_message_pump(delay)

        raise RuntimeError("Fluxo inesperado no retry COM.")

    def _write_formula(self, cell: str, formula: str) -> None:
        def operation() -> None:
            self._ws.Range(cell).FormulaLocal = formula

        self._com_call(f"escrever fórmula em {cell}", operation)

    @staticmethod
    def _formula(symbol: str, field: str) -> str:
        symbol = symbol.replace('"', '""')
        field = field.replace('"', '""')

        return (
            f'=RTD("{RTD_SERVER_PROGID}";;'
            f'"{symbol}";"{field}")'
        )

    def set_credentials(self, server_url: str, api_key: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

    def register_meta(
        self,
        option_series_id: int,
        rtd_symbol: str,
    ) -> None:
        self._meta_by_symbol[rtd_symbol] = int(option_series_id)

    def register_asset(self, rtd_symbol: str) -> None:
        self._asset_symbols.add(rtd_symbol)

    def _clear_recovery_state(self) -> None:
        self._field_created_at.clear()
        self._field_retry_count.clear()
        self._field_next_retry_at.clear()
        self._invalid_fields.clear()
        self._retry_exhausted.clear()
        self._restore_pending.clear()
        self._asset_warmup_done = False

    def reset_subscriptions(self) -> None:
        started_at = time.perf_counter()
        clear_started_at = time.perf_counter()

        if self._is_connected() and self._row > 1:
            last_row = self._row - 1

            self._com_call(
                "limpar demanda anterior",
                lambda: self._ws.Range(
                    f"A1:A{last_row}"
                ).ClearContents(),
            )

        clear_elapsed = time.perf_counter() - clear_started_at

        self._leases_to_release.update(self._leased_option_ids)

        self._subs.clear()
        self._meta_by_symbol.clear()
        self._asset_symbols.clear()
        self._leased_option_ids.clear()
        self._clear_recovery_state()

        self._row = 1
        self._last_diagnostic_at = 0.0
        self._last_lease_renewal_at = 0.0
        self._next_lease_attempt_at = 0.0

        release_started_at = time.perf_counter()
        removed, confirmed = self._release_pending_leases(force=True)

        self.logger.info(
            "Reset RTD sem recriar Excel: limpeza=%.2fs "
            "liberação_leases_lote=%.2fs total=%.2fs; "
            "removidos=%s confirmados=%s pendentes=%s.",
            clear_elapsed,
            time.perf_counter() - release_started_at,
            time.perf_counter() - started_at,
            removed,
            confirmed,
            len(self._leases_to_release),
        )

    def _request_leases_batch(
        self,
        option_series_ids: list[int],
        action_label: str,
    ) -> list[int] | None:
        ids = sorted({
            int(value)
            for value in option_series_ids
            if value is not None and int(value) > 0
        })

        if not ids:
            return []

        if not (self.server_url and self.api_key):
            return ids

        started_at = time.perf_counter()

        try:
            response = self._http.post(
                f"{self.server_url}/clients/lease/acquire-batch",
                json={"option_series_ids": ids},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=LEASE_ACQUIRE_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                self.logger.warning(
                    "Falha ao %s leases: HTTP %s: %s",
                    action_label,
                    response.status_code,
                    response.text,
                )
                return None

            body = response.json()

            if not isinstance(body, dict):
                raise ValueError("Resposta não é um objeto.")

            acquired = body.get("acquired")

            if not isinstance(acquired, list):
                raise ValueError("Campo acquired não é uma lista.")

            requested = set(ids)
            result = sorted({
                int(value)
                for value in acquired
                if value is not None and int(value) in requested
            })

            self.logger.info(
                "Leases: ação=%s solicitados=%s adquiridos=%s tempo=%.2fs.",
                action_label,
                len(ids),
                len(result),
                time.perf_counter() - started_at,
            )

            return result

        except (TypeError, ValueError, requests.RequestException) as exc:
            self.logger.warning(
                "Falha ao %s leases: %s",
                action_label,
                exc,
            )
            return None

    def _acquire_leases_batch(
        self,
        option_series_ids: list[int],
    ) -> list[int]:
        acquired = self._request_leases_batch(
            option_series_ids,
            "adquirir",
        )

        if acquired is None:
            return []

        acquired_set = set(acquired)
        self._leased_option_ids.update(acquired_set)
        self._leases_to_release.difference_update(acquired_set)

        if acquired_set and self._last_lease_renewal_at == 0.0:
            now = time.monotonic()
            self._last_lease_renewal_at = now
            self._next_lease_attempt_at = (
                now + LEASE_RENEW_INTERVAL_SECONDS
            )

        return acquired

    def _renew_leases_if_needed(self) -> None:
        if not (self.server_url and self.api_key):
            return

        if time.monotonic() < self._next_lease_attempt_at:
            return

        ids = sorted({
            self._meta_by_symbol[symbol]
            for symbol, _field in self._subs
            if symbol not in self._asset_symbols
            and symbol in self._meta_by_symbol
        })

        if not ids:
            return

        renewed = self._request_leases_batch(ids, "renovar")

        if renewed is None:
            self._next_lease_attempt_at = (
                time.monotonic() + LEASE_RETRY_INTERVAL_SECONDS
            )
            return

        expected = set(ids)
        renewed_set = set(renewed)

        self._leased_option_ids.difference_update(expected)
        self._leased_option_ids.update(renewed_set)

        failed = expected - renewed_set
        self._last_lease_renewal_at = time.monotonic()

        interval = (
            LEASE_RETRY_INTERVAL_SECONDS
            if failed
            else LEASE_RENEW_INTERVAL_SECONDS
        )
        self._next_lease_attempt_at = (
            self._last_lease_renewal_at + interval
        )

        if failed:
            symbols = sorted(
                symbol
                for symbol, option_id in self._meta_by_symbol.items()
                if option_id in failed
            )
            self.logger.warning(
                "Leases não renovados: %s.",
                ", ".join(symbols),
            )

    def _release_leases_batch(
        self,
        option_series_ids: list[int],
    ) -> tuple[set[int], set[int]] | None:
        ids = sorted({
            int(value)
            for value in option_series_ids
            if value is not None and int(value) > 0
        })

        if not ids:
            return set(), set()

        if not (self.server_url and self.api_key):
            return set(), set(ids)

        started_at = time.perf_counter()

        try:
            response = self._http.post(
                f"{self.server_url}/clients/lease/release-batch",
                json={"option_series_ids": ids},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=LEASE_RELEASE_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                self.logger.warning(
                    "Falha na liberação em lote: HTTP %s: %s.",
                    response.status_code,
                    response.text,
                )
                return None

            body = response.json()

            if not isinstance(body, dict):
                raise ValueError("Resposta não é um objeto.")

            raw_released = body.get("released")
            raw_not_released = body.get("not_released")

            if not isinstance(raw_released, list):
                raise ValueError("released não é uma lista.")

            if not isinstance(raw_not_released, list):
                raise ValueError("not_released não é uma lista.")

            released = {int(value) for value in raw_released}
            not_released = {int(value) for value in raw_not_released}
            requested = set(ids)

            if released & not_released:
                raise ValueError("IDs presentes nas duas listas.")

            if (released | not_released) != requested:
                raise ValueError("Resposta não corresponde aos IDs enviados.")

            self.logger.info(
                "Liberação de leases em lote: solicitados=%s "
                "removidos=%s sem_lease_deste_cliente=%s tempo=%.2fs.",
                len(ids),
                len(released),
                len(not_released),
                time.perf_counter() - started_at,
            )

            return released, not_released

        except (TypeError, ValueError, requests.RequestException) as exc:
            self.logger.warning(
                "Falha ao liberar leases em lote: %s. "
                "IDs permanecem pendentes.",
                exc,
            )
            return None

    def _release_pending_leases(
        self,
        force: bool = False,
    ) -> tuple[int, int]:
        self._leases_to_release.difference_update(
            self._leased_option_ids
        )

        if not self._leases_to_release:
            return 0, 0

        if (
            not force
            and time.monotonic() < self._next_release_attempt_at
        ):
            return 0, 0

        result = self._release_leases_batch(
            sorted(self._leases_to_release)
        )

        if result is None:
            self._next_release_attempt_at = (
                time.monotonic() + LEASE_RETRY_INTERVAL_SECONDS
            )
            return 0, 0

        released, not_released = result
        confirmed = released | not_released

        self._leases_to_release.difference_update(confirmed)
        self._next_release_attempt_at = 0.0

        return len(released), len(confirmed)

    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError(
                "Ponte Excel RTD disponível apenas "
                "no Windows com pywin32."
            )

        if self._is_connected():
            return

        if not self._com_initialized:
            pythoncom.CoInitialize()
            self._com_initialized = True

        started_at = time.perf_counter()

        try:
            self._excel = win32com.client.DispatchEx(
                "Excel.Application"
            )

            def configure_excel() -> None:
                self._excel.Visible = False
                self._excel.DisplayAlerts = False
                self._excel.AskToUpdateLinks = False

            self._com_call("configurar Excel", configure_excel)

            self._wb = self._com_call(
                "criar pasta RTD",
                lambda: self._excel.Workbooks.Add(),
            )
            self._ws = self._com_call(
                "obter aba RTD",
                lambda: self._wb.Worksheets(1),
            )

            def enable_automatic_calculation() -> None:
                self._excel.Calculation = XL_CALCULATION_AUTOMATIC

            self._com_call(
                "ativar cálculo automático",
                enable_automatic_calculation,
            )

            calculation_mode = self._com_call(
                "ler modo de cálculo",
                lambda: self._excel.Calculation,
            )

            self.logger.info(
                "Excel RTD: modo de cálculo=%s; esperado=%s.",
                calculation_mode,
                XL_CALCULATION_AUTOMATIC,
            )

            self._clear_recovery_state()

            # Na recuperação de conexão, restaura as fórmulas existentes.
            for (symbol, field), cell in self._subs.items():
                self._write_formula(
                    cell,
                    self._formula(symbol, field),
                )
                self._field_created_at[(symbol, field)] = (
                    time.monotonic()
                )

        except Exception:
            self._dispose_excel()
            raise

        self.logger.warning(
            "Excel oculto iniciado em %.2fs: uma pasta e uma aba. "
            "Instância mantida nas trocas de strike.",
            time.perf_counter() - started_at,
        )

    def _dispose_excel(self) -> None:
        workbook = self._wb
        excel = self._excel

        self._wb = None
        self._ws = None
        self._excel = None

        if workbook is not None:
            try:
                self._com_call(
                    "fechar pasta RTD",
                    lambda: workbook.Close(SaveChanges=False),
                )
            except Exception as exc:
                self.logger.warning(
                    "Falha ao fechar pasta RTD: %s.",
                    exc,
                )

        if excel is not None:
            try:
                self._com_call(
                    "encerrar Excel RTD",
                    lambda: excel.Quit(),
                )
            except Exception as exc:
                self.logger.warning(
                    "Falha ao encerrar Excel RTD: %s.",
                    exc,
                )

    def _reset_excel(self) -> None:
        self._dispose_excel()
        self._last_diagnostic_at = 0.0

    def _warmup_asset(self) -> None:
        if self._asset_warmup_done:
            return

        self._asset_warmup_done = True

        asset_cells = [
            (symbol, cell)
            for (symbol, field), cell in self._subs.items()
            if symbol in self._asset_symbols and field == "ULT"
        ]

        if not asset_cells:
            self.logger.warning(
                "Inicialização RTD sem fórmula ULT de ativo-base. "
                "Opções serão configuradas sem essa espera."
            )
            return

        started_at = time.monotonic()
        deadline = started_at + ASSET_WARMUP_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            for symbol, cell in asset_cells:
                try:
                    value = self._com_call(
                        f"aguardar primeiro ULT de {symbol}",
                        lambda cell=cell: self._ws.Range(cell).Value,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Falha na leitura inicial de %s: %s.",
                        symbol,
                        exc,
                    )
                    return

                if self._is_numeric(value):
                    self.logger.info(
                        "Inicialização RTD: %s.ULT=%r após %.2fs. "
                        "Iniciando configuração das opções.",
                        symbol,
                        value,
                        time.monotonic() - started_at,
                    )
                    return

            self._wait_with_message_pump(0.10)

        self.logger.warning(
            "Inicialização RTD: nenhum ULT numérico do ativo-base "
            "em %.1fs. Opções serão configuradas mesmo assim.",
            ASSET_WARMUP_TIMEOUT_SECONDS,
        )

    def subscribe(
        self,
        rtd_symbol: str,
        fields: Iterable[str],
    ) -> None:
        self.subscribe_batch([rtd_symbol], fields)

    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        started_at = time.perf_counter()
        symbols = list(dict.fromkeys(rtd_symbols))
        fields_list = list(dict.fromkeys(fields))

        if not symbols or not fields_list:
            return []

        option_ids = [
            self._meta_by_symbol[symbol]
            for symbol in symbols
            if symbol not in self._asset_symbols
            and self._meta_by_symbol.get(symbol, 0) > 0
        ]

        missing_meta = [
            symbol
            for symbol in symbols
            if symbol not in self._asset_symbols
            and self._meta_by_symbol.get(symbol, 0) <= 0
        ]

        if missing_meta:
            self.logger.warning(
                "Opções sem option_series_id: %s.",
                ", ".join(missing_meta),
            )

        acquired = set(self._acquire_leases_batch(option_ids))

        selected = [
            symbol
            for symbol in symbols
            if symbol in self._asset_symbols
            or self._meta_by_symbol.get(symbol) in acquired
        ]

        if not selected:
            return []

        self.connect()

        if any(
            symbol not in self._asset_symbols
            for symbol in selected
        ):
            self._warmup_asset()

        configured: list[str] = []
        options_in_group = 0

        for symbol in selected:
            failed = False

            for field in fields_list:
                key = (symbol, field)

                if key in self._subs:
                    continue

                cell = f"A{self._row}"
                formula = self._formula(symbol, field)

                self.logger.info(
                    "Fórmula RTD gerada: célula=%s; %s",
                    cell,
                    formula,
                )

                try:
                    self._write_formula(cell, formula)
                except Exception as exc:
                    failed = True
                    self.logger.warning(
                        "Falha ao configurar %s.%s em %s: %s. "
                        "Símbolo permanece pendente.",
                        symbol,
                        field,
                        cell,
                        exc,
                    )
                    break

                self._subs[key] = cell
                self._field_created_at[key] = time.monotonic()
                self._row += 1

            if failed:
                break

            if all(
                (symbol, field) in self._subs
                for field in fields_list
            ):
                configured.append(symbol)

            if symbol not in self._asset_symbols:
                options_in_group += 1

                if options_in_group >= OPTION_GROUP_SIZE:
                    self._wait_with_message_pump(
                        OPTION_GROUP_WAIT_SECONDS
                    )
                    options_in_group = 0

        self.logger.info(
            "RTD configurado: símbolos=%s campos_por_símbolo=%s "
            "tempo_total=%.2fs.",
            len(configured),
            len(fields_list),
            time.perf_counter() - started_at,
        )

        missing = set(symbols) - set(configured)

        if missing:
            self.logger.warning(
                "RTD ainda sem configuração completa: %s.",
                ", ".join(sorted(missing)),
            )

        return configured

    def _restore_one_pending_formula(self) -> None:
        now = time.monotonic()

        for key in sorted(self._restore_pending):
            if now < self._field_next_retry_at.get(key, 0.0):
                continue

            cell = self._subs.get(key)

            if cell is None:
                self._restore_pending.discard(key)
                continue

            symbol, field = key

            try:
                self._write_formula(
                    cell,
                    self._formula(symbol, field),
                )
            except Exception as exc:
                self._field_next_retry_at[key] = (
                    time.monotonic() + INVALID_FIELD_RETRY_SECONDS
                )
                self.logger.warning(
                    "Reescrita de %s.%s ainda pendente: %s.",
                    symbol,
                    field,
                    exc,
                )
            else:
                self._restore_pending.discard(key)
                self._field_next_retry_at[key] = (
                    time.monotonic() + INVALID_FIELD_RETRY_SECONDS
                )
                self.logger.info(
                    "Fórmula restaurada: %s.%s em %s.",
                    symbol,
                    field,
                    cell,
                )

            # No máximo uma restauração por rodada.
            return

    def _recover_one_invalid_field(
        self,
        values_by_key: dict[tuple[str, str], object],
    ) -> tuple[str, str] | None:
        now = time.monotonic()

        for key, value in values_by_key.items():
            if not self._is_invalid_asset(value):
                continue

            if key in self._restore_pending:
                continue

            symbol, field = key

            if symbol not in self._asset_symbols:
                option_id = self._meta_by_symbol.get(symbol)

                if option_id not in self._leased_option_ids:
                    continue

            created_at = self._field_created_at.get(key, now)

            if now - created_at < INVALID_FIELD_GRACE_SECONDS:
                continue

            if now < self._field_next_retry_at.get(key, 0.0):
                continue

            attempts = self._field_retry_count.get(key, 0)

            if attempts >= INVALID_FIELD_MAX_RETRIES:
                if key not in self._retry_exhausted:
                    self._retry_exhausted.add(key)
                    self.logger.warning(
                        "Campo permanece inválido: %s.%s após %s "
                        "reassinaturas. Fórmula mantida; "
                        "sem novas reassinaturas nesta demanda.",
                        symbol,
                        field,
                        attempts,
                    )
                continue

            cell = self._subs[key]
            attempt = attempts + 1

            self._field_retry_count[key] = attempt
            self._field_next_retry_at[key] = (
                now + INVALID_FIELD_RETRY_SECONDS
            )

            try:
                self._com_call(
                    f"limpar campo inválido {symbol}.{field}",
                    lambda cell=cell: self._ws.Range(
                        cell
                    ).ClearContents(),
                )

                # Se a reescrita falhar, a próxima rodada restaura
                # a fórmula antes de considerar outra recuperação.
                self._restore_pending.add(key)

                self._wait_with_message_pump(
                    INVALID_FIELD_CLEAR_WAIT_SECONDS
                )

                self._write_formula(
                    cell,
                    self._formula(symbol, field),
                )
                self._restore_pending.discard(key)

            except Exception as exc:
                self.logger.warning(
                    "Falha na reassinatura de %s.%s "
                    "tentativa=%s/%s: %s.",
                    symbol,
                    field,
                    attempt,
                    INVALID_FIELD_MAX_RETRIES,
                    exc,
                )
            else:
                self.logger.info(
                    "Campo RTD reassinado: %s.%s célula=%s "
                    "tentativa=%s/%s. Demais fórmulas preservadas.",
                    symbol,
                    field,
                    cell,
                    attempt,
                    INVALID_FIELD_MAX_RETRIES,
                )

            # No máximo um campo reassinado por rodada.
            return key

        return None

    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        self._release_pending_leases()

        if not self._subs:
            return []

        self._renew_leases_if_needed()

        if not self._is_connected():
            self.connect()

        self._restore_one_pending_formula()
        self._wait_with_message_pump(timeout_seconds)

        last_row = self._row - 1

        if last_row < 1:
            return []

        try:
            values = self._com_call(
                "ler células RTD",
                lambda: self._ws.Range(
                    f"A1:A{last_row}"
                ).Value,
            )
        except Exception as exc:
            if self._is_transient_com_error(exc):
                self.logger.warning(
                    "Leitura rejeitada após %s tentativas. "
                    "Rodada ignorada; Excel preservado.",
                    COM_MAX_ATTEMPTS,
                )
                return []

            self.logger.exception(
                "Falha não transitória de leitura. "
                "Conexão será recriada com fórmulas preservadas."
            )
            self._reset_excel()
            return []

        if values is None:
            return []

        if last_row == 1:
            if isinstance(values, (tuple, list)):
                if values and isinstance(values[0], (tuple, list)):
                    normalized = values
                else:
                    normalized = (tuple(values),)
            else:
                normalized = ((values,),)
        else:
            normalized = values

        values_by_key: dict[tuple[str, str], object] = {}

        for key, cell in list(self._subs.items()):
            index = int(cell[1:]) - 1

            if index < len(normalized):
                values_by_key[key] = normalized[index][0]

        now = time.monotonic()

        for key, value in values_by_key.items():
            if self._is_invalid_asset(value):
                self._invalid_fields.add(key)
            elif self._is_numeric(value) and key in self._invalid_fields:
                self._invalid_fields.discard(key)
                self.logger.info(
                    "Campo RTD passou de inválido para numérico: "
                    "%s.%s=%r; reassinaturas=%s.",
                    key[0],
                    key[1],
                    value,
                    self._field_retry_count.get(key, 0),
                )

        if now - self._last_diagnostic_at >= RTD_DIAGNOSTIC_INTERVAL_SECONDS:
            self._last_diagnostic_at = now

            for (symbol, field), value in values_by_key.items():
                self.logger.info(
                    "Diagnóstico RTD: %s.%s=%r",
                    symbol,
                    field,
                    value,
                )

        recovered_key = self._recover_one_invalid_field(
            values_by_key
        )

        updates: list[RTDUpdate] = []
        timestamp = now_iso_sp()

        for key, value in values_by_key.items():
            symbol, field = key

            if key == recovered_key or key in self._restore_pending:
                continue

            if symbol not in self._asset_symbols:
                option_id = self._meta_by_symbol.get(symbol)

                if option_id not in self._leased_option_ids:
                    continue

            if value is None:
                continue

            if isinstance(value, str) and value.startswith("#"):
                continue

            updates.append(
                RTDUpdate(
                    rtd_symbol=symbol,
                    field=field,
                    value=value,
                    timestamp=timestamp,
                )
            )

        return updates

    def _is_connected(self) -> bool:
        return (
            self._excel is not None
            and self._wb is not None
            and self._ws is not None
        )

    def close(self) -> None:
        started_at = time.perf_counter()
        self._dispose_excel()

        self._leases_to_release.update(self._leased_option_ids)
        self._leased_option_ids.clear()

        requested = len(self._leases_to_release)
        removed = 0
        confirmed = 0

        try:
            removed, confirmed = self._release_pending_leases(
                force=True
            )

            if self._leases_to_release:
                self.logger.warning(
                    "Encerramento com %s liberações não confirmadas.",
                    len(self._leases_to_release),
                )
        finally:
            self._subs.clear()
            self._meta_by_symbol.clear()
            self._asset_symbols.clear()
            self._leased_option_ids.clear()
            self._leases_to_release.clear()
            self._clear_recovery_state()

            self._row = 1
            self._last_lease_renewal_at = 0.0
            self._next_lease_attempt_at = 0.0
            self._next_release_attempt_at = 0.0
            self._last_diagnostic_at = 0.0

            self._http.close()

            if self._com_initialized and pythoncom:
                pythoncom.CoUninitialize()
                self._com_initialized = False

        self.logger.info(
            "RTD encerrado: removidos=%s confirmados=%s de %s "
            "tempo=%.2fs.",
            removed,
            confirmed,
            requested,
            time.perf_counter() - started_at,
        )


class ProfitApiRtdClient(BaseRTDClient):
    """Placeholder para integração API/plugin."""

    def connect(self) -> None:
        raise NotImplementedError(
            "Integração Profit API/plugin ainda não implementada."
        )

    def subscribe(
        self,
        rtd_symbol: str,
        fields: Iterable[str],
    ) -> None:
        raise NotImplementedError

    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SimulatedRTDClient(BaseRTDClient):
    def __init__(self):
        self._subs: dict[str, dict[str, float]] = {}
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def reset_subscriptions(self) -> None:
        self._subs.clear()

    def subscribe(
        self,
        rtd_symbol: str,
        fields: Iterable[str],
    ) -> None:
        base = 1.0 + random.uniform(0.1, 20)

        available = {
            "ULT": base,
            "OCP": max(0.01, base - 0.05),
            "OVD": base + 0.05,
        }

        self._subs[rtd_symbol] = {
            field: available[field]
            for field in dict.fromkeys(fields)
            if field in available
        }

    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        time.sleep(max(0.0, timeout_seconds))
        updates: list[RTDUpdate] = []

        for symbol, values in self._subs.items():
            if "ULT" in values:
                values["ULT"] = max(
                    0.01,
                    values["ULT"] + random.uniform(-0.03, 0.03),
                )

            last = values.get("ULT", 1.0)

            if "OCP" in values:
                values["OCP"] = max(0.01, last - 0.03)

            if "OVD" in values:
                values["OVD"] = last + 0.03

            timestamp = now_iso_sp()

            for field, value in values.items():
                updates.append(
                    RTDUpdate(
                        rtd_symbol=symbol,
                        field=field,
                        value=round(value, 2),
                        timestamp=timestamp,
                    )
                )

        return updates

    def close(self) -> None:
        self._subs.clear()
        self._connected = False


def create_rtd_client(
    mode: str,
    logger: logging.Logger,
    server_url: str = "",
    api_key: str = "",
) -> BaseRTDClient:
    selected = mode.lower().strip()

    if selected in {"excel_bridge", "excel", "com"}:
        return ExcelBridgeRTDClient(
            logger,
            server_url=server_url,
            api_key=api_key,
        )

    if selected in {"com_probe", "probe"}:
        return ComProbeRTDClient(logger)

    if selected == "profit_api":
        return ProfitApiRtdClient()

    if selected == "simulate":
        return SimulatedRTDClient()

    raise ValueError(
        "Modo RTD inválido. Use excel_bridge, com_probe, "
        "profit_api ou simulate."
    )