"""add ingredient evidence review status

Revision ID: 20260711_0031
Revises: 20260710_0030
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_0031"
down_revision: str | None = "20260710_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingredient_evidence",
        sa.Column("canonical_evidence_key", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="candidate_unverified",
            nullable=False,
        ),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("result_direction", sa.String(length=16), server_default="unclear", nullable=False),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column(
            "score_use_level",
            sa.String(length=20),
            server_default="reference_only",
            nullable=False,
        ),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("is_representative", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("representative_rank", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "ingredient_evidence",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_ingredient_evidence_review_status",
        "ingredient_evidence",
        "review_status in ('candidate_unverified', 'accepted', 'rejected')",
    )
    op.create_check_constraint(
        "ck_ingredient_evidence_result_direction",
        "ingredient_evidence",
        "result_direction in ('positive', 'negative', 'null', 'unclear')",
    )
    op.create_check_constraint(
        "ck_ingredient_evidence_score_use_level",
        "ingredient_evidence",
        "score_use_level in ('primary', 'supporting', 'reference_only')",
    )
    op.create_check_constraint(
        "ck_ingredient_evidence_representative_rank",
        "ingredient_evidence",
        "representative_rank is null or representative_rank between 1 and 3",
    )
    op.create_check_constraint(
        "ck_ingredient_evidence_rank_requires_representative",
        "ingredient_evidence",
        "is_representative = true or representative_rank is null",
    )
    op.create_check_constraint(
        "ck_ingredient_evidence_representative_eligible",
        "ingredient_evidence",
        "is_representative = false or "
        "(review_status = 'accepted' and is_current = true and representative_rank is not null)",
    )
    op.create_index(
        "ix_ingredient_evidence_canonical_pair",
        "ingredient_evidence",
        ["ingredient_id", "effect_id", "canonical_evidence_key"],
    )
    op.create_index(
        "ix_ingredient_evidence_review_current",
        "ingredient_evidence",
        ["review_status", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingredient_evidence_review_current", table_name="ingredient_evidence")
    op.drop_index("ix_ingredient_evidence_canonical_pair", table_name="ingredient_evidence")
    op.drop_constraint(
        "ck_ingredient_evidence_representative_eligible",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingredient_evidence_rank_requires_representative",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingredient_evidence_representative_rank",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingredient_evidence_score_use_level",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingredient_evidence_result_direction",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingredient_evidence_review_status",
        "ingredient_evidence",
        type_="check",
    )
    op.drop_column("ingredient_evidence", "reviewed_at")
    op.drop_column("ingredient_evidence", "reviewed_by")
    op.drop_column("ingredient_evidence", "review_note")
    op.drop_column("ingredient_evidence", "is_current")
    op.drop_column("ingredient_evidence", "representative_rank")
    op.drop_column("ingredient_evidence", "is_representative")
    op.drop_column("ingredient_evidence", "score_use_level")
    op.drop_column("ingredient_evidence", "result_direction")
    op.drop_column("ingredient_evidence", "review_status")
    op.drop_column("ingredient_evidence", "canonical_evidence_key")
