from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from time import perf_counter
from typing import Iterable

from sqlalchemy import case, delete, insert, or_, select, text, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.catalog import Product
from app.db.models.review import ProductReview, ProductReviewProfileLabel
from app.services.review_profile_mapping import (
    PROFILE_MAPPING_VERSION,
    ReviewProfileMapping,
    map_review_profile_labels,
)


logger = logging.getLogger(__name__)

DEFAULT_REVIEW_IMPORT_BATCH_SIZE = 5000
REVIEW_FILE_GLOB = "product_reviews_*.csv"
REVIEW_SUBDIRECTORY = "storefront_product_reviews"
REQUIRED_REVIEW_HEADERS = {
    "review_id",
    "product_id",
    "source",
    "source_review_id",
    "rating",
    "review_text",
    "review_date",
    "option_text",
    "helpful_count",
    "review_type",
    "is_month_use_review",
    "is_repurchase",
    "has_photo",
    "review_badge_labels",
    "reviewer_skin_type_label_ko",
    "reviewer_skin_tone_label_ko",
    "reviewer_skin_trouble_labels_ko",
    "reviewer_profile_labels_ko",
    "collected_at",
}


class ReviewImportError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewImportResult:
    files: int
    file_names: tuple[str, ...]
    rows_read: int
    products: int
    inserted: int
    updated: int
    unchanged: int
    profile_labels: int
    missing_profiles: int
    unknown_products: int
    unknown_profile_labels: int
    unknown_profile_label_values: tuple[str, ...]
    duplicate_rows: int
    errors: int
    dry_run: bool
    duration_seconds: float


@dataclass(frozen=True)
class _ParsedReview:
    file_name: str
    line_number: int
    review_code: str
    product_code: str
    product_id: int
    source: str
    source_review_id: str
    status: str
    review_type: str
    rating: int
    review_text: str
    reviewed_at: datetime
    option_text: str | None
    is_repurchase_review: bool
    verified_purchase: bool | None
    helpful_count: int
    source_has_photo: bool
    source_badge_labels_json: list[str] | None
    source_metadata_json: dict
    source_collected_at: datetime
    source_content_hash: str
    profile_mapping_version: str
    published_at: datetime
    profile_labels: tuple[ReviewProfileMapping, ...]
    unknown_profile_labels: tuple[str, ...]
    has_source_profile: bool

    @property
    def source_key(self) -> tuple[str, int, str]:
        return self.source, self.product_id, self.source_review_id

    def database_values(self) -> dict:
        return {
            "review_code": self.review_code,
            "product_id": self.product_id,
            "source": self.source,
            "source_review_id": self.source_review_id,
            "status": self.status,
            "review_type": self.review_type,
            "rating": self.rating,
            "review_text": self.review_text,
            "reviewed_at": self.reviewed_at,
            "option_text": self.option_text,
            "is_repurchase_review": self.is_repurchase_review,
            "verified_purchase": self.verified_purchase,
            "helpful_count": self.helpful_count,
            "source_has_photo": self.source_has_photo,
            "source_badge_labels_json": self.source_badge_labels_json,
            "source_metadata_json": self.source_metadata_json,
            "source_collected_at": self.source_collected_at,
            "source_content_hash": self.source_content_hash,
            "profile_mapping_version": self.profile_mapping_version,
            "published_at": self.published_at,
        }


@dataclass(frozen=True)
class _ExistingReview:
    review_code: str
    source: str
    product_id: int
    source_review_id: str
    source_content_hash: str | None
    profile_mapping_version: str | None


@dataclass(frozen=True)
class _BatchResult:
    inserted: int
    updated: int
    unchanged: int
    profile_labels: int


