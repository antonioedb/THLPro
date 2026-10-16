from datetime import date, datetime
from decimal import Decimal


from pydantic import BaseModel, ConfigDict, Field



class OptionSeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


    id: int
    asset_id: int
    option_symbol: str
    option_type: str
    strike: Decimal
    expiration_date: date
    expiration_month: str
    tolerance_applied: Decimal | None
    active: bool
    source: str
    needs_review: bool
    created_at: datetime
    updated_at: datetime



class OptionSynchronizeRequest(BaseModel):
    source: str = Field(pattern="^(b3|upload)$")
    asset_id: int | None = None
    b3_url: str | None = Field(
        default=None,
        max_length=1000,
    )



class SyncSummary(BaseModel):
    created: int
    updated: int
    deactivated: int
    errors: list[str]
    warnings: list[str] = Field(default_factory=list)