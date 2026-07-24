"""add home shortlist popularity and composite scores

Revision ID: 20260724_0058
Revises: 20260724_0057
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0058"
down_revision: str | None = "20260724_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column("home_popularity_score", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column("home_shortlist_score", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("product_recommendation_coarse_features", "home_shortlist_score")
    op.drop_column("product_recommendation_coarse_features", "home_popularity_score")
