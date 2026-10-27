"""add trade_count to market_quotes

Revision ID: 20261020_0001
Revises: 20261010_0001
Create Date: 2026-10-20
"""

from alembic import op
import sqlalchemy as sa



revision = "20261020_0001"
down_revision = "20261010_0001"
branch_labels = None
depends_on = None



def upgrade() -> None:
    op.add_column(
        "market_quotes",
        sa.Column("trade_count", sa.Integer(), nullable=True),
    )



def downgrade() -> None:
    op.drop_column("market_quotes", "trade_count")