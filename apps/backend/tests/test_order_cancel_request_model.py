from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest


@pytest.fixture()
def db_engine() -> Engine:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_order_cancel_request_persists_request_fields(db_engine: Engine) -> None:
    requested_at = datetime(2026, 7, 13, 15, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user, order = _seed_order(session, "persist")
        request = _new_request(user.id, order.id, "ocr_persist", requested_at=requested_at)
        session.add(request)
        session.commit()
        session.refresh(request)

    assert request.status == "REQUESTED"
    assert request.reason_code == "CHANGE_OF_MIND"
    assert request.reason_detail == "고객이 취소를 요청했습니다."
    assert request.decision_reason is None
    assert request.processed_at is None


def test_only_one_requested_cancel_request_is_allowed_per_order(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user, order = _seed_order(session, "duplicate")
        session.add(_new_request(user.id, order.id, "ocr_duplicate_1"))
        session.commit()

        session.add(_new_request(user.id, order.id, "ocr_duplicate_2"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        saved = session.scalars(sa.select(OrderCancelRequest)).all()

    assert [row.request_code for row in saved] == ["ocr_duplicate_1"]


def test_rejected_request_allows_a_new_request_for_the_same_order(db_engine: Engine) -> None:
    processed_at = datetime(2026, 7, 13, 15, 10, tzinfo=UTC)
    with Session(db_engine) as session:
        user, order = _seed_order(session, "retry")
        first = _new_request(user.id, order.id, "ocr_retry_1")
        session.add(first)
        session.commit()

        first.status = "REJECTED"
        first.decision_reason = "배송 준비를 계속 진행합니다."
        first.processed_at = processed_at
        first.updated_at = processed_at
        session.commit()

        session.add(_new_request(user.id, order.id, "ocr_retry_2"))
        session.commit()
        saved = session.scalars(
            sa.select(OrderCancelRequest).order_by(OrderCancelRequest.id.asc())
        ).all()

    assert [row.status for row in saved] == ["REJECTED", "REQUESTED"]


def test_rejected_request_requires_decision_reason(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user, order = _seed_order(session, "reason")
        session.add(
            OrderCancelRequest(
                request_code="ocr_reason",
                order_id=order.id,
                user_id=user.id,
                status="REJECTED",
                processed_at=datetime(2026, 7, 13, 15, 20, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_requested_request_cannot_have_processed_at(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user, order = _seed_order(session, "processed")
        session.add(
            OrderCancelRequest(
                request_code="ocr_processed",
                order_id=order.id,
                user_id=user.id,
                status="REQUESTED",
                processed_at=datetime(2026, 7, 13, 15, 30, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_requested_unique_index_compiles_for_postgresql() -> None:
    index = next(
        index
        for index in OrderCancelRequest.__table__.indexes
        if index.name == "uq_order_cancel_requests_order_requested"
    )
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "CREATE UNIQUE INDEX uq_order_cancel_requests_order_requested" in sql
    assert "WHERE status = 'REQUESTED'" in sql


def test_cancel_request_migration_upgrades_and_downgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    sa.Table("orders", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    metadata.create_all(engine)

    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()

            inspector = sa.inspect(connection)
            assert "order_cancel_requests" in inspector.get_table_names()
            assert {column["name"] for column in inspector.get_columns("order_cancel_requests")} == {
                "id",
                "request_code",
                "order_id",
                "user_id",
                "status",
                "reason_code",
                "reason_detail",
                "decision_reason",
                "requested_at",
                "processed_at",
                "created_at",
                "updated_at",
            }
            indexes = {index["name"]: index for index in inspector.get_indexes("order_cancel_requests")}
            assert indexes["uq_order_cancel_requests_order_requested"]["unique"] == 1
            assert "ix_order_cancel_requests_order_status" in indexes
            assert "ix_order_cancel_requests_user_created_at" in indexes

            migration.downgrade()
            assert "order_cancel_requests" not in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()


def _seed_order(session: Session, suffix: str) -> tuple[User, Order]:
    user = User(email=f"cancel-request-{suffix}@example.com", display_name=f"cancel-request-{suffix}")
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_cancel_request_{suffix}",
        user_id=user.id,
        idempotency_key=f"cancel-request-{suffix}",
        status="CANCEL_REQUESTED",
        subtotal_amount=1000,
        shipping_fee=0,
        discount_amount=0,
        total_amount=1000,
        currency="KRW",
        item_count=1,
        total_quantity=1,
    )
    session.add(order)
    session.flush()
    return user, order


def _new_request(
    user_id: int,
    order_id: int,
    request_code: str,
    *,
    requested_at: datetime | None = None,
) -> OrderCancelRequest:
    created_at = requested_at or datetime(2026, 7, 13, 15, 0, tzinfo=UTC)
    return OrderCancelRequest(
        request_code=request_code,
        order_id=order_id,
        user_id=user_id,
        status="REQUESTED",
        reason_code="CHANGE_OF_MIND",
        reason_detail="고객이 취소를 요청했습니다.",
        requested_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def _load_migration_module() -> ModuleType:
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260713_0041_add_order_cancel_requests.py"
    spec = importlib.util.spec_from_file_location("migration_20260713_0041", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the order cancel request migration.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
