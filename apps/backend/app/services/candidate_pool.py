from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.elasticsearch_recommendation_candidates import (
    RECOMMENDATION_CANDIDATE_SOURCE,
    RECOMMENDATION_CANDIDATE_STRATEGY_VERSION,
    ElasticsearchRecommendationCandidateResult,
    search_elasticsearch_recommendation_candidates,
)
from app.services.product_candidates import (
    ProductCandidate,
    list_recommendation_fallback_candidates,
)
from app.services.recommendation_intent import RecommendationIntent


CANDIDATE_GENERATION_VERSION = RECOMMENDATION_CANDIDATE_STRATEGY_VERSION
DB_POPULARITY_FALLBACK_SOURCE = "db_popularity_fallback"
ElasticsearchSearchFunc = Callable[..., ElasticsearchRecommendationCandidateResult]


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
    fallback_reason: str | None = None
    fallback_duration_ms: int = 0
    fallback_count: int = 0
    es_search_ms: int = 0
    es_direct_match_count: int = 0
    es_popularity_fill_count: int = 0
    es_raw_hit_count: int = 0
    pre_dedupe_count: int = 0
    post_dedupe_count: int = 0
    cap_applied_count: int = 0
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
            "strategy": "catalog_es_candidate_pool",
            "requested_candidate_pool_limit": self.requested_candidate_pool_limit,
            "loaded_candidate_count": len(self.candidates),
            "avoid_filtered_count": self.avoid_filtered_count,
            "after_avoid_filter_count": len(self.candidates),
            "merged_count": self.merged_count,
            "deduped_count": self.deduped_count,
            "pre_dedupe_count": self.pre_dedupe_count,
            "post_dedupe_count": self.post_dedupe_count,
            "final_candidate_count": len(self.candidates),
            "cap_applied_count": self.cap_applied_count,
            "es_search_ms": self.es_search_ms,
            "es_direct_match_count": self.es_direct_match_count,
            "es_popularity_fill_count": self.es_popularity_fill_count,
            "es_raw_hit_count": self.es_raw_hit_count,
            "source_counts": self.source_counts,
            "source_diagnostics": [
                diagnostic.to_dict() for diagnostic in self.source_diagnostics
            ],
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "fallback_duration_ms": self.fallback_duration_ms,
            "fallback_count": self.fallback_count,
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
    elasticsearch_search: ElasticsearchSearchFunc = search_elasticsearch_recommendation_candidates,
) -> CandidatePool:
    requested_limit = max(1, target_pool_size)
    source_diagnostics: list[CandidateSourceDiagnostic] = []
    notes: list[str] = [
        f"skin_type={skin_type}",
        f"sensitivity={sensitivity}",
        "pgvector candidate source disabled in v2",
    ]
    es_result: ElasticsearchRecommendationCandidateResult | None = None
    fallback_reason: str | None = None

    if _should_attempt_elasticsearch(
        session,
        enable_elasticsearch=enable_elasticsearch,
    ):
        es_result = elasticsearch_search(
            intent,
            avoid_ingredients=avoid_ingredients,
            limit=requested_limit,
        )
        source_diagnostics.append(
            _build_elasticsearch_diagnostic(
                es_result,
                requested_limit=requested_limit,
            )
        )
        if es_result.successful:
            candidates = _dedupe_candidates(list(es_result.candidates))
            capped_candidates = candidates[:requested_limit]
            return CandidatePool(
                candidates=capped_candidates,
                requested_candidate_pool_limit=requested_limit,
                merged_count=es_result.pre_dedupe_count,
                deduped_count=len(candidates),
                avoid_filtered_count=0,
                source_diagnostics=tuple(source_diagnostics),
                es_search_ms=es_result.duration_ms,
                es_direct_match_count=es_result.direct_match_count,
                es_popularity_fill_count=es_result.popularity_fill_count,
                es_raw_hit_count=es_result.raw_hit_count,
                pre_dedupe_count=es_result.pre_dedupe_count,
                post_dedupe_count=len(candidates),
                cap_applied_count=max(0, len(candidates) - len(capped_candidates)),
                hard_filter_total_count=es_result.total_hit_count,
                notes=tuple((*notes, "catalog Elasticsearch source connected")),
            )
        fallback_reason = es_result.failure_reason or es_result.skipped_reason or "unknown ES failure"
        notes.append("catalog Elasticsearch source unavailable")
    else:
        fallback_reason = _elasticsearch_skip_note(
            session,
            enable_elasticsearch=enable_elasticsearch,
        )
        source_diagnostics.append(
            CandidateSourceDiagnostic(
                source=RECOMMENDATION_CANDIDATE_SOURCE,
                requested_limit=requested_limit,
                returned_count=0,
                after_dedupe_count=0,
                failure_reason=fallback_reason,
                duration_ms=0,
                metadata={
                    "raw_hit_count": 0,
                    "direct_match_count": 0,
                    "popularity_fill_count": 0,
                },
            )
        )
        notes.append("catalog Elasticsearch source not attempted")

    fallback_started_at = perf_counter()
    fallback_candidates = list_recommendation_fallback_candidates(
        session,
        intent.purchase_conditions,
        avoid_ingredients=avoid_ingredients,
        limit=requested_limit,
    )
    fallback_duration_ms = _elapsed_ms(fallback_started_at)
    fallback_deduped_candidates = _dedupe_candidates(fallback_candidates)
    capped_candidates = fallback_deduped_candidates[:requested_limit]
    source_diagnostics.append(
        CandidateSourceDiagnostic(
            source=DB_POPULARITY_FALLBACK_SOURCE,
            requested_limit=requested_limit,
            returned_count=len(fallback_candidates),
            after_dedupe_count=len(fallback_deduped_candidates),
            duration_ms=fallback_duration_ms,
            metadata={"fallback_reason": fallback_reason},
        )
    )
    notes.append("popularity-ranked DB fallback used because Elasticsearch was unavailable")
    return CandidatePool(
        candidates=capped_candidates,
        requested_candidate_pool_limit=requested_limit,
        merged_count=len(fallback_candidates),
        deduped_count=len(fallback_deduped_candidates),
        avoid_filtered_count=0,
        source_diagnostics=tuple(source_diagnostics),
        fallback_used=True,
        fallback_reason=fallback_reason,
        fallback_duration_ms=fallback_duration_ms,
        fallback_count=len(capped_candidates),
        es_search_ms=es_result.duration_ms if es_result is not None else 0,
        es_direct_match_count=es_result.direct_match_count if es_result is not None else 0,
        es_popularity_fill_count=(
            es_result.popularity_fill_count if es_result is not None else 0
        ),
        es_raw_hit_count=es_result.raw_hit_count if es_result is not None else 0,
        pre_dedupe_count=len(fallback_candidates),
        post_dedupe_count=len(fallback_deduped_candidates),
        cap_applied_count=max(0, len(fallback_deduped_candidates) - len(capped_candidates)),
        hard_filter_total_count=(
            es_result.total_hit_count if es_result is not None else None
        ),
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


def _elasticsearch_skip_note(
    session: Session,
    *,
    enable_elasticsearch: bool | None,
) -> str:
    if enable_elasticsearch is False:
        return "catalog Elasticsearch disabled by caller"
    if settings.search_backend_mode == "postgres":
        return "catalog Elasticsearch disabled by search_backend_mode=postgres"
    return f"catalog Elasticsearch skipped for {session.get_bind().dialect.name}"


def _build_elasticsearch_diagnostic(
    result: ElasticsearchRecommendationCandidateResult,
    *,
    requested_limit: int,
) -> CandidateSourceDiagnostic:
    metadata: dict[str, Any] = {
        "raw_hit_count": result.raw_hit_count,
        "direct_match_count": result.direct_match_count,
        "popularity_fill_count": result.popularity_fill_count,
        "pre_dedupe_count": result.pre_dedupe_count,
        "post_dedupe_count": result.deduped_count,
        "total_hit_count": result.total_hit_count,
        "index_alias": result.index_alias,
    }
    return CandidateSourceDiagnostic(
        source=RECOMMENDATION_CANDIDATE_SOURCE,
        requested_limit=requested_limit,
        returned_count=len(result.candidates),
        after_dedupe_count=result.deduped_count,
        skipped_count=max(0, result.raw_hit_count - result.pre_dedupe_count),
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


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
