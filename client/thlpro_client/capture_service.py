from __future__ import annotations

import logging
from decimal import Decimal
from threading import Event, Lock
from typing import Any

from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.rtd_client import BaseRTDClient
from thlpro_client.timezone_utils import now_iso_sp


def map_series_by_rtd(config_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = config_payload.get("assets", [])
    active_series = config_payload.get("active_series", [])
    symbols = [a.get("symbol", "") for a in assets if a.get("symbol")]

    def _asset_root(sym: str) -> str:
        i = len(sym)
        while i > 0 and sym[i - 1].isdigit():
            i -= 1
        return sym[:i] if i > 0 else sym

    roots = sorted([(sym, _asset_root(sym)) for sym in symbols], key=lambda x: len(x[1]), reverse=True)

    def infer_asset(option_symbol: str) -> str:
        for sym, root in roots:
            if root and option_symbol.startswith(root):
                return sym
        return symbols[0] if symbols else "BOVA11"

    result: dict[str, dict[str, Any]] = {}
    for row in active_series:
        result[row["rtd_symbol"]] = {
            "asset": infer_asset(row["option_symbol"]),
            "option_symbol": row["option_symbol"],
            "option_type": row["option_type"],
            "strike": str(row["strike"]),
            "expiration_date": row["expiration_date"],
        }
    return result


class CaptureService:
    def __init__(
        self,
        logger: logging.Logger,
        rtd_client: BaseRTDClient,
        deduplicator: QuoteDeduplicator,
        queue_enqueue,
        simulation_mode: bool,
    ):
        self.logger = logger
        self.rtd_client = rtd_client
        self.deduplicator = deduplicator
        self.queue_enqueue = queue_enqueue
        self.simulation_mode = simulation_mode
        self._stop = Event()
        self._pause = Event()
        self._pause.set()
        self._lock = Lock()
        self._last_values: dict[str, dict[str, Any]] = {}
        self._meta_by_rtd: dict[str, dict[str, Any]] = {}

    def configure_series(self, config_payload: dict[str, Any]) -> int:
        with self._lock:
            self._meta_by_rtd = map_series_by_rtd(config_payload)
            self._last_values.clear()
            for rtd_symbol in self._meta_by_rtd:
                self.rtd_client.subscribe(rtd_symbol, ["ULT", "OCP", "OVD", "VEN", "PEX"])
        return len(self._meta_by_rtd)

    def start_capture(self):
        self._pause.clear()

    def stop_capture(self):
        self._pause.set()

    def stop(self):
        self._stop.set()

    def run_forever(self):
        self.rtd_client.connect()
        source = "SIMULATED" if self.simulation_mode else "Profit RTD"
        self.logger.info("Serviço de captura iniciado. source=%s", source)

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(0.2)
                continue

            updates = self.rtd_client.poll_updates(timeout_seconds=0.5)
            rows: list[dict[str, Any]] = []
            with self._lock:
                for upd in updates:
                    meta = self._meta_by_rtd.get(upd.rtd_symbol)
                    if not meta:
                        continue
                    bucket = self._last_values.setdefault(upd.rtd_symbol, {"ULT": None, "OCP": None, "OVD": None})
                    bucket[upd.field] = upd.value
                    payload = {
                        "asset": meta["asset"],
                        "option_symbol": meta["option_symbol"],
                        "last_price": bucket.get("ULT"),
                        "bid": bucket.get("OCP"),
                        "ask": bucket.get("OVD"),
                        "premium": bucket.get("ULT"),
                        "quote_timestamp": upd.timestamp or now_iso_sp(),
                        "source": source,
                        "data_status": "OK",
                    }
                    if self.deduplicator.should_send(payload):
                        rows.append(payload)
            if rows:
                self.queue_enqueue(rows)
                self.logger.info("Captura: %s atualizações relevantes enfileiradas.", len(rows))
