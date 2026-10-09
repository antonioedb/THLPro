from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Theme


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    role: str = "user"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("E-mail inválido.")
        return value.lower()


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = None
    active: bool | None = None


class UserPreferenceUpdate(BaseModel):
    selected_asset: str | None = Field(default=None, min_length=1, max_length=30)
    selected_strike: Decimal | None = None
    expiration_count: int | None = Field(default=None, ge=1, le=12)
    show_calls: bool | None = None
    show_puts: bool | None = None
    auto_refresh: bool | None = None
    refresh_interval: int | None = Field(default=None, ge=1, le=60)
    theme: Theme | None = None


class UserPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    selected_asset: str
    selected_strike: Decimal | None
    expiration_count: int
    show_calls: bool
    show_puts: bool
    auto_refresh: bool
    refresh_interval: int
    theme: Theme


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    active: bool
    created_at: datetime
    updated_at: datetime
