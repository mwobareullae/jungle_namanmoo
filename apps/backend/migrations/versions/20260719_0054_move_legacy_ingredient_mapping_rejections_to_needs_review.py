"""move legacy ingredient mapping rejections to needs review

Revision ID: 20260719_0054
Revises: 20260719_0053
Create Date: 2026-07-19

Legacy REJECTED decisions were created before P3 introduced explicit final
non-mapping dispositions.  They are therefore not final classifications and
must return to the temporary review workflow for an explicit decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260719_0054"
down_revision: str | None = "20260719_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE ingredient_mapping_reviews "
            "SET status = 'NEEDS_REVIEW' "
            "WHERE status = 'REJECTED' AND final_disposition IS NULL"
        )
    )


def downgrade() -> None:
    # Rows created by the P3 workflow always have a NEEDS_REVIEW transition
    # event.  Revert only legacy rows that this migration reclassified.
    op.execute(
        sa.text(
            "UPDATE ingredient_mapping_reviews r "
            "SET status = 'REJECTED' "
            "WHERE r.status = 'NEEDS_REVIEW' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM ingredient_mapping_review_events e "
            "  WHERE e.review_id = r.id "
            "    AND (e.from_status = 'NEEDS_REVIEW' OR e.to_status = 'NEEDS_REVIEW')"
            ")"
        )
    )
