import json
import sys
from datetime import UTC, datetime

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.cli import rollup_product_recommendation_coarse_features as coarse_cli
from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.recommendation import ProductRecommendationCoarseFeature
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.recommendation_coarse_feature_rollup import (
    EFFECT_SCORE_COLUMNS,
    rollup_product_recommendation_coarse_features,
)
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_feature_versions import (
    PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
)
from tests.test_data_loader import EXAMPLES_DIR


def test_coarse_feature_rollup_is_idempotent_and_numeric_only() -> None:
    session = _seed_example_session()
    computed_at = datetime(2026, 7, 17, 3, 0, tzinfo=UTC)

    first = rollup_product_recommendation_coarse_features(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    first_rows = _coarse_values(session)
    second = rollup_product_recommendation_coarse_features(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    session.expire_all()

    assert first.product_count == 2
    assert first.coarse_feature_count == 2
    assert first.source_current_count == 2
    assert first.batch_count == 2
    assert second.coarse_feature_count == 2
    assert _coarse_values(session) == first_rows
    assert session.query(ProductRecommendationCoarseFeature).count() == 2
    assert any(any(score > 0 for score in row[1]) for row in first_rows)
    assert all(
        row.feature_version == PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION
        for row in session.query(ProductRecommendationCoarseFeature)
    )
    assert {
        "functional_status",
        "functional_claims",
        "review_quality_score",
        "popularity_score",
        "risk_flags",
        "top_ingredient_codes",
        "skin_profile_reason",
    }.isdisjoint(ProductRecommendationCoarseFeature.__table__.columns.keys())


def test_coarse_feature_rollup_uses_fixed_select_count_per_batch() -> None:
    session = _seed_example_session()
    select_count = 0

    def count_selects(_connection, _cursor, statement, *_args) -> None:
        nonlocal select_count
        if statement.lstrip().lower().startswith("select"):
            select_count += 1

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", count_selects)
    try:
        rollup_product_recommendation_coarse_features(session, batch_size=500)
    finally:
        event.remove(session.bind, "before_cursor_execute", count_selects)

    assert select_count == 4


def test_coarse_feature_rollup_limits_rows_to_requested_product_ids() -> None:
    session = _seed_example_session()
    product_ids = list(
        session.execute(select(Product.id).order_by(Product.id.asc())).scalars()
    )

    result = rollup_product_recommendation_coarse_features(
        session,
        product_ids=(product_ids[-1],),
        batch_size=100,
    )
    session.commit()

    stored_ids = list(
        session.execute(
            select(ProductRecommendationCoarseFeature.product_id)
        ).scalars()
    )
    assert result.requested_product_count == 1
    assert result.product_count == 1
    assert result.batch_count == 1
    assert stored_ids == [product_ids[-1]]


def test_coarse_feature_cli_dry_run_rolls_back(tmp_path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "coarse-feature-dry-run.sqlite3"
    engine = make_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_database(session, EXAMPLES_DIR)
        rollup_product_recommendation_features(session)
        session.commit()

    monkeypatch.setattr(coarse_cli, "SessionLocal", factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rollup_product_recommendation_coarse_features",
            "--full",
            "--batch-size",
            "1",
            "--dry-run",
        ],
    )

    coarse_cli.main()

    output = json.loads(capsys.readouterr().out)
    with factory() as session:
        count = session.query(ProductRecommendationCoarseFeature).count()
    assert output["dry_run"] is True
    assert output["coarse_feature_count"] == 2
    assert count == 0


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    rollup_product_recommendation_features(session)
    session.commit()
    return session


def _coarse_values(session: Session) -> list[tuple[object, ...]]:
    rows = session.execute(
        select(ProductRecommendationCoarseFeature).order_by(
            ProductRecommendationCoarseFeature.product_id
        )
    ).scalars()
    return [
        (
            row.product_id,
            tuple(int(getattr(row, column)) for column in EFFECT_SCORE_COLUMNS),
            row.dry_fit,
            row.oily_fit,
            row.combination_fit,
            row.normal_fit,
            row.dehydrated_oily_fit,
            row.sensitive_fit,
            row.skin_profile_confidence_code,
            row.home_max_effect_score,
            row.home_max_evidence_score,
            row.home_lowest_price,
            row.home_has_image,
            row.home_source_current,
            row.source_current,
            row.feature_version,
            row.source_updated_at,
            row.computed_at,
        )
        for row in rows
    ]
