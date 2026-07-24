"""add independent home evidence pick features

Revision ID: 20260724_0059
Revises: 20260724_0058
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0059"
down_revision: str | None = "20260724_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_evidence_pick_features",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("max_evidence_score", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("max_effect_score", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("lowest_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )
    op.create_index(
        "ix_home_evidence_pick_features_current_rank",
        "home_evidence_pick_features",
        ["source_current", "max_evidence_score", "max_effect_score", "lowest_price"],
    )


def downgrade() -> None:
    op.drop_index("ix_home_evidence_pick_features_current_rank", table_name="home_evidence_pick_features")
    op.drop_table("home_evidence_pick_features")
