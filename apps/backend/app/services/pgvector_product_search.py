from __future__ import annotations

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from app.db.models.search import SearchDocument
from app.services.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    format_vector,
    get_default_embedding_provider,
)
from app.services.recommendation_intent import RecommendationIntent
from app.services.search_index_builder import DOCUMENT_CODE_PREFIX


PGVECTOR_SEARCH_SOURCE = "pgvector_search"
DEFAULT_MIN_EMBEDDING_COVERAGE = 0.8
JOIN_DOCUMENT_CODE_PATTERN = f"{DOCUMENT_CODE_PREFIX}%"
EXACT_TITLE_TERM_BONUS = 0.12
EXACT_BODY_TERM_BONUS = 0.06
EXACT_PRIMARY_TERM_BONUS = 0.08
MAX_EXACT_KEYWORD_BONUS = 0.3
MAX_EXACT_PRIMARY_BONUS = 0.12
MAX_EXACT_QUERY_TERMS = 8
EXACT_BONUS_STOP_TERMS = {
    "추천",
    "피부",
    "케어",
    "크림",
    "세럼",
    "앰플",
    "토너",
    "로션",
    "에센스",
}


@dataclass(frozen=True)
class PgvectorProductSearchResult:
    product_db_ids: tuple[int, ...]
    scores_by_product_db_id: dict[int, float]
    raw_hit_count: int
    attempted: bool
    query_text: str
    provider_model: str | None
    dimensions: int | None
    duration_ms: int
    embedding_coverage: float | None = None
    failure_reason: str | None = None
    skipped_reason: str | None = None
    total_hit_count: int | None = None

    @property
    def successful(self) -> bool:
        return self.attempted and self.failure_reason is None and self.skipped_reason is None


@dataclass(frozen=True)
class _EmbeddingCoverage:
    total_documents: int
    embedded_documents: int

    @property
    def ratio(self) -> float:
        if self.total_documents <= 0:
            return 0.0
        return round(self.embedded_documents / self.total_documents, 4)


def search_pgvector_product_candidates(
    session: Session,
    intent: RecommendationIntent,
    *,
    limit: int,
    offset: int = 0,
    embedding_provider: EmbeddingProvider | None = None,
    min_embedding_coverage: float = DEFAULT_MIN_EMBEDDING_COVERAGE,
) -> PgvectorProductSearchResult:
    started_at = perf_counter()
    query_text = _build_query_text(intent)
    provider = embedding_provider or get_default_embedding_provider()

    if session.get_bind().dialect.name != "postgresql":
        return _skipped_result(
            query_text=query_text,
            provider=provider,
            started_at=started_at,
            reason=f"pgvector skipped for {session.get_bind().dialect.name}",
        )

    if not query_text:
        return _skipped_result(
            query_text=query_text,
            provider=provider,
            started_at=started_at,
            reason="empty vector query",
        )

    coverage = _load_embedding_coverage(session, provider)
    if coverage.total_documents <= 0:
        return _skipped_result(
            query_text=query_text,
            provider=provider,
            started_at=started_at,
            reason="no product search documents",
            embedding_coverage=coverage.ratio,
        )
    if coverage.embedded_documents <= 0:
        return _skipped_result(
            query_text=query_text,
            provider=provider,
            started_at=started_at,
            reason=f"no embeddings for provider {provider.model}",
            embedding_coverage=coverage.ratio,
        )
    if coverage.ratio < min_embedding_coverage:
        return _skipped_result(
            query_text=query_text,
            provider=provider,
            started_at=started_at,
            reason=(
                "embedding coverage below threshold: "
                f"{coverage.ratio:.4f} < {min_embedding_coverage:.4f}"
            ),
            embedding_coverage=coverage.ratio,
        )

    try:
        query_vector = provider.embed_text(query_text)
    except EmbeddingError as exc:
        return PgvectorProductSearchResult(
            product_db_ids=(),
            scores_by_product_db_id={},
            raw_hit_count=0,
            attempted=True,
            query_text=query_text,
            provider_model=provider.model,
            dimensions=provider.dimensions,
            duration_ms=_elapsed_ms(started_at),
            embedding_coverage=coverage.ratio,
            failure_reason=str(exc),
            total_hit_count=0,
        )

    try:
        query_terms = _query_terms(query_text)
        rows = _load_vector_hits(
            session,
            intent,
            provider=provider,
            query_embedding=format_vector(query_vector),
            query_terms=query_terms,
            limit=max(1, limit),
            offset=max(0, offset),
        )
        total_hit_count = _count_vector_hits(session, intent, provider=provider)
    except Exception as exc:
        return PgvectorProductSearchResult(
            product_db_ids=(),
            scores_by_product_db_id={},
            raw_hit_count=0,
            attempted=True,
            query_text=query_text,
            provider_model=provider.model,
            dimensions=provider.dimensions,
            duration_ms=_elapsed_ms(started_at),
            embedding_coverage=coverage.ratio,
            failure_reason=str(exc),
            total_hit_count=0,
        )

    product_db_ids = tuple(product_db_id for product_db_id, _ in rows)
    return PgvectorProductSearchResult(
        product_db_ids=product_db_ids,
        scores_by_product_db_id={
            product_db_id: vector_score
            for product_db_id, vector_score in rows
        },
        raw_hit_count=len(product_db_ids),
        attempted=True,
        query_text=query_text,
        provider_model=provider.model,
        dimensions=provider.dimensions,
        duration_ms=_elapsed_ms(started_at),
        embedding_coverage=coverage.ratio,
        total_hit_count=total_hit_count,
    )


