from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.catalog import ProductIngredient
from app.db.models.taxonomy import Ingredient
from app.services.elasticsearch_product_search import (
    ES_KEYWORD_SEARCH_SOURCE,
    ElasticsearchProductSearchResult,
    search_elasticsearch_product_candidates,
)
from app.services.pgvector_product_search import (
    PGVECTOR_SEARCH_SOURCE,
    PgvectorProductSearchResult,
    search_pgvector_product_candidates,
)
from app.services.product_candidates import (
    ProductCandidate,
    list_product_candidates,
    list_product_candidates_by_db_ids,
)
from app.services.recommendation_intent import RecommendationIntent


CANDIDATE_GENERATION_VERSION = "candidate_pool_pgvector_v1"
LEGACY_ID_ORDER_SOURCE = "legacy_id_order"
ElasticsearchSearchFunc = Callable[..., ElasticsearchProductSearchResult]
PgvectorSearchFunc = Callable[..., PgvectorProductSearchResult]


@dataclass(frozen=True)
class CandidateSourceDiagnostic:
    source: str
    requested_limit: int
    returned_count: int
    after_dedupe_count: int
    skipped_count: int = 0
    failure_reason: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "requested_limit": self.requested_limit,
            "returned_count": self.returned_count,
            "after_dedupe_count": self.after_dedupe_count,
            "skipped_count": self.skipped_count,
        }
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.metadata:
            payload.update(self.metadata)
        return payload


@dataclass(frozen=True)
class CandidatePool:
    candidates: list[ProductCandidate]
    requested_candidate_pool_limit: int
    merged_count: int
    deduped_count: int
    avoid_filtered_count: int
    source_diagnostics: tuple[CandidateSourceDiagnostic, ...]
    fallback_used: bool = False
    hard_filter_total_count: int | None = None
    notes: tuple[str, ...] = ()

    @property
    def source_counts(self) -> dict[str, int]:
        return {
            diagnostic.source: diagnostic.returned_count
            for diagnostic in self.source_diagnostics
        }

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "candidate_generation_version": CANDIDATE_GENERATION_VERSION,
            "strategy": "candidate_pool",
            "requested_candidate_pool_limit": self.requested_candidate_pool_limit,
            "loaded_candidate_count": self.deduped_count,
            "avoid_filtered_count": self.avoid_filtered_count,
            "after_avoid_filter_count": len(self.candidates),
            "merged_count": self.merged_count,
            "deduped_count": self.deduped_count,
            "source_counts": self.source_counts,
            "source_diagnostics": [
                diagnostic.to_dict()
                for diagnostic in self.source_diagnostics
            ],
            "fallback_used": self.fallback_used,
            "hard_filter_total_count": self.hard_filter_total_count,
            "notes": list(self.notes),
        }


