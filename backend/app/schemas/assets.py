from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AssetBase(BaseModel):
    symbol: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=255)
    asset_type: str = Field(min_length=2, max_length=50)
    market: str = Field(min_length=2, max_length=50)
    enabled: bool = True
    tick_min: Decimal = Decimal("0.01")
    strike_interval: Decimal = Decimal("1")
    lower_range_percent: Decimal = Decimal("10")
    upper_range_percent: Decimal = Decimal("10")
    rtd_identifier_pattern: str = "{SYMBOL}{CODE}_B_0"
    source: str = "MANUAL"


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    tick_min: Decimal | None = None
    strike_interval: Decimal | None = None
    lower_range_percent: Decimal | None = None
    upper_range_percent: Decimal | None = None
    rtd_identifier_pattern: str | None = None


class AssetOut(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class StrikeListResponse(BaseModel):
    asset: str
    spot_price: Decimal | None
    range_low: Decimal | None
    range_high: Decimal | None
    strikes: list[Decimal]
    data_avail: bool
    warning: str | None = None
