"""add order cancel request records

Revision ID: 20260713_0041
Revises: 20260713_0040
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0041"
down_revision: str | None = "20260713_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_cancel_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_code", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="REQUESTED", nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('REQUESTED', 'APPROVED', 'REJECTED')",
            name="ck_order_cancel_requests_status",
        ),
        sa.CheckConstraint(
            "length(trim(request_code)) > 0",
            name="ck_order_cancel_requests_request_code_not_blank",
        ),
        sa.CheckConstraint(
            "reason_code is null or length(trim(reason_code)) > 0",
            name="ck_order_cancel_requests_reason_code_not_blank",
        ),
        sa.CheckConstraint(
            "reason_detail is null or length(trim(reason_detail)) > 0",
            name="ck_order_cancel_requests_reason_detail_not_blank",
        ),
        sa.CheckConstraint(
            "decision_reason is null or length(trim(decision_reason)) > 0",
            name="ck_order_cancel_requests_decision_reason_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'REQUESTED' and processed_at is null) or "
            "(status in ('APPROVED', 'REJECTED') and processed_at is not null)",
            name="ck_order_cancel_requests_status_processed_at",
        ),
        sa.CheckConstraint(
            "status <> 'REJECTED' or decision_reason is not null",
            name="ck_order_cancel_requests_rejected_reason",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_code", name="uq_order_cancel_requests_request_code"),
    )
    op.create_index("ix_order_cancel_requests_order_id", "order_cancel_requests", ["order_id"])
    op.create_index("ix_order_cancel_requests_user_id", "order_cancel_requests", ["user_id"])
    op.create_index(
        "ix_order_cancel_requests_order_status",
        "order_cancel_requests",
        ["order_id", "status"],
    )
    op.create_index(
        "ix_order_cancel_requests_user_created_at",
        "order_cancel_requests",
        ["user_id", "created_at"],
    )
    op.create_index(
        "uq_order_cancel_requests_order_requested",
        "order_cancel_requests",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'REQUESTED'"),
        sqlite_where=sa.text("status = 'REQUESTED'"),
    )


def downgrade() -> None:
    op.drop_index("uq_order_cancel_requests_order_requested", table_name="order_cancel_requests")
    op.drop_index("ix_order_cancel_requests_user_created_at", table_name="order_cancel_requests")
    op.drop_index("ix_order_cancel_requests_order_status", table_name="order_cancel_requests")
    op.drop_index("ix_order_cancel_requests_user_id", table_name="order_cancel_requests")
    op.drop_index("ix_order_cancel_requests_order_id", table_name="order_cancel_requests")
    op.drop_table("order_cancel_requests")
