import csv
import logging
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.review import ProductReview, ProductReviewProfileLabel
from app.services.db_seed import seed_database
from app.services.review_importer import REQUIRED_REVIEW_HEADERS, ReviewImportError, import_product_reviews
from app.services.review_profile_mapping import map_review_profile_labels
from tests.test_data_loader import EXAMPLES_DIR


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session, EXAMPLES_DIR)
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


def _product_code(session: Session) -> str:
    return str(session.execute(select(Product.product_code).order_by(Product.id)).scalars().first())


def _review_row(product_code: str, **overrides: str) -> dict[str, str]:
    row = {
        "review_id": "review-import-001",
        "product_id": product_code,
        "source": "OliveYoung",
        "source_review_id": "source-review-001",
        "rating": "5",
        "review_text": "한 달 동안 사용하니 만족스러워요.",
        "review_date": "2026-06-30",
        "option_text": "기본",
        "helpful_count": "3",
        "review_type": "one_month_review",
        "is_month_use_review": "true",
        "is_repurchase": "true",
        "has_photo": "true",
        "review_badge_labels": "한달사용;재구매",
        "reviewer_skin_type_label_ko": "약건성",
        "reviewer_skin_tone_label_ko": "여름쿨톤",
        "reviewer_skin_trouble_labels_ko": "민감성;붉은기",
        "reviewer_profile_labels_ko": "약건성;여름쿨톤;민감성;붉은기",
        "collected_at": "2026-07-01T03:00:00Z",
    }
    row.update(overrides)
    return row


def _write_reviews(path: Path, rows: list[dict[str, str]]) -> Path:
    headers = sorted(REQUIRED_REVIEW_HEADERS)
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_import_is_idempotent_and_updates_changed_content(
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(db_engine) as session:
        product_code = _product_code(session)
        source_file = _write_reviews(tmp_path / "reviews.csv", [_review_row(product_code)])

        first = import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()
        assert (first.inserted, first.updated, first.unchanged) == (1, 0, 0)
        assert first.profile_labels == 4

        review = session.execute(select(ProductReview)).scalar_one()
        labels = session.execute(
            select(
                ProductReviewProfileLabel.dimension,
                ProductReviewProfileLabel.value_code,
                ProductReviewProfileLabel.mapping_confidence,
            ).order_by(
                ProductReviewProfileLabel.dimension,
                ProductReviewProfileLabel.value_code,
            )
        ).all()
        assert review.source == "oliveyoung"
        assert review.review_type == "MONTH_USE"
        assert review.source_has_photo is True
        assert [(dimension, value) for dimension, value, _ in labels] == [
            ("SKIN_CONCERN", "concern_redness_irritation"),
            ("SKIN_CONCERN", "concern_sensitive"),
            ("SKIN_TONE", "summer_cool"),
            ("SKIN_TYPE", "dry"),
        ]
        dry_confidence = next(confidence for dimension, value, confidence in labels if value == "dry")
        assert str(dry_confidence) == "0.7000"

        second = import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()
        assert (second.inserted, second.updated, second.unchanged) == (0, 0, 1)
        assert second.profile_labels == 0

        _write_reviews(
            source_file,
            [_review_row(product_code, rating="4", review_text="내용이 바뀐 후기")],
        )
        third = import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()
        assert (third.inserted, third.updated, third.unchanged) == (0, 1, 0)
        session.refresh(review)
        assert review.rating == 4
        assert review.review_text == "내용이 바뀐 후기"


def test_import_preserves_hidden_status_on_source_refresh(
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(db_engine) as session:
        product_code = _product_code(session)
        source_file = _write_reviews(tmp_path / "reviews.csv", [_review_row(product_code)])
        import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()

        review = session.execute(select(ProductReview)).scalar_one()
        review.status = "HIDDEN"
        session.commit()
        _write_reviews(source_file, [_review_row(product_code, rating="4")])

        result = import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()
        session.refresh(review)
        assert result.updated == 1
        assert review.status == "HIDDEN"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"rating": "6"}, "rating must be between 1 and 5"),
        ({"has_photo": "yes"}, "has_photo must be true or false"),
        ({"review_type": "unknown"}, "unsupported review_type"),
        ({"is_month_use_review": "false"}, "review_type and is_month_use_review conflict"),
    ],
)
def test_import_rejects_invalid_source_rows(
    db_engine: Engine,
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    with Session(db_engine) as session:
        source_file = _write_reviews(
            tmp_path / "invalid.csv",
            [_review_row(_product_code(session), **overrides)],
        )
        with pytest.raises(ReviewImportError, match=message):
            import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.rollback()
        assert session.scalar(select(ProductReview.id)) is None


def test_import_rejects_unknown_product_without_partial_commit(
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(db_engine) as session:
        product_code = _product_code(session)
        source_file = _write_reviews(
            tmp_path / "unknown-product.csv",
            [
                _review_row(product_code),
                _review_row(
                    "missing-product",
                    review_id="review-import-002",
                    source_review_id="source-review-002",
                ),
            ],
        )
        with pytest.raises(ReviewImportError, match="unknown product_id"):
            import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file], batch_size=1)
        session.rollback()
        assert session.scalar(select(ProductReview.id)) is None