def import_product_reviews(
    session: Session,
    *,
    data_dir: str | Path,
    file_paths: Iterable[str | Path] | None = None,
    limit: int | None = None,
    batch_size: int = DEFAULT_REVIEW_IMPORT_BATCH_SIZE,
    dry_run: bool = False,
    profile_mapping_version: str = PROFILE_MAPPING_VERSION,
) -> ReviewImportResult:
    started_at = perf_counter()
    normalized_limit = _normalize_limit(limit)
    normalized_batch_size = _normalize_batch_size(batch_size)
    files = _resolve_review_files(Path(data_dir), file_paths)
    products_by_code = dict(session.execute(select(Product.product_code, Product.id)).all())
    dialect_name = session.get_bind().dialect.name
    if dialect_name not in {"postgresql", "sqlite"}:
        raise ReviewImportError(f"Unsupported review import database dialect: {dialect_name}")
    if dialect_name == "postgresql":
        _prepare_postgres_staging(session)

    counters = {
        "rows_read": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "profile_labels": 0,
        "missing_profiles": 0,
        "unknown_profile_labels": 0,
    }
    product_codes: set[str] = set()
    unknown_label_values: set[str] = set()
    sqlite_seen: set[tuple[str, int, str]] = set()
    batch: list[_ParsedReview] = []

    for file_path in files:
        with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            _validate_headers(reader.fieldnames, file_path.name)
            for line_number, row in enumerate(reader, start=2):
                if normalized_limit is not None and counters["rows_read"] >= normalized_limit:
                    break
                product_code = _required_text(row, "product_id", file_path.name, line_number)
                product_id = products_by_code.get(product_code)
                if product_id is None:
                    raise ReviewImportError(
                        f"{file_path.name}:{line_number} unknown product_id: {product_code}"
                    )
                parsed = _parse_review(
                    row,
                    file_name=file_path.name,
                    line_number=line_number,
                    product_id=int(product_id),
                    profile_mapping_version=profile_mapping_version,
                )
                batch.append(parsed)
                counters["rows_read"] += 1
                product_codes.add(product_code)
                if not parsed.profile_labels:
                    counters["missing_profiles"] += 1
                counters["unknown_profile_labels"] += len(parsed.unknown_profile_labels)
                unknown_label_values.update(parsed.unknown_profile_labels)
                if len(batch) >= normalized_batch_size:
                    _merge_batch_counters(
                        counters,
                        _process_batch(
                            session,
                            batch,
                            dialect_name=dialect_name,
                            dry_run=dry_run,
                            sqlite_seen=sqlite_seen,
                        ),
                    )
                    batch.clear()
            if normalized_limit is not None and counters["rows_read"] >= normalized_limit:
                break

    if batch:
        _merge_batch_counters(
            counters,
            _process_batch(
                session,
                batch,
                dialect_name=dialect_name,
                dry_run=dry_run,
                sqlite_seen=sqlite_seen,
            ),
        )

    if unknown_label_values:
        logger.warning(
            "product_review_import_unknown_profile_labels",
            extra={
                "unknown_profile_label_count": counters["unknown_profile_labels"],
                "unknown_profile_label_values": sorted(unknown_label_values),
            },
        )
    result = ReviewImportResult(
        files=len(files),
        file_names=tuple(path.name for path in files),
        rows_read=counters["rows_read"],
        products=len(product_codes),
        inserted=counters["inserted"],
        updated=counters["updated"],
        unchanged=counters["unchanged"],
        profile_labels=counters["profile_labels"],
        missing_profiles=counters["missing_profiles"],
        unknown_products=0,
        unknown_profile_labels=counters["unknown_profile_labels"],
        unknown_profile_label_values=tuple(sorted(unknown_label_values)),
        duplicate_rows=0,
        errors=0,
        dry_run=dry_run,
        duration_seconds=round(perf_counter() - started_at, 3),
    )
    logger.info(
        "product_review_import_completed",
        extra={
            "file_count": result.files,
            "rows_read": result.rows_read,
            "product_count": result.products,
            "inserted": result.inserted,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "profile_labels": result.profile_labels,
            "missing_profiles": result.missing_profiles,
            "unknown_profile_labels": result.unknown_profile_labels,
            "dry_run": result.dry_run,
            "duration_seconds": result.duration_seconds,
        },
    )
    return result


