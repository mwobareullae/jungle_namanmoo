"""add recommendation coarse features

Revision ID: 20260717_0046
Revises: 20260716_0045
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0046"
down_revision: str | None = "20260716_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EFFECT_SCORE_COLUMNS = (
    "acne_sebum_effect_score",
    "acne_sebum_evidence_score",
    "brightening_effect_score",
    "brightening_evidence_score",
    "calming_effect_score",
    "calming_evidence_score",
    "exfoliation_effect_score",
    "exfoliation_evidence_score",
    "moisture_barrier_effect_score",
    "moisture_barrier_evidence_score",
    "wrinkle_effect_score",
    "wrinkle_evidence_score",
)
FIT_COLUMNS = (
    "dry_fit",
    "oily_fit",
    "combination_fit",
    "normal_fit",
    "dehydrated_oily_fit",
    "sensitive_fit",
)


def upgrade() -> None:
    op.create_table(
        "product_recommendation_coarse_features",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        *(
            sa.Column(
                column,
                sa.SmallInteger(),
                server_default=sa.text("0"),
                nullable=False,
            )
            for column in EFFECT_SCORE_COLUMNS
        ),
        *(sa.Column(column, sa.SmallInteger(), nullable=True) for column in FIT_COLUMNS),
        sa.Column(
            "skin_profile_confidence_code",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source_current",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            " and ".join(f"{column} between 0 and 10000" for column in EFFECT_SCORE_COLUMNS),
            name="ck_recommendation_coarse_effect_scores",
        ),
        sa.CheckConstraint(
            " and ".join(
                f"({column} is null or {column} between 0 and 10000)"
                for column in FIT_COLUMNS
            ),
            name="ck_recommendation_coarse_skin_fits",
        ),
        sa.CheckConstraint(
            "skin_profile_confidence_code between 0 and 3",
            name="ck_recommendation_coarse_confidence_code",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )


def downgrade() -> None:
    op.drop_table("product_recommendation_coarse_features")
