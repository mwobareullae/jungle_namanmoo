import json
import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.cli import rollup_product_recommendation_scoring_read_models as read_model_cli
from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import ProductRecommendationScoringReadModel
from app.db.models.review import ProductReviewMetric
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_feature_versions import (
    PRODUCT_RECOMMENDATION_SCORING_READ_MODEL_VERSION,
)
from app.services.recommendation_scoring_read_model_rollup import (
    rollup_product_recommendation_scoring_read_models,
)
from app.services.review_rollup import REVIEW_SCORE_VERSION
from tests.test_data_loader import EXAMPLES_DIR


def test_read_model_rollup_is_idempotent_and_compact() -> None:
    session = _seed_example_session(include_optional_sources=True)
    computed_at = datetime(2026, 7, 16, 12, 30, tzinfo=UTC)

    first = rollup_product_recommendation_scoring_read_models(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    first_rows = _read_model_values(session)
    second = rollup_product_recommendation_scoring_read_models(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    session.expire_all()

    assert first.product_count == 2
    assert first.read_model_count == 2
    assert first.batch_count == 2
    assert second.read_model_count == 2
    assert _read_model_values(session) == first_rows
    assert session.query(ProductRecommendationScoringReadModel).count() == 2
    assert all(
        row.read_model_version
        == PRODUCT_RECOMMENDATION_SCORING_READ_MODEL_VERSION
        for row in session.query(ProductRecommendationScoringReadModel)
    )
    assert all(isinstance(row[1], list) for row in first_rows)
    assert all(isinstance(row[2], list) for row in first_rows)


def test_read_model_rollup_preserves_optional_source_versions() -> None:
    session = _seed_example_session(include_optional_sources=True)
    product_id = session.execute(select(Product.id).order_by(Product.id)).scalars().first()
    assert product_id is not None

    result = rollup_product_recommendation_scoring_read_models(
        session,
        product_ids=(int(product_id),),
    )
    session.commit()
    row = session.get(ProductRecommendationScoringReadModel, product_id)

    assert result.requested_product_count == 1
    assert result.product_count == 1
    assert row is not None
    assert row.product_feature_source_current is True
    assert row.popularity_window_days == 7
    assert row.popularity_score_version == "popular_v1"
    assert row.review_score_version == REVIEW_SCORE_VERSION
    assert row.review_quality_score == Decimal("0.700000")
    assert row.review_count == 10


def test_read_model_rollup_uses_fixed_select_count_per_batch() -> None:
    session = _seed_example_session()
    select_count = 0

    def count_selects(_connection, _cursor, statement, *_args) -> None:
        nonlocal select_count
        if statement.lstrip().lower().startswith("select"):
            select_count += 1

    assert session.bind is not None
    event.listen(session.bind, "before_cursor_execute", count_selects)
    try:
        rollup_product_recommendation_scoring_read_models(session, batch_size=500)
    finally:
        event.remove(session.bind, "before_cursor_execute", count_selects)

    assert select_count == 2


def test_read_model_cli_dry_run_rolls_back(tmp_path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "read-model-dry-run.sqlite3"
    engine = make_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_database(session, EXAMPLES_DIR)
        rollup_product_recommendation_features(session)
        session.commit()

    monkeypatch.setattr(read_model_cli, "SessionLocal", factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rollup_product_recommendation_scoring_read_models",
            "--full",
            "--batch-size",
            "1",
            "--dry-run",
        ],
    )

    read_model_cli.main()

    output = json.loads(capsys.readouterr().out)
    with factory() as session:
        count = session.query(ProductRecommendationScoringReadModel).count()
    assert output["dry_run"] is True
    assert output["read_model_count"] == 2
    assert count == 0


def _seed_example_session(*, include_optional_sources: bool = False) -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    rollup_product_recommendation_features(session)
    if include_optional_sources:
        products = session.execute(select(Product).order_by(Product.id)).scalars().all()
        for index, product in enumerate(products, start=1):
            session.add_all(
                [
                    ProductPopularityMetric(
                        product_id=product.id,
                        window_days=7,
                        popularity_score=Decimal(str(0.6 + index * 0.1)),
                    ),
                    ProductReviewMetric(
                        product_id=product.id,
                        review_count=10 * index,
                        rating_count=10 * index,
                        confidence=Decimal("0.7"),
                        effective_sample_size=Decimal(str(8 * index)),
                        review_quality_score=Decimal(str(0.65 + index * 0.05)),
                        score_version=REVIEW_SCORE_VERSION,
                    ),
                ]
            )
    session.commit()
    return session


def _read_model_values(
    session: Session,
) -> list[tuple[object, ...]]:
    rows = session.execute(
        select(ProductRecommendationScoringReadModel).order_by(
            ProductRecommendationScoringReadModel.product_id
        )
    ).scalars()
    return [
        (
            row.product_id,
            row.top_ingredient_codes,
            row.functional_claims,
            row.skin_tags,
            row.product_feature_version,
            row.product_feature_source_current,
            row.popularity_score,
            row.review_quality_score,
            row.read_model_version,
            row.source_updated_at,
            row.computed_at,
        )
        for row in rows
    ]
