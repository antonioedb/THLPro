"""add last_trade_count and last_trade_date to market_quotes


Revision ID: 20261027_0001
Revises: 20261020_0001
Create Date: 2026-10-27
"""


from alembic import op
import sqlalchemy as sa




revision = "20261027_0001"
down_revision = "20261020_0001"
branch_labels = None
depends_on = None




def upgrade() -> None:
    op.add_column(
        "market_quotes",
        sa.Column("last_trade_count", sa.Integer(), nullable=True),
    )


    op.add_column(
        "market_quotes",
        sa.Column("last_trade_date", sa.Date(), nullable=True),
    )


    op.create_index(
        "ix_market_quotes_last_trade_date",
        "market_quotes",
        ["last_trade_date"],
    )




def downgrade() -> None:
    op.drop_index(
        "ix_market_quotes_last_trade_date",
        table_name="market_quotes",
    )


    op.drop_column("market_quotes", "last_trade_date")


    op.drop_column("market_quotes", "last_trade_count")