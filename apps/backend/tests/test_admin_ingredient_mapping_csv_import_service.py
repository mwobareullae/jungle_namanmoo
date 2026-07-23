"""운영 성분 CSV dry-run 및 실제 연결 이동 서비스 테스트."""

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import ProductIngredient
from app.db.models.taxonomy import Ingredient
from app.schemas.admin.ingredient_mapping_csv_import import IngredientMappingCsvRowInput
from app.schemas.common import ApiError
from app.services.admin import ingredient_mapping_csv_import_service as csv_service


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _ingredient(code: str, name: str) -> Ingredient:
    return Ingredient(
        ingredient_code=code,
        name_ko=name,
        normalized_name=csv_service.normalize_source_name(name),
        is_active=True,
    )


def _product_ingredient(product_id: int, ingredient_id: int, raw_name: str) -> ProductIngredient:
    return ProductIngredient(
        product_id=product_id,
        ingredient_id=ingredient_id,
        ingredient_name=raw_name,
    )


def _row(expected_connection_count: int = 2, **overrides: object) -> IngredientMappingCsvRowInput:
    values: dict[str, object] = {
        "row_number": 2,
        "action": "MAP_EXISTING",
        "pending_code": "ing_pending_panthenol",
        "normalized_source_name": "판테놀",
        "expected_connection_count": expected_connection_count,
        "target_ingredient_code": "ing_panthenol",
        "target_name_ko": None,
        "target_name_en": None,
        "decision_reason": "운영 CSV 일괄 매핑",
        "source_reference": None,
    }
    values.update(overrides)
    return IngredientMappingCsvRowInput(**values)


def _seed_group(session: Session) -> tuple[Ingredient, Ingredient]:
    source = _ingredient("ing_pending_panthenol", "판테놀 원문")
    target = _ingredient("ing_panthenol", "판테놀")
    session.add_all([source, target])
    session.flush()
    session.add_all(
        [
            _product_ingredient(101, source.id, "판테놀"),
            _product_ingredient(102, source.id, " 판 테 놀 "),
        ]
    )
    session.flush()
    return source, target


def test_preview_accepts_current_exact_group(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        _seed_group(session)
        preview = csv_service.preview_csv_mapping_batch(session, [_row()])

    assert preview.summary.valid == 1
    assert preview.summary.invalid == 0
    assert preview.summary.connection_count == 2
    assert preview.rows[0].current_connection_count == 2


def test_preview_rejects_stale_connection_count(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        _seed_group(session)
        preview = csv_service.preview_csv_mapping_batch(session, [_row(expected_connection_count=1)])

    assert preview.summary.invalid == 1
    assert preview.rows[0].error_code == "CONNECTION_COUNT_CHANGED"


def test_create_and_map_requires_source_reference(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        source = _ingredient("ing_pending_panthenol", "판테놀 원문")
        session.add(source)
        session.flush()
        session.add(_product_ingredient(101, source.id, "판테놀"))
        session.flush()
        preview = csv_service.preview_csv_mapping_batch(
            session,
            [
                _row(
                    expected_connection_count=1,
                    action="CREATE_AND_MAP",
                    target_ingredient_code="ing_panthenol_compound",
                    target_name_ko="판테놀 복합 원료",
                    source_reference=None,
                )
            ],
        )

    assert preview.summary.invalid == 1
    assert preview.rows[0].error_code == "SOURCE_REFERENCE_REQUIRED"


def test_apply_moves_connections_to_existing_canonical(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_service, "approve_ingredient_mapping", lambda *_args, **_kwargs: None)
    with Session(db_engine) as session:
        source, target = _seed_group(session)
        row = _row()
        digest = csv_service.preview_csv_mapping_batch(session, [row]).preview_digest
        outcome = csv_service.apply_csv_mapping_batch(
            session,
            rows=[row],
            expected_preview_digest=digest,
            confirmed_count=1,
            actor_user_id=1,
        )
        ingredient_ids = list(
            session.execute(
                select(ProductIngredient.ingredient_id).order_by(ProductIngredient.product_id)
            ).scalars()
        )

    assert source.id != target.id
    assert ingredient_ids == [target.id, target.id]
    assert outcome.response.applied == 1
    assert outcome.response.moved_connections == 2
    assert outcome.response.search_reindex_required is True


def test_apply_collapses_existing_product_target_duplicate(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_service, "approve_ingredient_mapping", lambda *_args, **_kwargs: None)
    with Session(db_engine) as session:
        source = _ingredient("ing_pending_panthenol", "판테놀 원문")
        target = _ingredient("ing_panthenol", "판테놀")
        session.add_all([source, target])
        session.flush()
        session.add_all(
            [
                _product_ingredient(101, source.id, "판테놀"),
                _product_ingredient(101, target.id, "판테놀"),
            ]
        )
        session.flush()
        row = _row(expected_connection_count=1)
        digest = csv_service.preview_csv_mapping_batch(session, [row]).preview_digest
        outcome = csv_service.apply_csv_mapping_batch(
            session,
            rows=[row],
            expected_preview_digest=digest,
            confirmed_count=1,
            actor_user_id=1,
        )
        product_rows = list(session.execute(select(ProductIngredient)).scalars())

    assert len(product_rows) == 1
    assert product_rows[0].ingredient_id == target.id
    assert outcome.response.collapsed_duplicates == 1


def test_apply_rejects_changed_preview_digest(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        _seed_group(session)
        with pytest.raises(ApiError) as exc:
            csv_service.apply_csv_mapping_batch(
                session,
                rows=[_row()],
                expected_preview_digest="0" * 64,
                confirmed_count=1,
                actor_user_id=1,
            )

    assert exc.value.status_code == 409
    assert exc.value.code == "CSV_MAPPING_PREVIEW_STALE"
