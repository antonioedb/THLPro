from __future__ import annotations


import abc
import logging
import random
import time
from dataclasses import dataclass
from typing import Iterable


from thlpro_client.compat_windows import IS_WINDOWS
from thlpro_client.timezone_utils import now_iso_sp


try:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
except Exception:  # pragma: no cover
    pythoncom = None
    win32com = None



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
    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        raise NotImplementedError


    @abc.abstractmethod
    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        raise NotImplementedError


    @abc.abstractmethod
    def close(self) -> None:
        raise NotImplementedError



class ComRTDClient(BaseRTDClient):
    """Leitura direta do RTD COM do Profit (mantida para referência/fallback)."""


    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._connected = False
        self._subs: set[tuple[str, str]] = set()
        self._server = None


    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError("COM RTD só disponível em Windows com pywin32 instalado.")
        pythoncom.CoInitialize()
        self._server = win32com.client.Dispatch("rtdtrading.rtdserver")
        self._connected = True
        self.logger.info("Conectado ao servidor COM rtdtrading.rtdserver")


    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        for field in fields:
            self._subs.add((rtd_symbol, field))


    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        if not self._connected:
            return []
        time.sleep(timeout_seconds)
        return []


    def close(self) -> None:
        self._connected = False
        self._subs.clear()
        self._server = None
        if IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()



class ExcelBridgeRTDClient(BaseRTDClient):
    """Lê o RTD do Profit através de uma instância oculta do Excel.


    Usa a fórmula validada em runtime:
    =RTD("rtdtrading.rtdserver";; "BOVA11_B_0"; "ULT")
    """


    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._excel = None
        self._wb = None
        self._ws = None
        self._subs: dict[tuple[str, str], str] = {}  # (symbol, field) -> célula
        self._row = 1


    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError("COM RTD só disponível em Windows com pywin32 instalado.")
        pythoncom.CoInitialize()
        # DispatchEx cria instância nova, sem interferir no Excel aberto pelo usuário
        self._excel = win32com.client.DispatchEx("Excel.Application")
        self._excel.Visible = False
        self._excel.DisplayAlerts = False
        self._wb = self._excel.Workbooks.Add()
        self._ws = self._wb.Worksheets(1)
        self.logger.info("Excel oculto iniciado como ponte RTD")


    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        # Garante que o Excel oculto já foi iniciado
        if self._ws is None:
            self.connect()

        for field in fields:
            key = (rtd_symbol, field)
            if key in self._subs:
                continue
            cell = f"A{self._row}"
            # Fórmula em inglês usa vírgula; tópico vazio = argumento vazio
            formula = f'=RTD("rtdtrading.rtdserver",,"{rtd_symbol}","{field}")'
            self._ws.Range(cell).Formula = formula
            self._subs[key] = cell
            self._row += 1
            self.logger.info("Assinado: %s %s -> %s", rtd_symbol, field, cell)


    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        if not self._is_connected():
            return []
        time.sleep(timeout_seconds)
        updates = []
        ts = now_iso_sp()
        for (symbol, field), cell in self._subs.items():
            value = self._ws.Range(cell).Value
            if value is not None:
                updates.append(RTDUpdate(
                    rtd_symbol=symbol, field=field, value=value, timestamp=ts
                ))
        return updates


    def _is_connected(self) -> bool:
        return self._excel is not None


    def close(self) -> None:
        if self._wb:
            self._wb.Close(SaveChanges=False)
        if self._excel:
            self._excel.Quit()
        self._excel = None
        self._wb = None
        self._ws = None
        self._subs.clear()
        if IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()



class ProfitApiRtdClient(BaseRTDClient):
    """Stub documentado para API/plugin oficial da Nelogica."""


    def connect(self) -> None:
        raise NotImplementedError(
            "Integração Profit API/plugin COM ainda pendente de validação no ambiente Windows real."
        )


    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        raise NotImplementedError


    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        raise NotImplementedError


    def close(self) -> None:
        return



class SimulatedRTDClient(BaseRTDClient):
    def __init__(self):
        self._subs: dict[str, dict[str, float]] = {}
        self._connected = False


    def connect(self) -> None:
        self._connected = True


    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        base = 1.0 + random.uniform(0.1, 20)
        self._subs[rtd_symbol] = {
            "ULT": base,
            "OCP": max(0.01, base - 0.05),
            "OVD": base + 0.05,
            "VEN": 20261016,
            "PEX": random.choice([170, 175, 180, 185, 190, 195, 200]),
        }


    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        time.sleep(timeout_seconds)
        updates: list[RTDUpdate] = []
        for symbol, values in self._subs.items():
            delta = random.uniform(-0.03, 0.03)
            values["ULT"] = max(0.01, values["ULT"] + delta)
            values["OCP"] = max(0.01, values["ULT"] - 0.03)
            values["OVD"] = max(values["OCP"], values["ULT"] + 0.03)
            ts = now_iso_sp()
            for field in ["ULT", "OCP", "OVD"]:
                updates.append(RTDUpdate(rtd_symbol=symbol, field=field, value=round(values[field], 2), timestamp=ts))
        return updates


    def close(self) -> None:
        self._subs.clear()
        self._connected = False



def create_rtd_client(mode: str, logger: logging.Logger) -> BaseRTDClient:
    mode_l = mode.lower()
    if mode_l == "com":
        # Usa a ponte via Excel, que é o caminho validado na sua máquina
        return ExcelBridgeRTDClient(logger)
    if mode_l == "profit_api":
        return ProfitApiRtdClient()
    if mode_l == "simulate":
        return SimulatedRTDClient()
    raise ValueError(f"Modo RTD inválido: {mode}")