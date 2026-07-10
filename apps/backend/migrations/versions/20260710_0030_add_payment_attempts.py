"""add payment attempts and uncertain payment states

Revision ID: 20260710_0030
Revises: 20260710_0029
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260710_0030"
down_revision: str | None = "20260710_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_payments_status", "payments", type_="check")
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status in ('READY', 'CONFIRMING', 'UNKNOWN', 'APPROVED', 'FAILED', 'CANCELED', 'EXPIRED', 'REFUND_REQUESTED', 'REFUNDED', 'PARTIALLY_REFUNDED')",
    )

    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_code", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider_payment_key", sa.String(length=255), nullable=True),
        sa.Column("provider_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("provider_error_code", sa.String(length=120), nullable=True),
        sa.Column("provider_error_message", sa.Text(), nullable=True),
        sa.Column("request_summary_json", JSONB, nullable=True),
        sa.Column("response_summary_json", JSONB, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("operation in ('CONFIRM', 'CANCEL')", name="ck_payment_attempts_operation"),
        sa.CheckConstraint("status <> ''", name="ck_payment_attempts_status_not_blank"),
        sa.CheckConstraint("provider in ('MOCK', 'TOSS')", name="ck_payment_attempts_provider"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "attempt_code", name="uq_payment_attempts_payment_attempt_code"),
        sa.UniqueConstraint("provider", "provider_idempotency_key", name="uq_payment_attempts_provider_idempotency_key"),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])
    op.create_index("ix_payment_attempts_payment_requested_at", "payment_attempts", ["payment_id", "requested_at"])
    op.create_index("ix_payment_attempts_status_requested_at", "payment_attempts", ["status", "requested_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_attempts_status_requested_at", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_payment_requested_at", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_payment_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")

    op.drop_constraint("ck_payments_status", "payments", type_="check")
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status in ('READY', 'APPROVED', 'FAILED', 'CANCELED', 'EXPIRED', 'REFUND_REQUESTED', 'REFUNDED', 'PARTIALLY_REFUNDED')",
    )
