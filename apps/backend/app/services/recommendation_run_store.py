from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, ProductCategory
from app.db.models.recommendation import (
    RecommendationResult,
    RecommendationRun,
    RecommendationRunConcern,
    RecommendationRunConstraint,
    RecommendationScoreEvidence,
    SearchCandidate,
)
from app.db.models.taxonomy import Concern
from app.schemas.common import ApiError
from app.services.parser import ParsedConcern, ParsedEffect, ParsedExcludedConcern
from app.services.purchase_conditions import MatchedBrand, MatchedCategory, ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent


DEFAULT_RECOMMENDATION_TTL = timedelta(hours=24)
DEFAULT_SKIN_TYPE = "중성"
DEFAULT_SENSITIVITY = "보통"
DEFAULT_SCORING_VERSION = "v0"
CONFIDENCE_QUANTIZE = Decimal("0.0001")
EXPIRED_RECOMMENDATION_CODE = "EXPIRED_RECOMMENDATION"
EXPIRED_RECOMMENDATION_MESSAGE = "추천 결과 조회 기간이 만료되었습니다."


@dataclass(frozen=True)
class SavedRecommendationRun:
    run: RecommendationRun
    constraints: tuple[RecommendationRunConstraint, ...]
    concerns: tuple[RecommendationRunConcern, ...]


@dataclass(frozen=True)
class CleanupRecommendationRunsResult:
    cutoff: datetime
    dry_run: bool
    recommendation_runs: int
    recommendation_run_constraints: int
    recommendation_run_concerns: int
    search_candidates: int
    recommendation_results: int
    recommendation_score_evidence: int


def save_recommendation_run(
    session: Session,
    intent: RecommendationIntent,
    *,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    avoid_ingredients: list[str] | None = None,
    recommendation_code: str | None = None,
    scoring_version: str = DEFAULT_SCORING_VERSION,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_RECOMMENDATION_TTL,
) -> SavedRecommendationRun:
    created_at = now or datetime.now(UTC)
    run = RecommendationRun(
        recommendation_code=recommendation_code or _generate_recommendation_code(),
        concern_text=intent.concern_text,
        skin_type=_normalize_optional_text(skin_type) or DEFAULT_SKIN_TYPE,
        sensitivity=_normalize_optional_text(sensitivity) or DEFAULT_SENSITIVITY,
        avoid_ingredients=_normalize_avoid_ingredients(avoid_ingredients),
        request_context=_build_request_context(intent),
        parser_result=_build_parser_result(intent),
        scoring_version=scoring_version,
        expires_at=created_at + ttl,
    )
    session.add(run)
    session.flush()

    constraints = _build_constraints(session, run.id, intent.purchase_conditions)
    concerns = _build_concerns(session, run.id, intent.concerns)

    session.add_all([*constraints, *concerns])
    session.flush()

    return SavedRecommendationRun(
        run=run,
        constraints=tuple(constraints),
        concerns=tuple(concerns),
    )


def ensure_recommendation_run_active(
    run: RecommendationRun,
    *,
    now: datetime | None = None,
) -> None:
    if is_recommendation_run_expired(run, now=now):
        raise ApiError(
            410,
            EXPIRED_RECOMMENDATION_CODE,
            EXPIRED_RECOMMENDATION_MESSAGE,
        )


def is_recommendation_run_expired(
    run: RecommendationRun,
    *,
    now: datetime | None = None,
) -> bool:
    expires_at = _as_utc(run.expires_at)
    current_time = _as_utc(now or datetime.now(UTC))
    return expires_at <= current_time


