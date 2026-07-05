"""add event logs

Revision ID: 20260705_0024
Revises: 20260705_0023
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260705_0024"
down_revision: str | None = "20260705_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "event_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("recommendation_id", sa.String(length=128), nullable=True),
        sa.Column("product_id", sa.String(length=128), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("page", sa.String(length=255), nullable=True),
        sa.Column("cart_id", sa.BigInteger(), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(event_id)) > 0", name="ck_event_logs_event_id_not_blank"),
        sa.CheckConstraint("length(trim(event_name)) > 0", name="ck_event_logs_event_name_not_blank"),
        sa.CheckConstraint("rank is null or rank > 0", name="ck_event_logs_rank_positive"),
        sa.CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="ck_event_logs_metadata_is_object"),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_event_logs_event_id"),
    )
    op.create_index(
        "ix_event_logs_anonymous_session_occurred_at",
        "event_logs",
        ["anonymous_user_id", "session_id", "occurred_at"],
    )
    op.create_index("ix_event_logs_cart_id", "event_logs", ["cart_id"])
    op.create_index("ix_event_logs_event_name_occurred_at", "event_logs", ["event_name", "occurred_at"])
    op.create_index("ix_event_logs_order_id", "event_logs", ["order_id"])
    op.create_index("ix_event_logs_product_event_occurred_at", "event_logs", ["product_id", "event_name", "occurred_at"])
    op.create_index("ix_event_logs_recommendation_id_occurred_at", "event_logs", ["recommendation_id", "occurred_at"])
    op.create_index("ix_event_logs_request_id", "event_logs", ["request_id"])
    op.create_index("ix_event_logs_user_id_occurred_at", "event_logs", ["user_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_event_logs_user_id_occurred_at", table_name="event_logs")
    op.drop_index("ix_event_logs_request_id", table_name="event_logs")
    op.drop_index("ix_event_logs_recommendation_id_occurred_at", table_name="event_logs")
    op.drop_index("ix_event_logs_product_event_occurred_at", table_name="event_logs")
    op.drop_index("ix_event_logs_order_id", table_name="event_logs")
    op.drop_index("ix_event_logs_event_name_occurred_at", table_name="event_logs")
    op.drop_index("ix_event_logs_cart_id", table_name="event_logs")
    op.drop_index("ix_event_logs_anonymous_session_occurred_at", table_name="event_logs")
    op.drop_table("event_logs")