def _load_embedding_coverage(
    session: Session,
    provider: EmbeddingProvider,
) -> _EmbeddingCoverage:
    total_documents = int(
        session.execute(
            select(func.count())
            .select_from(SearchDocument)
            .where(
                SearchDocument.document_type == "product",
                SearchDocument.document_code.like(JOIN_DOCUMENT_CODE_PATTERN),
            )
        ).scalar_one()
    )
    embedded_documents = int(
        session.execute(
            select(func.count())
            .select_from(SearchDocument)
            .where(
                SearchDocument.document_type == "product",
                SearchDocument.document_code.like(JOIN_DOCUMENT_CODE_PATTERN),
                SearchDocument.embedding.is_not(None),
                SearchDocument.embedding_model == provider.model,
                SearchDocument.embedding_dimensions == provider.dimensions,
            )
        ).scalar_one()
    )
    return _EmbeddingCoverage(
        total_documents=total_documents,
        embedded_documents=embedded_documents,
    )


def _load_vector_hits(
    session: Session,
    intent: RecommendationIntent,
    *,
    provider: EmbeddingProvider,
    query_embedding: str,
    query_terms: tuple[str, ...],
    limit: int,
    offset: int,
) -> list[tuple[int, float]]:
    sql, params, expanding_params = _build_vector_hits_query(
        intent,
        provider=provider,
        query_embedding=query_embedding,
        query_terms=query_terms,
        limit=limit,
        offset=offset,
        count_only=False,
    )
    statement = text(sql)
    for param_name in expanding_params:
        statement = statement.bindparams(bindparam(param_name, expanding=True))

    rows = session.execute(statement, params).all()
    return [
        (int(row.product_id), _clamp_score(float(row.vector_score or 0.0)))
        for row in rows
    ]


def _count_vector_hits(
    session: Session,
    intent: RecommendationIntent,
    *,
    provider: EmbeddingProvider,
) -> int:
    sql, params, expanding_params = _build_vector_hits_query(
        intent,
        provider=provider,
        query_embedding=None,
        limit=0,
        offset=0,
        count_only=True,
    )
    statement = text(sql)
    for param_name in expanding_params:
        statement = statement.bindparams(bindparam(param_name, expanding=True))
    return int(session.execute(statement, params).scalar_one() or 0)


def _build_vector_hits_query(
    intent: RecommendationIntent,
    *,
    provider: EmbeddingProvider,
    query_embedding: str | None,
    query_terms: tuple[str, ...] = (),
    limit: int,
    offset: int,
    count_only: bool,
) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    conditions = [
        "sd.document_type = 'product'",
        "sd.document_code LIKE :join_document_code_pattern",
        "sd.embedding IS NOT NULL",
        "sd.embedding_model = :embedding_model",
        "sd.embedding_dimensions = :embedding_dimensions",
        "p.is_active = true",
        "b.is_active = true",
        "pc.is_active = true",
    ]
    params: dict[str, Any] = {
        "join_document_code_pattern": JOIN_DOCUMENT_CODE_PATTERN,
        "embedding_model": provider.model,
        "embedding_dimensions": provider.dimensions,
    }
    expanding_params: list[str] = []

    purchase_conditions = intent.purchase_conditions
    if purchase_conditions.categories:
        conditions.append("pc.category_code IN :category_codes")
        params["category_codes"] = [
            category.category_code
            for category in purchase_conditions.categories
        ]
        expanding_params.append("category_codes")
    if purchase_conditions.brands:
        conditions.append("b.brand_code IN :brand_codes")
        params["brand_codes"] = [
            brand.brand_code
            for brand in purchase_conditions.brands
        ]
        expanding_params.append("brand_codes")
    if purchase_conditions.price_min is not None:
        conditions.append("prices.lowest_price >= :price_min")
        params["price_min"] = purchase_conditions.price_min
    if purchase_conditions.price_max is not None:
        conditions.append("prices.lowest_price <= :price_max")
        params["price_max"] = purchase_conditions.price_max

    where_clause = "\n          AND ".join(conditions)
    if count_only:
        sql = f"""
        SELECT COUNT(DISTINCT sd.product_id)
        FROM search_documents sd
        JOIN products p ON sd.product_id = p.id
        JOIN brands b ON p.brand_id = b.id
        JOIN product_categories pc ON p.category_id = pc.id
        JOIN (
            SELECT product_id, MIN(price) AS lowest_price
            FROM product_prices
            GROUP BY product_id
        ) prices ON prices.product_id = p.id
        WHERE {where_clause}
        """
        return sql, params, tuple(expanding_params)

    exact_bonus_sql, exact_bonus_params = _exact_keyword_bonus_sql(query_terms)
    params.update(exact_bonus_params)
    params["query_embedding"] = query_embedding
    params["limit"] = limit
    params["offset"] = offset
    vector_score_sql = "MAX(GREATEST(0.0, 1.0 - (sd.embedding <=> CAST(:query_embedding AS vector))))"
    exact_bonus_score_sql = f"MAX({exact_bonus_sql})"
    search_score_sql = f"LEAST(1.0, {vector_score_sql} + {exact_bonus_score_sql})"
    sql = f"""
    SELECT
        sd.product_id,
        {search_score_sql} AS vector_score
    FROM search_documents sd
    JOIN products p ON sd.product_id = p.id
    JOIN brands b ON p.brand_id = b.id
    JOIN product_categories pc ON p.category_id = pc.id
    JOIN (
        SELECT product_id, MIN(price) AS lowest_price
        FROM product_prices
        GROUP BY product_id
    ) prices ON prices.product_id = p.id
    WHERE {where_clause}
    GROUP BY sd.product_id
    ORDER BY vector_score DESC, {vector_score_sql} DESC, sd.product_id ASC
    LIMIT :limit OFFSET :offset
    """
    return sql, params, tuple(expanding_params)


