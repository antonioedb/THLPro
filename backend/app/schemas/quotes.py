from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class QuoteIn(BaseModel):
    option_series_id: int | None = None

    asset: str = Field(min_length=2, max_length=30)
    option_symbol: str = Field(min_length=2, max_length=40)

    last_price: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    premium: Decimal | None = None

    quote_timestamp: datetime
    source: str = "RTD"
    data_status: str = "OK"


class AssetQuoteIn(BaseModel):
    asset: str = Field(min_length=2, max_length=30)
    last_price: Decimal
    quote_timestamp: datetime
    source: str = "RTD"

    high: Decimal | None = None
    low: Decimal | None = None
    variation_points: Decimal | None = None
    variation_pct: Decimal | None = None
    data_status: str = "OK"


class QuoteReject(BaseModel):
    index: int
    option_symbol: str | None = None
    reason: str


class QuoteBatchResponse(BaseModel):
    accepted: int
    rejected: list[QuoteReject]