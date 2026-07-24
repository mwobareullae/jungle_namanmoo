"""add Olive Young availability to home coarse features

Revision ID: 20260724_0057
Revises: 20260720_0056
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0057"
down_revision: str | None = "20260720_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_recommendation_coarse_features",
        sa.Column(
            "home_oliveyoung_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "product_recommendation_coarse_features",
        "home_oliveyoung_available",
    )