def _exact_keyword_bonus_sql(query_terms: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    terms = query_terms[:MAX_EXACT_QUERY_TERMS]
    if not terms:
        return "0.0", {}

    params: dict[str, str] = {}
    title_matches: list[str] = []
    body_matches: list[str] = []
    primary_matches: list[str] = []
    title_text = _brand_stripped_text_sql("CONCAT_WS(' ', p.product_name, sd.title, pc.name)")
    body_text = _brand_stripped_text_sql("CONCAT_WS(' ', sd.keywords, sd.content)")

    for index, term in enumerate(terms):
        param_name = f"exact_term_{index}"
        params[param_name] = f"%{term}%"
        title_matches.append(
            f"CASE WHEN {title_text} LIKE :{param_name} THEN 1 ELSE 0 END"
        )
        body_matches.append(
            f"CASE WHEN {body_text} LIKE :{param_name} THEN 1 ELSE 0 END"
        )
        primary_matches.append(
            f"CASE WHEN {title_text} LIKE :{param_name} THEN 1 ELSE 0 END"
        )

    title_score = " + ".join(title_matches) or "0"
    body_score = " + ".join(body_matches) or "0"
    primary_score = " + ".join(primary_matches) or "0"
    exact_keyword_score = (
        "LEAST("
        f"{MAX_EXACT_KEYWORD_BONUS}, "
        f"(({title_score}) * {EXACT_TITLE_TERM_BONUS}) "
        f"+ (({body_score}) * {EXACT_BODY_TERM_BONUS})"
        ")"
    )
    primary_keyword_score = (
        "LEAST("
        f"{MAX_EXACT_PRIMARY_BONUS}, "
        f"(({primary_score}) * {EXACT_PRIMARY_TERM_BONUS})"
        ")"
    )
    return (
        f"({exact_keyword_score} + {primary_keyword_score})",
        params,
    )


def _brand_stripped_text_sql(expression: str) -> str:
    lowered_text = f"LOWER({expression})"
    without_brand_name = f"REPLACE({lowered_text}, LOWER(b.name), '')"
    return f"REPLACE({without_brand_name}, LOWER(b.brand_code), '')"


def _build_query_text(intent: RecommendationIntent) -> str:
    terms = [
        intent.concern_text,
        *intent.search_terms,
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(term.strip())
    return " ".join(deduped)


def _query_terms(query_text: str) -> tuple[str, ...]:
    terms = [
        term
        for term in re.split(r"[\s/·,]+", query_text.strip().casefold())
        if len(term) >= 2 and term not in EXACT_BONUS_STOP_TERMS
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return tuple(deduped)


def _skipped_result(
    *,
    query_text: str,
    provider: EmbeddingProvider,
    started_at: float,
    reason: str,
    embedding_coverage: float | None = None,
) -> PgvectorProductSearchResult:
    return PgvectorProductSearchResult(
        product_db_ids=(),
        scores_by_product_db_id={},
        raw_hit_count=0,
        attempted=False,
        query_text=query_text,
        provider_model=provider.model,
        dimensions=provider.dimensions,
        duration_ms=_elapsed_ms(started_at),
        embedding_coverage=embedding_coverage,
        skipped_reason=reason,
        total_hit_count=0,
    )


def _clamp_score(score: float) -> float:
    return max(0.0, min(1.0, round(score, 4)))


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
