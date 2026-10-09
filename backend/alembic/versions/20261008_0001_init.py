"""init thlpro backend

Revision ID: 20261008_0001
Revises: 
Create Date: 2026-10-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20261008_0001"
down_revision = None
branch_labels = None
depends_on = None


user_role = sa.Enum("admin", "user", name="user_role")
option_type = sa.Enum("CALL", "PUT", name="option_type")
theme = sa.Enum("light", "dark", name="theme")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("market", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tick_min", sa.Numeric(12, 4), nullable=False),
        sa.Column("strike_interval", sa.Numeric(12, 4), nullable=False),
        sa.Column("lower_range_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("upper_range_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("rtd_identifier_pattern", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="MANUAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_assets_symbol", "assets", ["symbol"], unique=False)

    op.create_table(
        "option_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_symbol", sa.String(length=40), nullable=False),
        sa.Column("option_type", option_type, nullable=False),
        sa.Column("strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("expiration_month", sa.String(length=3), nullable=False),
        sa.Column("tolerance_applied", sa.Numeric(12, 4), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="B3"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("option_symbol"),
    )
    op.create_index("ix_option_series_symbol", "option_series", ["option_symbol"], unique=False)
    op.create_index("ix_option_series_asset_strike_exp", "option_series", ["asset_id", "strike", "expiration_date"], unique=False)
    op.create_index("ix_option_series_asset_type", "option_series", ["asset_id", "option_type"], unique=False)

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_name", sa.String(length=120), nullable=False),
        sa.Column("computer_name", sa.String(length=120), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("api_key_hash"),
    )

    op.create_table(
        "asset_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_price", sa.Numeric(16, 6), nullable=False),
        sa.Column("variation_points", sa.Numeric(16, 6), nullable=True),
        sa.Column("variation_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("high", sa.Numeric(16, 6), nullable=True),
        sa.Column("low", sa.Numeric(16, 6), nullable=True),
        sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("data_status", sa.String(length=10), nullable=False, server_default="OK"),
    )

    op.execute("CREATE SEQUENCE market_quote_sequence START 1")

    op.create_table(
        "market_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_series_id", sa.Integer(), sa.ForeignKey("option_series.id"), nullable=True),
        sa.Column("last_price", sa.Numeric(16, 6), nullable=True),
        sa.Column("bid", sa.Numeric(16, 6), nullable=True),
        sa.Column("ask", sa.Numeric(16, 6), nullable=True),
        sa.Column("premium", sa.Numeric(16, 6), nullable=True),
        sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("data_status", sa.String(length=10), nullable=False, server_default="OK"),
        sa.Column("sequence", sa.BigInteger(), nullable=False, server_default=sa.text("nextval('market_quote_sequence')")),
        sa.UniqueConstraint("option_series_id", "quote_timestamp", "last_price", "bid", "ask", name="uq_market_dup"),
    )
    op.create_index("ix_market_quotes_option_ts_desc", "market_quotes", ["option_series_id", "quote_timestamp"], unique=False)
    op.create_index("ix_market_quotes_asset_ts", "market_quotes", ["asset_id", "quote_timestamp"], unique=False)

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("selected_asset", sa.String(length=30), nullable=False, server_default="BOVA11"),
        sa.Column("selected_strike", sa.Numeric(12, 4), nullable=True),
        sa.Column("expiration_count", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("show_calls", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("show_puts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_refresh", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("refresh_interval", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("theme", theme, nullable=False, server_default="light"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "synchronization_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sync_logs_created_at", "synchronization_logs", ["created_at"], unique=False)

    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_sync_logs_created_at", table_name="synchronization_logs")
    op.drop_table("synchronization_logs")
    op.drop_table("user_preferences")
    op.drop_index("ix_market_quotes_asset_ts", table_name="market_quotes")
    op.drop_index("ix_market_quotes_option_ts_desc", table_name="market_quotes")
    op.drop_table("market_quotes")
    op.execute("DROP SEQUENCE IF EXISTS market_quote_sequence")
    op.drop_table("asset_quotes")
    op.drop_table("clients")
    op.drop_index("ix_option_series_asset_type", table_name="option_series")
    op.drop_index("ix_option_series_asset_strike_exp", table_name="option_series")
    op.drop_index("ix_option_series_symbol", table_name="option_series")
    op.drop_table("option_series")
    op.drop_index("ix_assets_symbol", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    theme.drop(op.get_bind(), checkfirst=True)
    option_type.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
