"""prepare search document embeddings

Revision ID: 20260629_0002
Revises: 20260627_0001
Create Date: 2026-06-29 04:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0002"
down_revision: str | None = "20260627_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            """
            ALTER TABLE search_documents
            ALTER COLUMN embedding TYPE vector(1536)
            USING CASE
                WHEN embedding IS NULL OR embedding = '' THEN NULL
                ELSE embedding::vector
            END
            """
        )

    op.add_column("search_documents", sa.Column("embedding_model", sa.String(length=80), nullable=True))
    op.add_column("search_documents", sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
    op.add_column("search_documents", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_search_documents_embedding_model", "search_documents", ["embedding_model"])


def downgrade() -> None:
    op.drop_index("ix_search_documents_embedding_model", table_name="search_documents")
    op.drop_column("search_documents", "embedding_updated_at")
    op.drop_column("search_documents", "embedding_dimensions")
    op.drop_column("search_documents", "embedding_model")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE search_documents
            ALTER COLUMN embedding TYPE text
            USING embedding::text
            """
        )
