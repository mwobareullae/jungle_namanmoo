"""add agent request idempotency records

Revision ID: 20260716_0044
Revises: 20260716_0043
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_0044"
down_revision: str | None = "20260716_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "agent_request_executions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("principal_key", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("response_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('PENDING', 'COMPLETED', 'FAILED')",
            name="ck_agent_request_executions_status",
        ),
        sa.CheckConstraint(
            "length(trim(principal_key)) > 0",
            name="ck_agent_request_executions_principal_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_agent_request_executions_idempotency_key_not_blank",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "principal_key",
            "idempotency_key",
            name="uq_agent_request_executions_principal_idempotency_key",
        ),
    )
    op.create_index(
        "ix_agent_request_executions_status_updated_at",
        "agent_request_executions",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_request_executions_status_updated_at", table_name="agent_request_executions")
    op.drop_table("agent_request_executions")
