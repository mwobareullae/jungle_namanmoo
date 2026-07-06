"""add agent tool calls

Revision ID: 20260705_0025
Revises: 20260705_0024
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260705_0025"
down_revision: str | None = "20260705_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())

AGENT_TOOL_CALL_STATUS_VALUES = (
    "'PROPOSED', 'AWAITING_CONFIRMATION', 'CONFIRMED', 'EXECUTED', "
    "'REJECTED', 'EXPIRED', 'FAILED'"
)


def upgrade() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="PROPOSED", nullable=False),
        sa.Column("confirmation_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("output_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(tool_call_id)) > 0",
            name="ck_agent_tool_calls_tool_call_id_not_blank",
        ),
        sa.CheckConstraint("length(trim(tool_name)) > 0", name="ck_agent_tool_calls_tool_name_not_blank"),
        sa.CheckConstraint(f"status in ({AGENT_TOOL_CALL_STATUS_VALUES})", name="ck_agent_tool_calls_status"),
        sa.CheckConstraint("latency_ms is null or latency_ms >= 0", name="ck_agent_tool_calls_latency_non_negative"),
        sa.CheckConstraint("jsonb_typeof(input_json) = 'object'", name="ck_agent_tool_calls_input_is_object"),
        sa.CheckConstraint("jsonb_typeof(output_json) = 'object'", name="ck_agent_tool_calls_output_is_object"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id", name="uq_agent_tool_calls_tool_call_id"),
    )
    op.create_index(
        "ix_agent_tool_calls_conversation_created_at",
        "agent_tool_calls",
        ["conversation_id", "created_at"],
    )
    op.create_index("ix_agent_tool_calls_request_id", "agent_tool_calls", ["request_id"])
    op.create_index("ix_agent_tool_calls_session_created_at", "agent_tool_calls", ["session_id", "created_at"])
    op.create_index("ix_agent_tool_calls_status_expires_at", "agent_tool_calls", ["status", "expires_at"])
    op.create_index(
        "ix_agent_tool_calls_tool_status_created_at",
        "agent_tool_calls",
        ["tool_name", "status", "created_at"],
    )
    op.create_index("ix_agent_tool_calls_user_created_at", "agent_tool_calls", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_user_created_at", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_tool_status_created_at", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_status_expires_at", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_session_created_at", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_request_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_conversation_created_at", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