def _resolve_review_files(
    data_dir: Path,
    file_paths: Iterable[str | Path] | None,
) -> tuple[Path, ...]:
    if file_paths:
        resolved: list[Path] = []
        for value in file_paths:
            path = Path(value)
            if not path.is_absolute():
                direct_path = data_dir / path
                review_path = data_dir / REVIEW_SUBDIRECTORY / path
                path = direct_path if direct_path.exists() else review_path
            resolved.append(path)
    else:
        resolved = sorted((data_dir / REVIEW_SUBDIRECTORY).glob(REVIEW_FILE_GLOB))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in resolved:
        normalized = path.resolve()
        if normalized in seen:
            continue
        if not normalized.is_file():
            raise ReviewImportError(f"Review file was not found: {path}")
        seen.add(normalized)
        deduped.append(normalized)
    if not deduped:
        raise ReviewImportError(f"No review files matched under {data_dir / REVIEW_SUBDIRECTORY}")
    return tuple(deduped)


def _validate_headers(fieldnames: list[str] | None, file_name: str) -> None:
    headers = set(fieldnames or [])
    missing = sorted(REQUIRED_REVIEW_HEADERS - headers)
    if missing:
        raise ReviewImportError(f"{file_name} missing required headers: {', '.join(missing)}")


def _parse_review(
    row: dict[str, str],
    *,
    file_name: str,
    line_number: int,
    product_id: int,
    profile_mapping_version: str,
) -> _ParsedReview:
    review_code = _required_text(row, "review_id", file_name, line_number)
    product_code = _required_text(row, "product_id", file_name, line_number)
    source = _required_text(row, "source", file_name, line_number)
    source_review_id = _required_text(row, "source_review_id", file_name, line_number)
    rating = _required_int(row, "rating", file_name, line_number)
    if not 1 <= rating <= 5:
        raise ReviewImportError(f"{file_name}:{line_number} rating must be between 1 and 5")
    review_text = _required_content_text(row, "review_text", file_name, line_number)
    reviewed_at = _required_reviewed_at(row, file_name, line_number)
    option_text = _optional_text(row.get("option_text"))
    helpful_count = _required_int(row, "helpful_count", file_name, line_number)
    if helpful_count < 0:
        raise ReviewImportError(f"{file_name}:{line_number} helpful_count must be non-negative")
    is_month_use_review = _required_bool(row, "is_month_use_review", file_name, line_number)
    review_type, source_review_type = _normalize_review_type(
        row,
        is_month_use_review=is_month_use_review,
        file_name=file_name,
        line_number=line_number,
    )
    is_repurchase = _required_bool(row, "is_repurchase", file_name, line_number)
    has_photo = _required_bool(row, "has_photo", file_name, line_number)
    badges = list(_split_labels(row.get("review_badge_labels"))) or None
    source_collected_at = _required_datetime(row, "collected_at", file_name, line_number)
    mapping = map_review_profile_labels(
        skin_type_label=_optional_text(row.get("reviewer_skin_type_label_ko")),
        skin_tone_label=_optional_text(row.get("reviewer_skin_tone_label_ko")),
        skin_concern_labels=_optional_text(row.get("reviewer_skin_trouble_labels_ko")),
        combined_profile_labels=_optional_text(row.get("reviewer_profile_labels_ko")),
    )
    normalized_source = source.strip().lower()
    normalized_payload = {
        key: _optional_text(row.get(key))
        for key in sorted(REQUIRED_REVIEW_HEADERS)
    }
    content_hash = hashlib.sha256(
        json.dumps(
            normalized_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return _ParsedReview(
        file_name=file_name,
        line_number=line_number,
        review_code=review_code,
        product_code=product_code,
        product_id=product_id,
        source=normalized_source,
        source_review_id=source_review_id,
        status="PUBLISHED",
        review_type=review_type,
        rating=rating,
        review_text=review_text,
        reviewed_at=reviewed_at,
        option_text=option_text,
        is_repurchase_review=is_repurchase,
        verified_purchase=None,
        helpful_count=helpful_count,
        source_has_photo=has_photo,
        source_badge_labels_json=badges,
        source_metadata_json={
            "source_review_type": source_review_type,
            "source_is_month_use_review": is_month_use_review,
        },
        source_collected_at=source_collected_at,
        source_content_hash=content_hash,
        profile_mapping_version=profile_mapping_version,
        published_at=reviewed_at,
        profile_labels=mapping.labels,
        unknown_profile_labels=mapping.unknown_labels,
        has_source_profile=mapping.has_source_profile,
    )


def _process_batch(
    session: Session,
    batch: list[_ParsedReview],
    *,
    dialect_name: str,
    dry_run: bool,
    sqlite_seen: set[tuple[str, int, str]],
) -> _BatchResult:
    if dialect_name == "postgresql":
        _copy_batch_to_postgres_stage(session, batch)
        duplicate_count = _register_postgres_seen_rows(session)
    else:
        duplicate_count = _register_sqlite_seen_rows(batch, sqlite_seen)
    if duplicate_count:
        first = batch[0]
        raise ReviewImportError(
            f"{first.file_name}:{first.line_number} duplicate source review rows in import input: "
            f"{duplicate_count}"
        )

    existing_by_key = _load_existing_reviews(session, batch)
    _validate_review_code_ownership(session, batch)
    changed: list[_ParsedReview] = []
    inserted = 0
    updated = 0
    unchanged = 0
    for review in batch:
        existing = existing_by_key.get(review.source_key)
        if existing is None:
            inserted += 1
            changed.append(review)
        elif (
            existing.source_content_hash == review.source_content_hash
            and existing.profile_mapping_version == review.profile_mapping_version
        ):
            unchanged += 1
        else:
            updated += 1
            changed.append(review)

    profile_label_count = sum(len(review.profile_labels) for review in changed)
    if not dry_run:
        if dialect_name == "postgresql":
            _upsert_postgres_stage(session)
        else:
            _upsert_sqlite_batch(session, batch)
        _sync_profile_labels(session, changed)
        session.flush()
    return _BatchResult(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        profile_labels=profile_label_count,
    )


def _load_existing_reviews(
    session: Session,
    batch: list[_ParsedReview],
) -> dict[tuple[str, int, str], _ExistingReview]:
    keys = [review.source_key for review in batch]
    rows = session.execute(
        select(
            ProductReview.review_code,
            ProductReview.source,
            ProductReview.product_id,
            ProductReview.source_review_id,
            ProductReview.source_content_hash,
            ProductReview.profile_mapping_version,
        ).where(
            tuple_(
                ProductReview.source,
                ProductReview.product_id,
                ProductReview.source_review_id,
            ).in_(keys)
        )
    ).all()
    return {
        (str(source), int(product_id), str(source_review_id)): _ExistingReview(
            review_code=str(review_code),
            source=str(source),
            product_id=int(product_id),
            source_review_id=str(source_review_id),
            source_content_hash=source_content_hash,
            profile_mapping_version=profile_mapping_version,
        )
        for (
            review_code,
            source,
            product_id,
            source_review_id,
            source_content_hash,
            profile_mapping_version,
        ) in rows
    }


def _validate_review_code_ownership(session: Session, batch: list[_ParsedReview]) -> None:
    expected_by_code = {review.review_code: review.source_key for review in batch}
    rows = session.execute(
        select(
            ProductReview.review_code,
            ProductReview.source,
            ProductReview.product_id,
            ProductReview.source_review_id,
        ).where(ProductReview.review_code.in_(expected_by_code))
    ).all()
    for review_code, source, product_id, source_review_id in rows:
        expected_key = expected_by_code[str(review_code)]
        actual_key = str(source), int(product_id), str(source_review_id)
        if expected_key != actual_key:
            raise ReviewImportError(
                f"review_id {review_code} already belongs to "
                f"{actual_key[0]}/{actual_key[1]}/{actual_key[2]}"
            )


def _prepare_postgres_staging(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TEMP TABLE IF NOT EXISTS product_review_import_stage (
                review_code varchar(80) NOT NULL,
                product_id bigint NOT NULL,
                source varchar(40) NOT NULL,
                source_review_id varchar(120) NOT NULL,
                status varchar(20) NOT NULL,
                review_type varchar(20) NOT NULL,
                rating integer NOT NULL,
                review_text text NOT NULL,
                reviewed_at timestamptz NOT NULL,
                option_text text NULL,
                is_repurchase_review boolean NOT NULL,
                verified_purchase boolean NULL,
                helpful_count integer NOT NULL,
                source_has_photo boolean NOT NULL,
                source_badge_labels_json jsonb NULL,
                source_metadata_json jsonb NOT NULL,
                source_collected_at timestamptz NOT NULL,
                source_content_hash varchar(64) NOT NULL,
                profile_mapping_version varchar(40) NOT NULL,
                published_at timestamptz NOT NULL
            ) ON COMMIT DROP
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TEMP TABLE IF NOT EXISTS product_review_import_seen (
                source varchar(40) NOT NULL,
                product_id bigint NOT NULL,
                source_review_id varchar(120) NOT NULL,
                PRIMARY KEY (source, product_id, source_review_id)
            ) ON COMMIT DROP
            """
        )
    )


_POSTGRES_STAGE_COLUMNS = (
    "review_code",
    "product_id",
    "source",
    "source_review_id",
    "status",
    "review_type",
    "rating",
    "review_text",
    "reviewed_at",
    "option_text",
    "is_repurchase_review",
    "verified_purchase",
    "helpful_count",
    "source_has_photo",
    "source_badge_labels_json",
    "source_metadata_json",
    "source_collected_at",
    "source_content_hash",
    "profile_mapping_version",
    "published_at",
)


def _copy_batch_to_postgres_stage(session: Session, batch: list[_ParsedReview]) -> None:
    from psycopg.types.json import Jsonb

    session.execute(text("TRUNCATE product_review_import_stage"))
    raw_connection = session.connection().connection
    driver_connection = getattr(raw_connection, "driver_connection", raw_connection)
    copy_sql = (
        "COPY product_review_import_stage ("
        + ", ".join(_POSTGRES_STAGE_COLUMNS)
        + ") FROM STDIN"
    )
    with driver_connection.cursor() as cursor:
        with cursor.copy(copy_sql) as copy:
            for review in batch:
                values = review.database_values()
                copy.write_row(
                    tuple(
                        Jsonb(values[column])
                        if column in {"source_badge_labels_json", "source_metadata_json"}
                        and values[column] is not None
                        else values[column]
                        for column in _POSTGRES_STAGE_COLUMNS
                    )
                )


def _register_postgres_seen_rows(session: Session) -> int:
    return int(
        session.execute(
            text(
                """
                WITH inserted AS (
                    INSERT INTO product_review_import_seen (source, product_id, source_review_id)
                    SELECT source, product_id, source_review_id
                    FROM product_review_import_stage
                    ON CONFLICT (source, product_id, source_review_id) DO NOTHING
                    RETURNING 1
                )
                SELECT (SELECT count(*) FROM product_review_import_stage) - count(*)
                FROM inserted
                """
            )
        ).scalar_one()
    )


def _register_sqlite_seen_rows(
    batch: list[_ParsedReview],
    seen: set[tuple[str, int, str]],
) -> int:
    duplicate_count = 0
    for review in batch:
        if review.source_key in seen:
            duplicate_count += 1
        else:
            seen.add(review.source_key)
    return duplicate_count


def _upsert_postgres_stage(session: Session) -> None:
    session.execute(
        text(
            """
            INSERT INTO product_reviews (
                review_code, product_id, source, source_review_id, status, review_type,
                rating, review_text, reviewed_at, option_text, is_repurchase_review,
                verified_purchase, helpful_count, source_has_photo,
                source_badge_labels_json, source_metadata_json, source_collected_at,
                source_content_hash, profile_mapping_version, published_at
            )
            SELECT
                review_code, product_id, source, source_review_id, status, review_type,
                rating, review_text, reviewed_at, option_text, is_repurchase_review,
                verified_purchase, helpful_count, source_has_photo,
                source_badge_labels_json, source_metadata_json, source_collected_at,
                source_content_hash, profile_mapping_version, published_at
            FROM product_review_import_stage
            ON CONFLICT (source, product_id, source_review_id) DO UPDATE SET
                review_code = EXCLUDED.review_code,
                product_id = EXCLUDED.product_id,
                status = CASE
                    WHEN product_reviews.status IN ('HIDDEN', 'DELETED') THEN product_reviews.status
                    ELSE EXCLUDED.status
                END,
                review_type = EXCLUDED.review_type,
                rating = EXCLUDED.rating,
                review_text = EXCLUDED.review_text,
                reviewed_at = EXCLUDED.reviewed_at,
                option_text = EXCLUDED.option_text,
                is_repurchase_review = EXCLUDED.is_repurchase_review,
                verified_purchase = EXCLUDED.verified_purchase,
                helpful_count = EXCLUDED.helpful_count,
                source_has_photo = EXCLUDED.source_has_photo,
                source_badge_labels_json = EXCLUDED.source_badge_labels_json,
                source_metadata_json = EXCLUDED.source_metadata_json,
                source_collected_at = EXCLUDED.source_collected_at,
                source_content_hash = EXCLUDED.source_content_hash,
                profile_mapping_version = EXCLUDED.profile_mapping_version,
                published_at = EXCLUDED.published_at,
                updated_at = now()
            WHERE product_reviews.source_content_hash IS DISTINCT FROM EXCLUDED.source_content_hash
               OR product_reviews.profile_mapping_version IS DISTINCT FROM EXCLUDED.profile_mapping_version
            """
        )
    )


def _upsert_sqlite_batch(session: Session, batch: list[_ParsedReview]) -> None:
    table = ProductReview.__table__
    statement = sqlite_insert(table).values([review.database_values() for review in batch])
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.source, table.c.product_id, table.c.source_review_id],
        set_={
            "review_code": excluded.review_code,
            "product_id": excluded.product_id,
            "status": case(
                (table.c.status.in_(("HIDDEN", "DELETED")), table.c.status),
                else_=excluded.status,
            ),
            "review_type": excluded.review_type,
            "rating": excluded.rating,
            "review_text": excluded.review_text,
            "reviewed_at": excluded.reviewed_at,
            "option_text": excluded.option_text,
            "is_repurchase_review": excluded.is_repurchase_review,
            "verified_purchase": excluded.verified_purchase,
            "helpful_count": excluded.helpful_count,
            "source_has_photo": excluded.source_has_photo,
            "source_badge_labels_json": excluded.source_badge_labels_json,
            "source_metadata_json": excluded.source_metadata_json,
            "source_collected_at": excluded.source_collected_at,
            "source_content_hash": excluded.source_content_hash,
            "profile_mapping_version": excluded.profile_mapping_version,
            "published_at": excluded.published_at,
            "updated_at": datetime.now(UTC),
        },
        where=or_(
            table.c.source_content_hash.is_distinct_from(excluded.source_content_hash),
            table.c.profile_mapping_version.is_distinct_from(excluded.profile_mapping_version),
        ),
    )
    session.execute(statement)


def _sync_profile_labels(session: Session, changed: list[_ParsedReview]) -> None:
    if not changed:
        return
    keys = [review.source_key for review in changed]
    id_rows = session.execute(
        select(
            ProductReview.id,
            ProductReview.source,
            ProductReview.product_id,
            ProductReview.source_review_id,
        ).where(
            tuple_(
                ProductReview.source,
                ProductReview.product_id,
                ProductReview.source_review_id,
            ).in_(keys)
        )
    ).all()
    review_ids_by_key = {
        (str(source), int(product_id), str(source_review_id)): int(review_id)
        for review_id, source, product_id, source_review_id in id_rows
    }
    review_ids = list(review_ids_by_key.values())
    session.execute(
        delete(ProductReviewProfileLabel).where(ProductReviewProfileLabel.review_id.in_(review_ids))
    )
    label_rows = [
        {
            "review_id": review_ids_by_key[review.source_key],
            "dimension": label.dimension,
            "value_code": label.value_code,
            "source_label": label.source_label,
            "mapping_source": label.mapping_source,
            "mapping_confidence": label.mapping_confidence,
        }
        for review in changed
        for label in review.profile_labels
    ]
    if label_rows:
        session.execute(insert(ProductReviewProfileLabel), label_rows)


def _normalize_review_type(
    row: dict[str, str],
    *,
    is_month_use_review: bool,
    file_name: str,
    line_number: int,
) -> tuple[str, str]:
    source_value = _required_text(row, "review_type", file_name, line_number)
    normalized = source_value.casefold().replace("-", "_").strip()
    if normalized in {"one_month_review", "month_use", "month_use_review"}:
        review_type = "MONTH_USE"
    elif normalized in {"general", "general_review"}:
        review_type = "GENERAL"
    else:
        raise ReviewImportError(
            f"{file_name}:{line_number} unsupported review_type: {source_value}"
        )
    if (review_type == "MONTH_USE") != is_month_use_review:
        raise ReviewImportError(
            f"{file_name}:{line_number} review_type and is_month_use_review conflict"
        )
    return review_type, source_value


def _required_reviewed_at(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> datetime:
    value = _required_text(row, "review_date", file_name, line_number)
    try:
        return datetime.combine(date.fromisoformat(value), time.min, tzinfo=UTC)
    except ValueError as exc:
        raise ReviewImportError(
            f"{file_name}:{line_number} review_date must be YYYY-MM-DD"
        ) from exc


def _required_datetime(
    row: dict[str, str],
    key: str,
    file_name: str,
    line_number: int,
) -> datetime:
    value = _required_text(row, key, file_name, line_number)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewImportError(f"{file_name}:{line_number} invalid {key}: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_bool(
    row: dict[str, str],
    key: str,
    file_name: str,
    line_number: int,
) -> bool:
    value = _required_text(row, key, file_name, line_number).casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ReviewImportError(f"{file_name}:{line_number} {key} must be true or false")


def _required_int(
    row: dict[str, str],
    key: str,
    file_name: str,
    line_number: int,
) -> int:
    value = _required_text(row, key, file_name, line_number)
    try:
        return int(value)
    except ValueError as exc:
        raise ReviewImportError(f"{file_name}:{line_number} {key} must be an integer") from exc


def _required_text(
    row: dict[str, str],
    key: str,
    file_name: str,
    line_number: int,
) -> str:
    raw_value = row.get(key)
    if raw_value is not None and "\x00" in str(raw_value):
        raise ReviewImportError(f"{file_name}:{line_number} {key} contains a NUL byte")
    value = _optional_text(raw_value)
    if value is None:
        raise ReviewImportError(f"{file_name}:{line_number} {key} is required")
    return value


def _required_content_text(
    row: dict[str, str],
    key: str,
    file_name: str,
    line_number: int,
) -> str:
    value = _optional_text(row.get(key))
    if value is None:
        raise ReviewImportError(f"{file_name}:{line_number} {key} is required")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).replace("\x00", "").strip()
    return normalized or None


def _split_labels(value: object) -> tuple[str, ...]:
    text_value = _optional_text(value)
    if text_value is None:
        return ()
    return tuple(item.strip() for item in text_value.split(";") if item.strip())


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    if limit < 1:
        raise ReviewImportError("limit must be at least 1")
    return int(limit)


def _normalize_batch_size(batch_size: int) -> int:
    if batch_size < 1:
        raise ReviewImportError("batch_size must be at least 1")
    return int(batch_size)


def _merge_batch_counters(counters: dict[str, int], batch_result: _BatchResult) -> None:
    counters["inserted"] += batch_result.inserted
    counters["updated"] += batch_result.updated
    counters["unchanged"] += batch_result.unchanged
    counters["profile_labels"] += batch_result.profile_labels
