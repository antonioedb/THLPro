from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException


def ensure_timestamp(value: datetime | None) -> datetime:
    if value is None:
        raise HTTPException(status_code=422, detail="Timestamp da cotação é obrigatório.")
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="Timestamp deve conter fuso horário.")
    return value.astimezone(UTC)


def validate_future_skew(quote_ts: datetime, max_skew_seconds: int) -> None:
    now = datetime.now(UTC)
    delta = (quote_ts - now).total_seconds()
    if delta > max_skew_seconds:
        raise HTTPException(status_code=422, detail="Timestamp da cotação está no futuro além do limite permitido.")


def round_by_tick(value: Decimal | None, tick: Decimal) -> Decimal | None:
    if value is None:
        return None
    if tick <= 0:
        tick = Decimal("0.01")
    return (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick


def safe_variation_pct(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * Decimal("100")
