"""add recommendation scoring snapshots

Revision ID: 20260716_0044
Revises: 20260716_0043
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_0044"
down_revision: str | None = "20260716_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "product_recommendation_scoring_snapshots",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("scoring_payload", JSONB, nullable=False),
        sa.Column("snapshot_version", sa.String(length=64), nullable=False),
        sa.Column("source_versions", JSONB, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )


def downgrade() -> None:
    op.drop_table("product_recommendation_scoring_snapshots")
