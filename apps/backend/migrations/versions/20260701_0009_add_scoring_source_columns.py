"""add scoring source columns

Revision ID: 20260701_0009
Revises: 20260630_0008
Create Date: 2026-07-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_0009"
down_revision: str | None = "20260630_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    product_columns = _existing_columns("products")
    _add_column_if_missing("products", product_columns, sa.Column("functional_review_text", sa.Text(), nullable=True))
    _add_column_if_missing(
        "products",
        product_columns,
        sa.Column("functional_cosmetic_status", sa.String(length=40), nullable=True),
    )
    _add_column_if_missing("products", product_columns, sa.Column("functional_cosmetic_claims", sa.Text(), nullable=True))
    _add_column_if_missing(
        "products",
        product_columns,
        sa.Column("functional_claim_confidence", sa.String(length=20), nullable=True),
    )
    _add_column_if_missing("products", product_columns, sa.Column("functional_claim_basis", sa.Text(), nullable=True))

    evidence_columns = _existing_columns("ingredient_evidence")
    _add_column_if_missing(
        "ingredient_evidence",
        evidence_columns,
        sa.Column("source_type", sa.String(length=40), nullable=True),
    )
    _add_column_if_missing(
        "ingredient_evidence",
        evidence_columns,
        sa.Column("pmid", sa.String(length=40), nullable=True),
    )
    _add_column_if_missing(
        "ingredient_evidence",
        evidence_columns,
        sa.Column("doi", sa.String(length=120), nullable=True),
    )
    _add_column_if_missing(
        "ingredient_evidence",
        evidence_columns,
        sa.Column("source_authority_score", sa.Numeric(5, 4), nullable=True),
    )

    risk_columns = _existing_columns("risk_flags")
    _add_column_if_missing(
        "risk_flags",
        risk_columns,
        sa.Column("severity_score", sa.Numeric(5, 4), nullable=True),
    )
    _add_column_if_missing("risk_flags", risk_columns, sa.Column("applies_to", sa.Text(), nullable=True))
    _add_column_if_missing("risk_flags", risk_columns, sa.Column("condition", sa.Text(), nullable=True))
    _add_column_if_missing(
        "risk_flags",
        risk_columns,
        sa.Column("source_type", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    risk_columns = _existing_columns("risk_flags")
    _drop_column_if_exists("risk_flags", risk_columns, "source_type")
    _drop_column_if_exists("risk_flags", risk_columns, "condition")
    _drop_column_if_exists("risk_flags", risk_columns, "applies_to")
    _drop_column_if_exists("risk_flags", risk_columns, "severity_score")

    evidence_columns = _existing_columns("ingredient_evidence")
    _drop_column_if_exists("ingredient_evidence", evidence_columns, "source_authority_score")
    _drop_column_if_exists("ingredient_evidence", evidence_columns, "doi")
    _drop_column_if_exists("ingredient_evidence", evidence_columns, "pmid")
    _drop_column_if_exists("ingredient_evidence", evidence_columns, "source_type")

    product_columns = _existing_columns("products")
    _drop_column_if_exists("products", product_columns, "functional_claim_basis")
    _drop_column_if_exists("products", product_columns, "functional_claim_confidence")
    _drop_column_if_exists("products", product_columns, "functional_cosmetic_claims")
    _drop_column_if_exists("products", product_columns, "functional_cosmetic_status")
    _drop_column_if_exists("products", product_columns, "functional_review_text")


def _existing_columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, existing_columns: set[str], column: sa.Column) -> None:
    if column.name in existing_columns:
        return
    op.add_column(table_name, column)
    existing_columns.add(column.name)


def _drop_column_if_exists(table_name: str, existing_columns: set[str], column_name: str) -> None:
    if column_name not in existing_columns:
        return
    op.drop_column(table_name, column_name)
    existing_columns.remove(column_name)
