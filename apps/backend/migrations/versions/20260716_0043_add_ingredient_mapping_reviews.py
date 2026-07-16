"""add ingredient mapping review tables

Revision ID: 20260716_0043
Revises: 20260715_0042
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_0043"
down_revision: str | None = "20260715_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ingredient_mapping_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("source_ingredient_name", sa.Text(), nullable=True),
        sa.Column("normalized_source_name", sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column("target_ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('HELD', 'APPROVED', 'REJECTED')",
            name="ck_ingredient_mapping_reviews_status",
        ),
        sa.CheckConstraint(
            "(status = 'APPROVED' and target_ingredient_id is not null) or "
            "(status in ('HELD', 'REJECTED') and target_ingredient_id is null)",
            name="ck_ingredient_mapping_reviews_status_target",
        ),
        sa.CheckConstraint(
            "status not in ('HELD', 'REJECTED') or decision_reason is not null",
            name="ck_ingredient_mapping_reviews_status_reason",
        ),
        sa.CheckConstraint(
            "decision_reason is null or length(trim(decision_reason)) > 0",
            name="ck_ingredient_mapping_reviews_decision_reason_not_blank",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["target_ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_ingredient_id",
            "normalized_source_name",
            name="uq_ingredient_mapping_reviews_source_normalized_name",
        ),
    )
    op.create_index("ix_ingredient_mapping_reviews_status", "ingredient_mapping_reviews", ["status"])

    op.create_table(
        "ingredient_mapping_review_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("from_target_ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("to_target_ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "to_status in ('HELD', 'APPROVED', 'REJECTED')",
            name="ck_ingredient_mapping_review_events_to_status",
        ),
        sa.CheckConstraint(
            "from_status is null or from_status in ('HELD', 'APPROVED', 'REJECTED')",
            name="ck_ingredient_mapping_review_events_from_status",
        ),
        sa.CheckConstraint(
            "(to_status = 'APPROVED' and to_target_ingredient_id is not null) or "
            "(to_status in ('HELD', 'REJECTED') and to_target_ingredient_id is null)",
            name="ck_ingredient_mapping_review_events_to_status_target",
        ),
        sa.CheckConstraint(
            "(from_status is null and from_target_ingredient_id is null) or "
            "(from_status = 'APPROVED' and from_target_ingredient_id is not null) or "
            "(from_status in ('HELD', 'REJECTED') and from_target_ingredient_id is null)",
            name="ck_ingredient_mapping_review_events_from_status_target",
        ),
        sa.CheckConstraint(
            "to_status not in ('HELD', 'REJECTED') or "
            "(reason is not null and length(trim(reason)) > 0)",
            name="ck_ingredient_mapping_review_events_to_status_reason",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_target_ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["ingredient_mapping_reviews.id"]),
        sa.ForeignKeyConstraint(["to_target_ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingredient_mapping_review_events_review_created_at",
        "ingredient_mapping_review_events",
        ["review_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingredient_mapping_review_events_review_created_at",
        table_name="ingredient_mapping_review_events",
    )
    op.drop_table("ingredient_mapping_review_events")
    op.drop_index("ix_ingredient_mapping_reviews_status", table_name="ingredient_mapping_reviews")
    op.drop_table("ingredient_mapping_reviews")
