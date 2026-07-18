"""add home shortlist fields to recommendation coarse features

Revision ID: 20260718_0050
Revises: 20260717_0049
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0050"
down_revision: str | None = "20260717_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_max_effect_score",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_max_evidence_score",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_lowest_price",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_has_image",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_source_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_recommendation_coarse_home_scores",
        "product_recommendation_coarse_features",
        "home_max_effect_score between 0 and 10000 and home_max_evidence_score between 0 and 10000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_recommendation_coarse_home_scores",
        "product_recommendation_coarse_features",
        type_="check",
    )
    op.drop_column("product_recommendation_coarse_features", "home_source_current")
    op.drop_column("product_recommendation_coarse_features", "home_has_image")
    op.drop_column("product_recommendation_coarse_features", "home_lowest_price")
    op.drop_column("product_recommendation_coarse_features", "home_max_evidence_score")
    op.drop_column("product_recommendation_coarse_features", "home_max_effect_score")
