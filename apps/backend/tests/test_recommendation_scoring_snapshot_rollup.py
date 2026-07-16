import json
import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.cli import rollup_product_recommendation_scoring_snapshots as snapshot_cli
from app.db.base import Base
from app.db.models.catalog import Product, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationFeature,
    ProductRecommendationScoringSnapshot,
)
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.models.taxonomy import RiskFlag
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_feature_versions import (
    RECOMMENDATION_SCORING_SNAPSHOT_VERSION,
)
from app.services.recommendation_scoring_snapshot_rollup import (
    rollup_product_recommendation_scoring_snapshots,
)
from app.services.review_rollup import REVIEW_SCORE_VERSION
from tests.test_data_loader import EXAMPLES_DIR


def test_snapshot_full_rollup_is_idempotent() -> None:
    session = _seed_example_session()
    computed_at = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)

    first = rollup_product_recommendation_scoring_snapshots(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    first_rows = _snapshot_rows(session)
    second = rollup_product_recommendation_scoring_snapshots(
        session,
        batch_size=2,
        computed_at=computed_at,
    )
    session.commit()

    assert first.product_count == second.product_count == 2
    assert first.snapshot_count == second.snapshot_count == 2
    assert first.batch_count == 2
    assert second.batch_count == 1
    assert _snapshot_rows(session) == first_rows


def test_snapshot_targeted_rollup_only_updates_requested_product() -> None:
    session = _seed_example_session()
    products = session.execute(select(Product).order_by(Product.id)).scalars().all()

    result = rollup_product_recommendation_scoring_snapshots(
        session,
        product_ids=(products[0].id,),
    )
    session.commit()

    rows = session.execute(select(ProductRecommendationScoringSnapshot)).scalars().all()
    assert result.requested_product_count == 1
    assert result.product_count == 1
    assert result.snapshot_count == 1
    assert [row.product_id for row in rows] == [products[0].id]


def test_snapshot_rollup_keeps_products_without_optional_sources() -> None:
    session = _seed_example_session()
    product_id = session.execute(select(Product.id).order_by(Product.id)).scalars().first()
    assert product_id is not None
    session.execute(
        delete(ProductEffectRecommendationFeature).where(
            ProductEffectRecommendationFeature.product_id == product_id
        )
    )
    session.execute(
        delete(ProductRecommendationFeature).where(
            ProductRecommendationFeature.product_id == product_id
        )
    )
    session.execute(
        delete(ProductSkinProfile).where(ProductSkinProfile.product_id == product_id)
    )
    session.execute(
        delete(ProductPopularityMetric).where(
            ProductPopularityMetric.product_id == product_id
        )
    )
    session.execute(
        delete(ProductReviewSegmentMetric).where(
            ProductReviewSegmentMetric.product_id == product_id
        )
    )
    session.execute(
        delete(ProductReviewMetric).where(ProductReviewMetric.product_id == product_id)
    )
    session.execute(
        delete(ProductIngredient).where(ProductIngredient.product_id == product_id)
    )

    result = rollup_product_recommendation_scoring_snapshots(
        session,
        product_ids=(product_id,),
    )
    session.commit()
    snapshot = session.get(ProductRecommendationScoringSnapshot, product_id)

    assert result.snapshot_count == 1
    assert snapshot is not None
    assert snapshot.scoring_payload["product_feature"] is None
    assert snapshot.scoring_payload["effect_features"] == {}
    assert snapshot.scoring_payload["skin_profile"] is None
    assert snapshot.scoring_payload["risk_flags"] == []
    assert snapshot.scoring_payload["market_signal"] is None
    assert snapshot.scoring_payload["review_metric"] is None
    assert snapshot.scoring_payload["review_segments"] == []


def test_snapshot_rollup_serializes_authoritative_review_and_market_inputs() -> None:
    session = _seed_example_session()
    product = session.execute(select(Product).order_by(Product.id)).scalars().first()
    assert product is not None
    product_ingredient = session.execute(
        select(ProductIngredient)
        .where(ProductIngredient.product_id == product.id)
        .order_by(ProductIngredient.id)
    ).scalars().first()
    assert product_ingredient is not None
    session.execute(
        delete(ProductPopularityMetric).where(
            ProductPopularityMetric.product_id == product.id
        )
    )
    session.execute(
        delete(ProductReviewSegmentMetric).where(
            ProductReviewSegmentMetric.product_id == product.id
        )
    )
    session.execute(
        delete(ProductReviewMetric).where(ProductReviewMetric.product_id == product.id)
    )
    session.add_all(
        [
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=Decimal("0.8123"),
                score_version="popular_v1",
            ),
            ProductReviewMetric(
                product_id=product.id,
                review_count=123,
                rating_count=123,
                confidence=Decimal("0.75"),
                effective_sample_size=Decimal("81.5"),
                review_quality_score=Decimal("0.84"),
                score_version=REVIEW_SCORE_VERSION,
            ),
            ProductReviewSegmentMetric(
                product_id=product.id,
                dimension="SKIN_TYPE",
                value_code="dry",
                review_count=25,
                rating_count=25,
                effective_sample_size=Decimal("17.25"),
                total_affinity_score=Decimal("0.73"),
                score_version=REVIEW_SCORE_VERSION,
            ),
            RiskFlag(
                ingredient_id=product_ingredient.ingredient_id,
                risk_type="sensitive_caution",
                display_text="sensitive caution",
                severity="medium",
                severity_score=Decimal("0.4"),
                applies_to="sensitive",
            ),
        ]
    )
    session.flush()

    rollup_product_recommendation_scoring_snapshots(
        session,
        product_ids=(product.id,),
    )
    session.commit()
    snapshot = session.get(ProductRecommendationScoringSnapshot, product.id)

    assert snapshot is not None
    assert snapshot.snapshot_version == RECOMMENDATION_SCORING_SNAPSHOT_VERSION
    assert snapshot.scoring_payload["market_signal"] == {
        "popularity_score": 0.8123
    }
    assert snapshot.scoring_payload["review_metric"] == {
        "review_quality_score": 0.84,
        "confidence": 0.75,
        "effective_sample_size": 81.5,
        "review_count": 123,
    }
    assert snapshot.scoring_payload["review_segments"] == [
        {
            "dimension": "SKIN_TYPE",
            "value_code": "dry",
            "total_affinity_score": 0.73,
            "effective_sample_size": 17.25,
            "review_count": 25,
        }
    ]
    assert snapshot.scoring_payload["risk_flags"][-1]["severity_score"] == 0.4
    assert snapshot.source_versions["review_metric"] == REVIEW_SCORE_VERSION
    assert snapshot.source_versions["market_signal"] == {
        "window_days": 7,
        "score_version": "popular_v1",
    }


def test_snapshot_cli_dry_run_rolls_back(tmp_path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "snapshot-dry-run.sqlite3"
    engine = make_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_database(session, EXAMPLES_DIR)
        rollup_product_recommendation_features(session)
        session.commit()

    monkeypatch.setattr(snapshot_cli, "SessionLocal", factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rollup_product_recommendation_scoring_snapshots",
            "--full",
            "--batch-size",
            "1",
            "--dry-run",
        ],
    )

    snapshot_cli.main()

    output = json.loads(capsys.readouterr().out)
    with factory() as session:
        count = session.query(ProductRecommendationScoringSnapshot).count()
    assert output["dry_run"] is True
    assert output["snapshot_count"] == 2
    assert count == 0


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    rollup_product_recommendation_features(session)
    session.commit()
    return session


def _snapshot_rows(session: Session) -> list[tuple]:
    rows = session.execute(
        select(ProductRecommendationScoringSnapshot).order_by(
            ProductRecommendationScoringSnapshot.product_id
        )
    ).scalars()
    return [
        (
            row.product_id,
            row.scoring_payload,
            row.snapshot_version,
            row.source_versions,
            row.computed_at,
        )
        for row in rows
    ]
