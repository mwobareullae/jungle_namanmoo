"""add order claim tables

Revision ID: 20260712_0039
Revises: 20260712_0038
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260712_0039"
down_revision: str | None = "20260712_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_claims",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("claim_code", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("claim_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="REQUESTED", nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("claim_type in ('RETURN', 'EXCHANGE', 'REFUND')", name="ck_order_claims_claim_type"),
        sa.CheckConstraint(
            "status in ('REQUESTED', 'APPROVED', 'REJECTED', 'IN_PROGRESS', 'COMPLETED', 'WITHDRAWN')",
            name="ck_order_claims_status",
        ),
        sa.CheckConstraint("length(trim(reason_code)) > 0", name="ck_order_claims_reason_code_not_blank"),
        sa.CheckConstraint("refund_amount is null or refund_amount >= 0", name="ck_order_claims_refund_non_negative"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_code"),
    )
    op.create_index("ix_order_claims_order_id", "order_claims", ["order_id"])
    op.create_index("ix_order_claims_user_id", "order_claims", ["user_id"])
    op.create_index("ix_order_claims_user_created_at", "order_claims", ["user_id", "created_at"])
    op.create_index("ix_order_claims_order_status", "order_claims", ["order_id", "status"])

    op.create_table(
        "order_claim_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.BigInteger(), nullable=False),
        sa.Column("order_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity >= 1", name="ck_order_claim_items_quantity_positive"),
        sa.CheckConstraint("resolution in ('REFUND', 'EXCHANGE')", name="ck_order_claim_items_resolution"),
        sa.ForeignKeyConstraint(["claim_id"], ["order_claims.id"]),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "order_item_id", name="uq_order_claim_items_claim_order_item"),
    )
    op.create_index("ix_order_claim_items_claim_id", "order_claim_items", ["claim_id"])
    op.create_index("ix_order_claim_items_order_item_id", "order_claim_items", ["order_item_id"])
    op.create_index("ix_order_claim_items_order_item", "order_claim_items", ["order_item_id"])

    op.create_table(
        "order_claim_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), server_default="SYSTEM", nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(to_status)) > 0", name="ck_order_claim_events_to_status_not_blank"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["claim_id"], ["order_claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_claim_events_claim_id", "order_claim_events", ["claim_id"])
    op.create_index("ix_order_claim_events_claim_created_at", "order_claim_events", ["claim_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_order_claim_events_claim_created_at", table_name="order_claim_events")
    op.drop_index("ix_order_claim_events_claim_id", table_name="order_claim_events")
    op.drop_table("order_claim_events")
    op.drop_index("ix_order_claim_items_order_item", table_name="order_claim_items")
    op.drop_index("ix_order_claim_items_order_item_id", table_name="order_claim_items")
    op.drop_index("ix_order_claim_items_claim_id", table_name="order_claim_items")
    op.drop_table("order_claim_items")
    op.drop_index("ix_order_claims_order_status", table_name="order_claims")
    op.drop_index("ix_order_claims_user_created_at", table_name="order_claims")
    op.drop_index("ix_order_claims_user_id", table_name="order_claims")
    op.drop_index("ix_order_claims_order_id", table_name="order_claims")
    op.drop_table("order_claims")
