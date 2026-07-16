from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.taxonomy import Ingredient, IngredientMappingReview, IngredientMappingReviewEvent


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


def test_mapping_review_persists_approved_decision_and_initial_event(db_engine: Engine) -> None:
    reviewed_at = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user, source, target = _seed_references(session, "approved")
        review = IngredientMappingReview(
            source_ingredient_id=source.id,
            source_ingredient_name="Sodium Hyaluronate",
            normalized_source_name="sodiumhyaluronate",
            target_ingredient_id=target.id,
            status="APPROVED",
            reviewed_by_user_id=user.id,
            reviewed_at=reviewed_at,
        )
        session.add(review)
        session.flush()
        session.add(
            IngredientMappingReviewEvent(
                review_id=review.id,
                to_status="APPROVED",
                to_target_ingredient_id=target.id,
                actor_id=user.id,
            )
        )
        session.commit()

        saved_event = session.scalar(sa.select(IngredientMappingReviewEvent))
        assert review.status == "APPROVED"
        assert review.target_ingredient_id == target.id
        assert saved_event is not None
        assert saved_event.metadata_json == {}


@pytest.mark.parametrize(
    ("status", "include_target", "reason"),
    [
        (None, False, None),
        ("PENDING", False, None),
        ("APPROVED", False, None),
        ("HELD", True, "재검토 필요"),
        ("REJECTED", False, None),
        ("HELD", False, "   "),
    ],
)
def test_mapping_review_rejects_invalid_current_state(
    db_engine: Engine,
    status: str | None,
    include_target: bool,
    reason: str | None,
) -> None:
    with Session(db_engine) as session:
        user, source, target = _seed_references(session, status.lower() if status else "null")
        session.add(
            IngredientMappingReview(
                source_ingredient_id=source.id,
                normalized_source_name="sodiumhyaluronate",
                target_ingredient_id=target.id if include_target else None,
                status=status,
                decision_reason=reason,
                reviewed_by_user_id=user.id,
                reviewed_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize(
    ("from_status", "include_from_target", "to_status", "include_to_target", "reason"),
    [
        ("APPROVED", False, "HELD", False, "재검토 필요"),
        ("HELD", True, "REJECTED", False, "반려 사유"),
        (None, False, "APPROVED", False, None),
        (None, False, "HELD", True, "보류 사유"),
        (None, False, "HELD", False, None),
        (None, False, "PENDING", False, None),
    ],
)
def test_mapping_review_event_rejects_inconsistent_history(
    db_engine: Engine,
    from_status: str | None,
    include_from_target: bool,
    to_status: str,
    include_to_target: bool,
    reason: str | None,
) -> None:
    with Session(db_engine) as session:
        user, source, target = _seed_references(session, f"event-{to_status.lower()}")
        review = IngredientMappingReview(
            source_ingredient_id=source.id,
            normalized_source_name="sodiumhyaluronate",
            status="HELD",
            decision_reason="초기 보류",
            reviewed_by_user_id=user.id,
            reviewed_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        )
        session.add(review)
        session.flush()
        session.add(
            IngredientMappingReviewEvent(
                review_id=review.id,
                from_status=from_status,
                to_status=to_status,
                from_target_ingredient_id=target.id if include_from_target else None,
                to_target_ingredient_id=target.id if include_to_target else None,
                actor_id=user.id,
                reason=reason,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_mapping_review_unique_key_prevents_duplicate_admin_decision(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user, source, _target = _seed_references(session, "duplicate")
        reviewed_at = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
        session.add_all(
            [
                IngredientMappingReview(
                    source_ingredient_id=source.id,
                    normalized_source_name="sodiumhyaluronate",
                    status="HELD",
                    decision_reason="근거 확인 필요",
                    reviewed_by_user_id=user.id,
                    reviewed_at=reviewed_at,
                ),
                IngredientMappingReview(
                    source_ingredient_id=source.id,
                    normalized_source_name="sodiumhyaluronate",
                    status="REJECTED",
                    decision_reason="동일 원문 중복",
                    reviewed_by_user_id=user.id,
                    reviewed_at=reviewed_at,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_mapping_review_migration_upgrades_and_downgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("ingredients", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.BigInteger(), primary_key=True))
    metadata.create_all(engine)

    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()

            inspector = sa.inspect(connection)
            assert {"ingredient_mapping_reviews", "ingredient_mapping_review_events"}.issubset(
                inspector.get_table_names()
            )
            assert {column["name"] for column in inspector.get_columns("ingredient_mapping_reviews")} == {
                "id",
                "source_ingredient_id",
                "source_ingredient_name",
                "normalized_source_name",
                "target_ingredient_id",
                "status",
                "decision_reason",
                "reviewed_by_user_id",
                "reviewed_at",
                "created_at",
                "updated_at",
            }
            assert {column["name"] for column in inspector.get_columns("ingredient_mapping_review_events")} == {
                "id",
                "review_id",
                "from_status",
                "to_status",
                "from_target_ingredient_id",
                "to_target_ingredient_id",
                "actor_id",
                "reason",
                "metadata_json",
                "created_at",
            }
            review_indexes = {index["name"] for index in inspector.get_indexes("ingredient_mapping_reviews")}
            event_indexes = {index["name"] for index in inspector.get_indexes("ingredient_mapping_review_events")}
            assert review_indexes == {"ix_ingredient_mapping_reviews_status"}
            assert event_indexes == {"ix_ingredient_mapping_review_events_review_created_at"}

            migration.downgrade()
            table_names = set(sa.inspect(connection).get_table_names())
            assert "ingredient_mapping_reviews" not in table_names
            assert "ingredient_mapping_review_events" not in table_names
    finally:
        engine.dispose()


def _seed_references(session: Session, suffix: str) -> tuple[User, Ingredient, Ingredient]:
    user = User(email=f"ingredient-review-{suffix}@example.com", display_name=f"ingredient-review-{suffix}")
    source = Ingredient(
        ingredient_code=f"ing_pending_{suffix}",
        name_ko="소듐하이알루로네이트 원문",
    )
    target = Ingredient(
        ingredient_code=f"ing_canonical_{suffix}",
        name_ko="소듐하이알루로네이트",
    )
    session.add_all([user, source, target])
    session.flush()
    return user, source, target


def _load_migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260716_0043_add_ingredient_mapping_reviews.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20260716_0043", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the ingredient mapping review migration.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