def test_import_keeps_review_and_warns_for_unknown_profile_label(
    db_engine: Engine,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with Session(db_engine) as session:
        source_file = _write_reviews(
            tmp_path / "unknown-profile.csv",
            [
                _review_row(
                    _product_code(session),
                    reviewer_skin_type_label_ko="알수없는피부",
                    reviewer_skin_tone_label_ko="",
                    reviewer_skin_trouble_labels_ko="",
                    reviewer_profile_labels_ko="알수없는피부",
                )
            ],
        )
        with caplog.at_level(logging.WARNING, logger="app.services.review_importer"):
            result = import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()

        assert result.inserted == 1
        assert result.profile_labels == 0
        assert result.unknown_profile_labels == 1
        assert result.unknown_profile_label_values == ("알수없는피부",)
        assert session.scalar(select(ProductReview.id)) is not None
        assert session.scalar(select(ProductReviewProfileLabel.id)) is None
        assert "product_review_import_unknown_profile_labels" in caplog.text


def test_dry_run_classifies_rows_without_persisting_them(
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(db_engine) as session:
        source_file = _write_reviews(
            tmp_path / "dry-run.csv",
            [_review_row(_product_code(session))],
        )
        result = import_product_reviews(
            session,
            data_dir=tmp_path,
            file_paths=[source_file],
            dry_run=True,
        )
        session.rollback()

        assert result.dry_run is True
        assert result.inserted == 1
        assert session.scalar(select(ProductReview.id)) is None


def test_import_removes_postgres_incompatible_nul_from_review_text(
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(db_engine) as session:
        source_file = _write_reviews(
            tmp_path / "nul-review.csv",
            [_review_row(_product_code(session), review_text="앞부분\x00뒷부분")],
        )
        import_product_reviews(session, data_dir=tmp_path, file_paths=[source_file])
        session.commit()

        assert session.scalar(select(ProductReview.review_text)) == "앞부분뒷부분"


def test_profile_mapping_uses_combined_labels_only_as_dimension_fallback() -> None:
    result = map_review_profile_labels(
        skin_type_label="지성",
        skin_tone_label=None,
        skin_concern_labels="민감성",
        combined_profile_labels="건성;겨울쿨톤;트러블",
    )

    assert {(item.dimension, item.value_code) for item in result.labels} == {
        ("SKIN_TYPE", "oily"),
        ("SKIN_TONE", "winter_cool"),
        ("SKIN_CONCERN", "concern_sensitive"),
    }
    fallback = next(item for item in result.labels if item.dimension == "SKIN_TONE")
    assert str(fallback.mapping_confidence) == "0.8000"
