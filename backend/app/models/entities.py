import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)


from sqlalchemy.orm import Mapped, mapped_column, relationship


from app.models.base import Base, TimestampMixin



class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"



class OptionType(str, enum.Enum):
    CALL = "CALL"
    PUT = "PUT"



class Theme(str, enum.Enum):
    light = "light"
    dark = "dark"



class User(Base, TimestampMixin):
    __tablename__ = "users"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False, default=UserRole.user)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)



class Asset(Base, TimestampMixin):
    __tablename__ = "assets"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    market: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tick_min: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    strike_interval: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    lower_range_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    upper_range_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    rtd_identifier_pattern: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL")



class OptionSeries(Base, TimestampMixin):
    __tablename__ = "option_series"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    option_symbol: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    option_type: Mapped[OptionType] = mapped_column(Enum(OptionType, name="option_type"), nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiration_month: Mapped[str] = mapped_column(String(3), nullable=False)
    tolerance_applied: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="B3", nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


    asset: Mapped[Asset] = relationship("Asset")


    __table_args__ = (
        Index("ix_option_series_asset_strike_exp", "asset_id", "strike", "expiration_date"),
        Index("ix_option_series_asset_type", "asset_id", "option_type"),
        Index("ix_option_series_symbol", "option_symbol"),
    )



class AssetQuote(Base):
    __tablename__ = "asset_quotes"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    last_price: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    variation_points: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    variation_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    high: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    low: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    quote_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    data_status: Mapped[str] = mapped_column(String(10), nullable=False, default="OK")



class MarketQuote(Base):
    """
    Cotação atual de uma opção.

    Regra de negócio:
    - Existe apenas uma linha por option_series_id.
    - O primeiro cliente que capturar a opção cria a linha.
    - Os demais clientes apenas atualizam essa mesma linha.
    - A atualização ocorre somente quando last_price, bid ou ask mudam.
    """
    __tablename__ = "market_quotes"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    option_series_id: Mapped[int] = mapped_column(
        ForeignKey("option_series.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    last_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    ask: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)

    quote_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source: Mapped[str] = mapped_column(String(30), nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    data_status: Mapped[str] = mapped_column(String(10), nullable=False, default="OK")

    sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("nextval('market_quote_sequence')"),
    )

    option_series: Mapped[OptionSeries] = relationship("OptionSeries")

    __table_args__ = (
        Index(
            "ix_market_quotes_option_ts_desc",
            "option_series_id",
            "quote_timestamp",
        ),
        Index(
            "ix_market_quotes_asset_ts",
            "asset_id",
            "quote_timestamp",
        ),
    )



class Client(Base):
    __tablename__ = "clients"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_name: Mapped[str] = mapped_column(String(120), nullable=False)
    computer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)



class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    selected_asset: Mapped[str] = mapped_column(String(30), nullable=False, default="BOVA11")
    selected_strike: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    expiration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    show_calls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_puts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    refresh_interval: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    theme: Mapped[Theme] = mapped_column(Enum(Theme, name="theme"), default=Theme.light, nullable=False)



class SynchronizationLog(Base):
    __tablename__ = "synchronization_logs"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    __table_args__ = (
        Index("ix_sync_logs_created_at", "created_at"),
    )



class SystemSetting(Base):
    __tablename__ = "system_settings"


    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)



class Lease(Base):
    __tablename__ = "leases"


    option_series_id: Mapped[int] = mapped_column(
        ForeignKey("option_series.id", ondelete="CASCADE"),
        primary_key=True,
    )

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


    option_series: Mapped[OptionSeries] = relationship("OptionSeries")
    client: Mapped[Client] = relationship("Client")


    __table_args__ = (
        Index("ix_leases_expires_at", "expires_at"),
    )