"""add reusable home section snapshots

Revision ID: 20260718_0051
Revises: 20260718_0050
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.types import jsonb_type


revision: str = "20260718_0051"
down_revision: str | None = "20260718_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_section_snapshots",
        sa.Column("section_id", sa.String(length=40), nullable=False),
        sa.Column("context_key", sa.String(length=120), nullable=False),
        sa.Column("rank_order", sa.SmallInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("display_score", sa.SmallInteger(), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("badges", jsonb_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tags", jsonb_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("section_id", "context_key", "rank_order"),
        sa.UniqueConstraint("section_id", "context_key", "product_id", name="uq_home_section_snapshot_product"),
        sa.CheckConstraint("rank_order > 0", name="ck_home_section_snapshot_rank_positive"),
        sa.CheckConstraint("display_score between 0 and 100", name="ck_home_section_snapshot_display_score"),
    )
    op.create_index("ix_home_section_snapshots_product_id", "home_section_snapshots", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_home_section_snapshots_product_id", table_name="home_section_snapshots")
    op.drop_table("home_section_snapshots")