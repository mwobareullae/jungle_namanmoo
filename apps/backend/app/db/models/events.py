from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


class EventLog(Base):
    __tablename__ = "event_logs"
    __table_args__ = (
        CheckConstraint("length(trim(event_id)) > 0", name="ck_event_logs_event_id_not_blank"),
        CheckConstraint("length(trim(event_name)) > 0", name="ck_event_logs_event_name_not_blank"),
        CheckConstraint("rank is null or rank > 0", name="ck_event_logs_rank_positive"),
        UniqueConstraint("event_id", name="uq_event_logs_event_id"),
        Index("ix_event_logs_event_name_occurred_at", "event_name", "occurred_at"),
        Index("ix_event_logs_recommendation_id_occurred_at", "recommendation_id", "occurred_at"),
        Index("ix_event_logs_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_event_logs_anonymous_session_occurred_at", "anonymous_user_id", "session_id", "occurred_at"),
        Index("ix_event_logs_product_event_occurred_at", "product_id", "event_name", "occurred_at"),
        Index("ix_event_logs_request_id", "request_id"),
        Index("ix_event_logs_cart_id", "cart_id"),
        Index("ix_event_logs_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    anonymous_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cart_id: Mapped[int | None] = mapped_column(ForeignKey("carts.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
