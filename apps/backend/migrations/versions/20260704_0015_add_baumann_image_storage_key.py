"""add baumann type image storage key

Revision ID: 20260704_0015
Revises: 20260704_0014
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0015"
down_revision: str | None = "20260704_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "baumann_type_profiles",
        sa.Column("image_storage_key", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("baumann_type_profiles", "image_storage_key")