def generate_candidate_pool(
    session: Session,
    intent: RecommendationIntent,
    *,
    skin_type: str,
    sensitivity: str,
    avoid_ingredients: list[str],
    target_pool_size: int,
    enable_elasticsearch: bool | None = None,
    enable_pgvector: bool | None = None,
    elasticsearch_search: ElasticsearchSearchFunc = search_elasticsearch_product_candidates,
    pgvector_search: PgvectorSearchFunc = search_pgvector_product_candidates,
) -> CandidatePool:
    requested_limit = max(1, target_pool_size)
    source_diagnostics: list[CandidateSourceDiagnostic] = []
    notes: list[str] = [
        f"skin_type={skin_type}",
        f"sensitivity={sensitivity}",
    ]
    es_candidates: list[ProductCandidate] = []
    pgvector_candidates: list[ProductCandidate] = []
    es_result: ElasticsearchProductSearchResult | None = None
    pgvector_result: PgvectorProductSearchResult | None = None
    should_attempt_elasticsearch = _should_attempt_elasticsearch(
        session,
        enable_elasticsearch=enable_elasticsearch,
    )
    if should_attempt_elasticsearch:
        es_result = elasticsearch_search(intent, limit=requested_limit)
        es_candidates = list_product_candidates_by_db_ids(
            session,
            intent.purchase_conditions,
            list(es_result.product_db_ids),
            limit=requested_limit,
        )
        source_diagnostics.append(
            _build_elasticsearch_diagnostic(
                es_result,
                hydrated_count=len(es_candidates),
                requested_limit=requested_limit,
            )
        )
        if es_result.failure_reason:
            notes.append("elasticsearch keyword source failed")
        elif es_result.skipped_reason:
            notes.append(f"elasticsearch keyword source skipped: {es_result.skipped_reason}")
        else:
            notes.append("elasticsearch keyword source connected")
    else:
        notes.append(_elasticsearch_skip_note(session, enable_elasticsearch=enable_elasticsearch))

    should_attempt_pgvector = _should_attempt_pgvector(
        session,
        enable_pgvector=enable_pgvector,
    )
    if should_attempt_pgvector:
        pgvector_result = pgvector_search(session, intent, limit=requested_limit)
        pgvector_candidates = list_product_candidates_by_db_ids(
            session,
            intent.purchase_conditions,
            list(pgvector_result.product_db_ids),
            limit=requested_limit,
        )
        source_diagnostics.append(
            _build_pgvector_diagnostic(
                pgvector_result,
                hydrated_count=len(pgvector_candidates),
                requested_limit=requested_limit,
            )
        )
        if pgvector_result.failure_reason:
            notes.append("pgvector source failed")
        elif pgvector_result.skipped_reason:
            notes.append(f"pgvector source skipped: {pgvector_result.skipped_reason}")
        else:
            notes.append("pgvector source connected")
    else:
        notes.append(_pgvector_skip_note(session, enable_pgvector=enable_pgvector))

    legacy_candidates = list_product_candidates(
        session,
        intent.purchase_conditions,
        limit=requested_limit,
    )
    legacy_deduped_candidates = _dedupe_candidates(legacy_candidates)
    source_diagnostics.append(
        CandidateSourceDiagnostic(
            source=LEGACY_ID_ORDER_SOURCE,
            requested_limit=requested_limit,
            returned_count=len(legacy_candidates),
            after_dedupe_count=len(legacy_deduped_candidates),
        )
    )

    merged_candidates = [*es_candidates, *pgvector_candidates, *legacy_candidates]
    deduped_candidates = _dedupe_candidates(merged_candidates)
    candidates = _filter_avoided_ingredients(
        session,
        deduped_candidates,
        avoid_ingredients,
    )
    retrieval_candidate_count = len(es_candidates) + len(pgvector_candidates)
    retrieval_unavailable = (
        (
            should_attempt_elasticsearch
            and es_result is not None
            and bool(es_result.failure_reason or es_result.skipped_reason)
        )
        or (
            should_attempt_pgvector
            and pgvector_result is not None
            and bool(pgvector_result.failure_reason or pgvector_result.skipped_reason)
        )
    )
    fallback_used = (
        len(legacy_candidates) > 0
        and retrieval_candidate_count == 0
        and retrieval_unavailable
    )

    return CandidatePool(
        candidates=candidates,
        requested_candidate_pool_limit=requested_limit,
        merged_count=len(merged_candidates),
        deduped_count=len(deduped_candidates),
        avoid_filtered_count=len(deduped_candidates) - len(candidates),
        source_diagnostics=tuple(source_diagnostics),
        fallback_used=fallback_used,
        notes=tuple(notes),
    )


def _should_attempt_elasticsearch(
    session: Session,
    *,
    enable_elasticsearch: bool | None,
) -> bool:
    if enable_elasticsearch is not None:
        return enable_elasticsearch
    if settings.search_backend_mode == "postgres":
        return False
    return session.get_bind().dialect.name == "postgresql"


def _should_attempt_pgvector(
    session: Session,
    *,
    enable_pgvector: bool | None,
) -> bool:
    if enable_pgvector is not None:
        return enable_pgvector
    return session.get_bind().dialect.name == "postgresql"


def _elasticsearch_skip_note(
    session: Session,
    *,
    enable_elasticsearch: bool | None,
) -> str:
    if enable_elasticsearch is False:
        return "elasticsearch keyword source disabled by caller"
    if settings.search_backend_mode == "postgres":
        return "elasticsearch keyword source disabled by search_backend_mode=postgres"
    return f"elasticsearch keyword source skipped for {session.get_bind().dialect.name}"


