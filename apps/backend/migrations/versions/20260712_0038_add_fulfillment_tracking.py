"""add fulfillment timestamps and transition history

Revision ID: 20260712_0038
Revises: 20260712_0037
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0038"
down_revision: str | None = "20260712_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "order_fulfillment_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=40), server_default="ADMIN", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(to_status)) > 0",
            name="ck_order_fulfillment_events_to_status_not_blank",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_fulfillment_events_order_id", "order_fulfillment_events", ["order_id"])
    op.create_index(
        "ix_order_fulfillment_events_order_created_at",
        "order_fulfillment_events",
        ["order_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_fulfillment_events_order_created_at", table_name="order_fulfillment_events")
    op.drop_index("ix_order_fulfillment_events_order_id", table_name="order_fulfillment_events")
    op.drop_table("order_fulfillment_events")
    op.drop_column("orders", "delivered_at")
    op.drop_column("orders", "shipped_at")
