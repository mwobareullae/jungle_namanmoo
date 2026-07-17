from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


AGENT_TOOL_CALL_STATUS_VALUES = (
    "'PROPOSED', 'AWAITING_CONFIRMATION', 'CONFIRMED', 'EXECUTED', "
    "'REJECTED', 'EXPIRED', 'FAILED'"
)

AGENT_REQUEST_EXECUTION_STATUS_VALUES = "'PENDING', 'COMPLETED', 'FAILED'"


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        CheckConstraint("length(trim(tool_call_id)) > 0", name="ck_agent_tool_calls_tool_call_id_not_blank"),
        CheckConstraint("length(trim(tool_name)) > 0", name="ck_agent_tool_calls_tool_name_not_blank"),
        CheckConstraint(f"status in ({AGENT_TOOL_CALL_STATUS_VALUES})", name="ck_agent_tool_calls_status"),
        CheckConstraint("latency_ms is null or latency_ms >= 0", name="ck_agent_tool_calls_latency_non_negative"),
        UniqueConstraint("tool_call_id", name="uq_agent_tool_calls_tool_call_id"),
        Index("ix_agent_tool_calls_user_created_at", "user_id", "created_at"),
        Index("ix_agent_tool_calls_conversation_created_at", "conversation_id", "created_at"),
        Index("ix_agent_tool_calls_status_expires_at", "status", "expires_at"),
        Index("ix_agent_tool_calls_request_id", "request_id"),
        Index("ix_agent_tool_calls_session_created_at", "session_id", "created_at"),
        Index("ix_agent_tool_calls_tool_status_created_at", "tool_name", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    anonymous_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PROPOSED", server_default="PROPOSED")
    confirmation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentRequestExecution(Base):
    """Stores an agent request result so a browser retry cannot repeat a write tool."""

    __tablename__ = "agent_request_executions"
    __table_args__ = (
        CheckConstraint(
            f"status in ({AGENT_REQUEST_EXECUTION_STATUS_VALUES})",
            name="ck_agent_request_executions_status",
        ),
        CheckConstraint(
            "length(trim(principal_key)) > 0",
            name="ck_agent_request_executions_principal_key_not_blank",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_agent_request_executions_idempotency_key_not_blank",
        ),
        UniqueConstraint(
            "principal_key",
            "idempotency_key",
            name="uq_agent_request_executions_principal_idempotency_key",
        ),
        Index("ix_agent_request_executions_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    principal_key: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    response_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