def cleanup_expired_recommendation_runs(
    session: Session,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> CleanupRecommendationRunsResult:
    cutoff = _as_utc(now or datetime.now(UTC))
    run_ids = _load_expired_run_ids(session, cutoff, limit=limit)
    result_ids = _load_result_ids(session, run_ids)

    counts = CleanupRecommendationRunsResult(
        cutoff=cutoff,
        dry_run=dry_run,
        recommendation_runs=len(run_ids),
        recommendation_run_constraints=_count_by_run_ids(
            session,
            RecommendationRunConstraint,
            run_ids,
        ),
        recommendation_run_concerns=_count_by_run_ids(
            session,
            RecommendationRunConcern,
            run_ids,
        ),
        search_candidates=_count_by_run_ids(session, SearchCandidate, run_ids),
        recommendation_results=len(result_ids),
        recommendation_score_evidence=_count_score_evidence(session, result_ids),
    )

    if dry_run or not run_ids:
        return counts

    if result_ids:
        session.execute(
            delete(RecommendationScoreEvidence).where(
                RecommendationScoreEvidence.recommendation_result_id.in_(result_ids),
            )
        )
    session.execute(
        delete(RecommendationResult).where(
            RecommendationResult.recommendation_run_id.in_(run_ids),
        )
    )
    session.execute(
        delete(SearchCandidate).where(SearchCandidate.recommendation_run_id.in_(run_ids))
    )
    session.execute(
        delete(RecommendationRunConstraint).where(
            RecommendationRunConstraint.recommendation_run_id.in_(run_ids),
        )
    )
    session.execute(
        delete(RecommendationRunConcern).where(
            RecommendationRunConcern.recommendation_run_id.in_(run_ids),
        )
    )
    session.execute(delete(RecommendationRun).where(RecommendationRun.id.in_(run_ids)))
    session.flush()
    return counts


def _generate_recommendation_code() -> str:
    return f"rec_{uuid4().hex[:12]}"


def _load_expired_run_ids(
    session: Session,
    cutoff: datetime,
    *,
    limit: int | None,
) -> list[int]:
    statement = (
        select(RecommendationRun.id)
        .where(RecommendationRun.expires_at <= cutoff)
        .order_by(RecommendationRun.expires_at.asc(), RecommendationRun.id.asc())
    )
    if limit is not None:
        statement = statement.limit(max(0, limit))
    return [int(run_id) for run_id in session.execute(statement).scalars().all()]


def _load_result_ids(session: Session, run_ids: list[int]) -> list[int]:
    if not run_ids:
        return []
    return [
        int(result_id)
        for result_id in session.execute(
            select(RecommendationResult.id).where(
                RecommendationResult.recommendation_run_id.in_(run_ids),
            )
        ).scalars()
    ]


def _count_by_run_ids(
    session: Session,
    model: type[
        RecommendationRunConstraint
        | RecommendationRunConcern
        | SearchCandidate
    ],
    run_ids: list[int],
) -> int:
    if not run_ids:
        return 0
    return len(
        session.execute(
            select(model.id).where(model.recommendation_run_id.in_(run_ids))
        )
        .scalars()
        .all()
    )


def _count_score_evidence(session: Session, result_ids: list[int]) -> int:
    if not result_ids:
        return 0
    return len(
        session.execute(
            select(RecommendationScoreEvidence.id).where(
                RecommendationScoreEvidence.recommendation_result_id.in_(result_ids),
            )
        )
        .scalars()
        .all()
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _build_request_context(intent: RecommendationIntent) -> dict:
    return {
        "purchase_conditions": _purchase_conditions_to_dict(intent.purchase_conditions),
        "search_terms": list(intent.search_terms),
        "semantic_query_text": intent.semantic_query_text,
    }


def _build_parser_result(intent: RecommendationIntent) -> dict:
    return {
        "normalized_text": intent.normalized_text,
        "concerns": [_parsed_concern_to_dict(concern) for concern in intent.concerns],
        "effects": [_parsed_effect_to_dict(effect) for effect in intent.effects],
        "excluded_concerns": [
            _parsed_excluded_concern_to_dict(concern)
            for concern in intent.excluded_concerns
        ],
        "priority_effects": [_parsed_effect_to_dict(effect) for effect in intent.priority_effects],
        "unmatched_terms": list(intent.unmatched_terms),
        "needs_llm": intent.needs_llm,
    }


def _purchase_conditions_to_dict(purchase_conditions: ParsedPurchaseConditions) -> dict:
    return {
        "categories": [
            _matched_category_to_dict(category)
            for category in purchase_conditions.categories
        ],
        "brands": [
            _matched_brand_to_dict(brand)
            for brand in purchase_conditions.brands
        ],
        "price_min": purchase_conditions.price_min,
        "price_max": purchase_conditions.price_max,
        "price_text": purchase_conditions.price_text,
        "price_max_text": purchase_conditions.price_max_text,
    }


def _build_constraints(
    session: Session,
    recommendation_run_id: int,
    purchase_conditions: ParsedPurchaseConditions,
) -> list[RecommendationRunConstraint]:
    brand_ids_by_code = _load_brand_ids_by_code(
        session,
        [brand.brand_code for brand in purchase_conditions.brands],
    )
    category_ids_by_code = _load_category_ids_by_code(
        session,
        [category.category_code for category in purchase_conditions.categories],
    )

    constraints: list[RecommendationRunConstraint] = []
    for category in purchase_conditions.categories:
        constraints.append(
            RecommendationRunConstraint(
                recommendation_run_id=recommendation_run_id,
                constraint_type="category",
                operator="eq",
                raw_text=category.matched_text,
                normalized_value=category.category_code,
                category_id=category_ids_by_code.get(category.category_code),
                is_hard=True,
            )
        )

    for brand in purchase_conditions.brands:
        constraints.append(
            RecommendationRunConstraint(
                recommendation_run_id=recommendation_run_id,
                constraint_type="brand",
                operator="eq",
                raw_text=brand.matched_text,
                normalized_value=brand.brand_code,
                brand_id=brand_ids_by_code.get(brand.brand_code),
                is_hard=True,
            )
        )

    if purchase_conditions.price_min is not None:
        constraints.append(
            RecommendationRunConstraint(
                recommendation_run_id=recommendation_run_id,
                constraint_type="price_min",
                operator="gte",
                raw_text=purchase_conditions.price_text,
                normalized_value=str(purchase_conditions.price_min),
                numeric_value=Decimal(str(purchase_conditions.price_min)),
                is_hard=True,
            )
        )

    if purchase_conditions.price_max is not None:
        constraints.append(
            RecommendationRunConstraint(
                recommendation_run_id=recommendation_run_id,
                constraint_type="price_max",
                operator="lte",
                raw_text=purchase_conditions.price_max_text or purchase_conditions.price_text,
                normalized_value=str(purchase_conditions.price_max),
                numeric_value=Decimal(str(purchase_conditions.price_max)),
                is_hard=True,
            )
        )

    return constraints


def _build_concerns(
    session: Session,
    recommendation_run_id: int,
    parsed_concerns: tuple[ParsedConcern, ...],
) -> list[RecommendationRunConcern]:
    concern_ids_by_code = _load_concern_ids_by_code(
        session,
        [concern.tag_id for concern in parsed_concerns],
    )

    concerns: list[RecommendationRunConcern] = []
    for parsed_concern in parsed_concerns:
        concern_id = concern_ids_by_code.get(parsed_concern.tag_id)
        if concern_id is None:
            continue
        concerns.append(
            RecommendationRunConcern(
                recommendation_run_id=recommendation_run_id,
                concern_id=concern_id,
                matched_text=parsed_concern.matched_text,
                confidence=_confidence_to_decimal(parsed_concern.confidence),
            )
        )
    return concerns


def _load_brand_ids_by_code(session: Session, brand_codes: list[str]) -> dict[str, int]:
    if not brand_codes:
        return {}

    rows = session.execute(
        select(Brand).where(Brand.brand_code.in_(brand_codes))
    ).scalars()
    return {row.brand_code: row.id for row in rows}


def _load_category_ids_by_code(session: Session, category_codes: list[str]) -> dict[str, int]:
    if not category_codes:
        return {}

    rows = session.execute(
        select(ProductCategory).where(ProductCategory.category_code.in_(category_codes))
    ).scalars()
    return {row.category_code: row.id for row in rows}


def _load_concern_ids_by_code(session: Session, concern_codes: list[str]) -> dict[str, int]:
    if not concern_codes:
        return {}

    rows = session.execute(
        select(Concern).where(Concern.concern_code.in_(concern_codes))
    ).scalars()
    return {row.concern_code: row.id for row in rows}


def _matched_category_to_dict(category: MatchedCategory) -> dict:
    return {
        "category_code": category.category_code,
        "name": category.name,
        "matched_text": category.matched_text,
    }


def _matched_brand_to_dict(brand: MatchedBrand) -> dict:
    return {
        "brand_code": brand.brand_code,
        "name": brand.name,
        "matched_text": brand.matched_text,
    }


def _parsed_concern_to_dict(concern: ParsedConcern) -> dict:
    return {
        "tag_id": concern.tag_id,
        "name": concern.name,
        "matched_text": concern.matched_text,
        "confidence": concern.confidence,
    }


def _parsed_excluded_concern_to_dict(concern: ParsedExcludedConcern) -> dict:
    return {
        "tag_id": concern.tag_id,
        "name": concern.name,
        "matched_text": concern.matched_text,
        "reason": concern.reason,
    }


def _parsed_effect_to_dict(effect: ParsedEffect) -> dict:
    return {
        "effect_id": effect.effect_id,
        "name": effect.name,
        "weight": effect.weight,
    }


def _normalize_avoid_ingredients(avoid_ingredients: list[str] | None) -> list[str]:
    if avoid_ingredients is None:
        return []
    return [
        ingredient.strip()
        for ingredient in avoid_ingredients
        if ingredient and ingredient.strip()
    ]


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _confidence_to_decimal(confidence: float) -> Decimal:
    return Decimal(str(confidence)).quantize(CONFIDENCE_QUANTIZE)
