"""add leases table

Revision ID: 20261009_0001
Revises: 20261008_0001
Create Date: 2026-10-09
"""


from alembic import op
import sqlalchemy as sa


revision = "20261009_0001"
down_revision = "20261008_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leases",
        sa.Column(
            "option_series_id",
            sa.Integer(),
            sa.ForeignKey("option_series.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_leases_expires_at", "leases", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_leases_expires_at", table_name="leases")
    op.drop_table("leases")