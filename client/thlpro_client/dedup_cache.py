from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any


@dataclass
class QuoteState:
    last_price: float | None
    bid: float | None
    ask: float | None
    timestamp: str
    sent_at_monotonic: float


class QuoteDeduplicator:
    def __init__(self, min_interval_ms: int = 500):
        self.min_interval_ms = min_interval_ms
        self._state: dict[str, QuoteState] = {}

    def should_send(self, payload: dict[str, Any]) -> bool:
        symbol = payload["option_symbol"]
        now_mono = monotonic()
        cur = QuoteState(
            last_price=payload.get("last_price"),
            bid=payload.get("bid"),
            ask=payload.get("ask"),
            timestamp=payload.get("quote_timestamp", ""),
            sent_at_monotonic=now_mono,
        )
        old = self._state.get(symbol)
        if not old:
            self._state[symbol] = cur
            return True

        changed = any([
            old.last_price != cur.last_price,
            old.bid != cur.bid,
            old.ask != cur.ask,
            old.timestamp != cur.timestamp,
        ])
        if not changed:
            return False

        elapsed_ms = (now_mono - old.sent_at_monotonic) * 1000.0
        if elapsed_ms < self.min_interval_ms:
            return False

        self._state[symbol] = cur
        return True
