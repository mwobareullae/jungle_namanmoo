"""sync product ingredient concentration columns

Revision ID: 20260629_0004
Revises: 20260629_0003
Create Date: 2026-06-29 21:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0004"
down_revision: str | None = "20260629_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = _existing_columns("product_ingredients")

    _add_column_if_missing(existing_columns, sa.Column("concentration_text", sa.String(length=160), nullable=True))
    _add_column_if_missing(existing_columns, sa.Column("concentration_value", sa.Numeric(14, 6), nullable=True))
    _add_column_if_missing(existing_columns, sa.Column("concentration_unit", sa.String(length=16), nullable=True))
    _add_column_if_missing(
        existing_columns,
        sa.Column("concentration_confidence", sa.String(length=20), nullable=True),
    )
    _add_column_if_missing(
        existing_columns,
        sa.Column("normalized_concentration_value", sa.Numeric(14, 8), nullable=True),
    )
    _add_column_if_missing(
        existing_columns,
        sa.Column("normalized_concentration_unit", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    # Compatibility migration for databases created before the data contract gained
    # concentration columns. Keep downgrade as no-op so fresh databases whose 0001
    # already contains these columns do not accidentally lose them.
    pass


def _existing_columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(existing_columns: set[str], column: sa.Column) -> None:
    if column.name in existing_columns:
        return
    op.add_column("product_ingredients", column)
    existing_columns.add(column.name)
