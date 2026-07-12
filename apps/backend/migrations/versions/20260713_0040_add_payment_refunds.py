"""add payment refund records

Revision ID: 20260713_0040
Revises: 20260712_0039
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0040"
down_revision: str | None = "20260712_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("refund_code", sa.String(length=40), nullable=False),
        sa.Column("claim_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="REQUESTED", nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("restocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("provider_refund_key", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('REQUESTED', 'PROCESSING', 'REFUNDED', 'FAILED')",
            name="ck_payment_refunds_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_refunds_amount_positive"),
        sa.ForeignKeyConstraint(["claim_id"], ["order_claims.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", name="uq_payment_refunds_claim_id"),
        sa.UniqueConstraint("refund_code"),
    )
    op.create_index("ix_payment_refunds_claim_id", "payment_refunds", ["claim_id"])
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"])
    op.create_index("ix_payment_refunds_order_id", "payment_refunds", ["order_id"])
    op.create_index("ix_payment_refunds_payment_created_at", "payment_refunds", ["payment_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_refunds_payment_created_at", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_order_id", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_payment_id", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_claim_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")