def _pgvector_skip_note(
    session: Session,
    *,
    enable_pgvector: bool | None,
) -> str:
    if enable_pgvector is False:
        return "pgvector source disabled by caller"
    return f"pgvector source skipped for {session.get_bind().dialect.name}"


def _build_elasticsearch_diagnostic(
    result: ElasticsearchProductSearchResult,
    *,
    hydrated_count: int,
    requested_limit: int,
) -> CandidateSourceDiagnostic:
    skipped_count = max(0, result.raw_hit_count - hydrated_count)
    return CandidateSourceDiagnostic(
        source=ES_KEYWORD_SEARCH_SOURCE,
        requested_limit=requested_limit,
        returned_count=result.raw_hit_count,
        after_dedupe_count=hydrated_count,
        skipped_count=skipped_count,
        failure_reason=result.failure_reason or result.skipped_reason,
        duration_ms=result.duration_ms,
    )


def _build_pgvector_diagnostic(
    result: PgvectorProductSearchResult,
    *,
    hydrated_count: int,
    requested_limit: int,
) -> CandidateSourceDiagnostic:
    skipped_count = max(0, result.raw_hit_count - hydrated_count)
    metadata: dict[str, Any] = {}
    if result.provider_model is not None:
        metadata["provider_model"] = result.provider_model
    if result.dimensions is not None:
        metadata["embedding_dimensions"] = result.dimensions
    if result.embedding_coverage is not None:
        metadata["embedding_coverage"] = result.embedding_coverage
    if result.total_hit_count is not None:
        metadata["total_hit_count"] = result.total_hit_count

    return CandidateSourceDiagnostic(
        source=PGVECTOR_SEARCH_SOURCE,
        requested_limit=requested_limit,
        returned_count=result.raw_hit_count,
        after_dedupe_count=hydrated_count,
        skipped_count=skipped_count,
        failure_reason=result.failure_reason or result.skipped_reason,
        duration_ms=result.duration_ms,
        metadata=metadata,
    )


def _dedupe_candidates(candidates: list[ProductCandidate]) -> list[ProductCandidate]:
    deduped: list[ProductCandidate] = []
    seen_product_ids: set[int] = set()
    for candidate in candidates:
        if candidate.db_product_id in seen_product_ids:
            continue
        seen_product_ids.add(candidate.db_product_id)
        deduped.append(candidate)
    return deduped


def _filter_avoided_ingredients(
    session: Session,
    candidates: list[ProductCandidate],
    avoid_ingredients: list[str],
) -> list[ProductCandidate]:
    avoid_terms = {_normalize_match_text(ingredient) for ingredient in avoid_ingredients}
    avoid_terms.discard("")
    if not candidates or not avoid_terms:
        return candidates

    candidate_ids = [candidate.db_product_id for candidate in candidates]
    rows = session.execute(
        select(
            ProductIngredient.product_id,
            ProductIngredient.ingredient_name,
            Ingredient.ingredient_code,
            Ingredient.name_ko,
            Ingredient.name_en,
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .where(ProductIngredient.product_id.in_(candidate_ids))
    ).all()

    blocked_product_ids: set[int] = set()
    for product_id, ingredient_name, ingredient_code, name_ko, name_en in rows:
        searchable_values = {
            _normalize_match_text(value)
            for value in (ingredient_name, ingredient_code, name_ko, name_en)
            if value
        }
        if _has_avoided_match(avoid_terms, searchable_values):
            blocked_product_ids.add(int(product_id))

    return [
        candidate
        for candidate in candidates
        if candidate.db_product_id not in blocked_product_ids
    ]


def _has_avoided_match(avoid_terms: set[str], values: set[str]) -> bool:
    return any(
        avoid_term in value or value in avoid_term
        for avoid_term in avoid_terms
        for value in values
        if avoid_term and value
    )


def _normalize_match_text(value: str) -> str:
    return "".join(value.casefold().split())
