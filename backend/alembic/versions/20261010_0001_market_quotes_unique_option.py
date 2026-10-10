"""market_quotes: uma cotação única por opção

Revision ID: 20261010_0001
Revises: 20261009_0001
Create Date: 2026-10-10
"""


from alembic import op
import sqlalchemy as sa



revision = "20261010_0001"
down_revision = "20261009_0001"
branch_labels = None
depends_on = None



def upgrade() -> None:
    op.execute(
        """
        DELETE FROM market_quotes
        WHERE option_series_id IS NULL
        """
    )

    op.execute(
        """
        DELETE FROM market_quotes a
        USING market_quotes b
        WHERE a.option_series_id = b.option_series_id
          AND a.id < b.id
        """
    )

    op.drop_constraint(
        "uq_market_dup",
        "market_quotes",
        type_="unique",
    )

    op.alter_column(
        "market_quotes",
        "option_series_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_market_quotes_option_series",
        "market_quotes",
        ["option_series_id"],
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_quotes_option_ts_desc
        ON market_quotes (option_series_id, quote_timestamp DESC)
        """
    )



def downgrade() -> None:
    op.drop_constraint(
        "uq_market_quotes_option_series",
        "market_quotes",
        type_="unique",
    )

    op.alter_column(
        "market_quotes",
        "option_series_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_unique_constraint(
        "uq_market_dup",
        "market_quotes",
        ["option_series_id", "quote_timestamp", "last_price", "bid", "ask"],
    )
