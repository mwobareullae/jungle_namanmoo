import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductPrice
from app.db.models.recommendation import (
    RecommendationResult,
    RecommendationRun,
    RecommendationScoreEvidence,
)
from app.db.models.taxonomy import Effect, Ingredient, IngredientEvidence
from app.schemas.common import ApiError
from app.schemas.recommendation import (
    CartHandoff,
    MatchedBrandConstraint,
    MatchedCategoryConstraint,
    Pagination,
    PurchaseConstraints,
    RecommendedProduct,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSummary,
    ScoreBreakdown,
)
from app.services.candidate_pool import CandidatePool, generate_candidate_pool
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.concern_llm_parser import get_default_concern_llm_parser
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_result_store import save_recommendation_results
from app.services.recommendation_run_store import (
    ensure_recommendation_run_active,
    save_recommendation_run,
)
from app.services.scoring import (
    SCORING_VERSION,
    load_behavior_personalization_context,
    load_skin_test_scoring_context,
    score_candidates,
)
from app.services.search_candidate_store import save_search_candidates
from app.services.search_matching import (
    SearchNoResultDiagnostics,
    build_search_no_result_diagnostics,
    count_join_product_search_documents,
    match_product_search_documents,
)
from app.services.skin_profile_service import load_skin_profile_for_user


DEFAULT_RESULT_LIMIT = 50
DEFAULT_CANDIDATE_POOL_LIMIT = settings.recommendation_candidate_pool_limit
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50
ALLOWED_SKIN_TYPES = {"건성", "지성", "복합성", "중성", "수부지"}
ALLOWED_SENSITIVITIES = {"낮음", "보통", "높음"}
SENSITIVITY_ALIASES = {
    "low": "낮음",
    "normal": "보통",
    "mid": "보통",
    "medium": "보통",
    "high": "높음",
    "sensitive": "높음",
    "민감": "높음",
    "민감성": "높음",
    "예민": "높음",
    "예민함": "높음",
}
DEFAULT_SKIN_TYPE = "중성"
DEFAULT_SENSITIVITY = "보통"
SENSITIVE_INTENT_PATTERN = re.compile(r"(?:민감(?:성|한|하고|해서|해)?|예민(?:함|한|하고|해서|해)?)")


@dataclass(frozen=True)
class NormalizedRecommendationRequest:
    concern_text: str
    skin_type: str
    sensitivity: str
    avoid_ingredients: list[str]
    manual_skin_type_explicit: bool
    manual_sensitivity_explicit: bool


@dataclass(frozen=True)
class NormalizedPagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True)
class _ResultRow:
    result: RecommendationResult
    product: Product
    brand: Brand
    lowest_price: int
    thumbnail_storage_key: str


@dataclass(frozen=True)
class _ResultEvidence:
    ingredient_name: str
    effect_name: str
    evidence_level: str | None


def create_recommendation_response(
    session: Session,
    request: RecommendationRequest,
    *,
    current_user: User | None = None,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    candidate_pool_limit: int = DEFAULT_CANDIDATE_POOL_LIMIT,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    commit: bool = True,
) -> RecommendationResponse:
    total_started_at = current_time()
    stage_durations: dict[str, float] = {}
    pagination = normalize_pagination(page, page_size)
    saved_skin_profile = (
        load_skin_profile_for_user(session, current_user.id)
        if current_user is not None
        else None
    )
    normalized_request = normalize_recommendation_request(
        request,
        saved_skin_profile=saved_skin_profile,
    )
    skin_test_context = load_skin_test_scoring_context(
        session,
        current_user.id if current_user is not None else None,
    )
    behavior_personalization_context = load_behavior_personalization_context(
        session,
        current_user.id if current_user is not None else None,
    )
    llm_parser = get_default_concern_llm_parser() if settings.openai_api_key else None

    stage_started_at = current_time()
    intent = build_recommendation_intent(
        normalized_request.concern_text,
        llm_parser=llm_parser,
    )
    _record_stage_duration(stage_durations, "intent_parse_ms", stage_started_at)

    try:
        stage_started_at = current_time()
        saved_run = save_recommendation_run(
            session,
            intent,
            skin_type=normalized_request.skin_type,
            sensitivity=normalized_request.sensitivity,
            avoid_ingredients=normalized_request.avoid_ingredients,
            scoring_version=SCORING_VERSION,
        )
        _record_stage_duration(stage_durations, "run_save_ms", stage_started_at)

        requested_candidate_pool_limit = max(candidate_pool_limit, result_limit)
        stage_started_at = current_time()
        candidate_pool = generate_candidate_pool(
            session,
            intent,
            skin_type=normalized_request.skin_type,
            sensitivity=normalized_request.sensitivity,
            avoid_ingredients=normalized_request.avoid_ingredients,
            target_pool_size=requested_candidate_pool_limit,
        )
        _record_stage_duration(stage_durations, "candidate_pool_ms", stage_started_at)
        candidates = candidate_pool.candidates
        stage_started_at = current_time()
        search_join_document_count = count_join_product_search_documents(
            session,
            [candidate.db_product_id for candidate in candidates],
        )
        matches = match_product_search_documents(session, intent, candidates)
        search_no_result_diagnostics = build_search_no_result_diagnostics(
            intent,
            candidates,
            matches,
            join_document_count=search_join_document_count,
        )
        _record_stage_duration(stage_durations, "search_match_ms", stage_started_at)

        stage_started_at = current_time()
        save_search_candidates(session, saved_run.run.id, candidates, matches)
        _record_stage_duration(stage_durations, "search_candidate_save_ms", stage_started_at)

        stage_started_at = current_time()
        scored_candidates = score_candidates(
            session,
            intent,
            candidates,
            matches,
            skin_type=normalized_request.skin_type,
            sensitivity=normalized_request.sensitivity,
            skin_test_context=skin_test_context,
            behavior_personalization_context=behavior_personalization_context,
            manual_skin_type_explicit=normalized_request.manual_skin_type_explicit,
            manual_sensitivity_explicit=normalized_request.manual_sensitivity_explicit,
        )
        _record_stage_duration(stage_durations, "scoring_ms", stage_started_at)

        scored_products = scored_candidates[:result_limit]
        _attach_candidate_pool_diagnostics(
            saved_run.run,
            candidate_pool=candidate_pool,
            result_limit=result_limit,
            search_join_document_count=search_join_document_count,
            search_match_count=len(matches),
            search_no_result_diagnostics=search_no_result_diagnostics,
            scored_candidate_count=len(scored_candidates),
            final_result_count=len(scored_products),
        )
        stage_started_at = current_time()
        save_recommendation_results(
            session,
            saved_run.run.id,
            scored_products,
            result_limit=result_limit,
        )
        _record_stage_duration(stage_durations, "result_save_ms", stage_started_at)

        recommendation_code = saved_run.run.recommendation_code
        stage_started_at = current_time()
        if commit:
            session.commit()
        else:
            session.flush()
        _record_stage_duration(stage_durations, "commit_ms", stage_started_at)

        stage_started_at = current_time()
        response = get_recommendation_response(
            session,
            recommendation_code,
            page=pagination.page,
            page_size=pagination.page_size,
        )
        _record_stage_duration(stage_durations, "response_load_ms", stage_started_at)
        log_performance_event(
            "recommendation_pipeline_completed",
            duration_ms=elapsed_ms(total_started_at),
            metadata={
                **stage_durations,
                "recommendation_id": recommendation_code,
                "llm_available": llm_parser is not None,
                "llm_used": intent.llm_used,
                "candidate_pool_limit": requested_candidate_pool_limit,
                "result_limit": result_limit,
                "page": pagination.page,
                "page_size": pagination.page_size,
                "candidate_pool_candidate_count": len(candidates),
                "candidate_pool_source_counts": candidate_pool.source_counts,
                "search_join_document_count": search_join_document_count,
                "search_match_count": len(matches),
                "positive_search_match_count": search_no_result_diagnostics.positive_search_match_count,
                "no_result_reason": search_no_result_diagnostics.no_result_reason,
                "scored_candidate_count": len(scored_candidates),
                "final_result_count": len(scored_products),
                "returned_product_count": len(response.products),
                "total_items": response.pagination.total_items,
                "matched_concern_count": len(intent.concerns),
                "expected_effect_count": len(intent.effects),
                "unmatched_term_count": len(intent.unmatched_terms),
                "avoid_ingredient_count": len(normalized_request.avoid_ingredients),
                "skin_test_context_applied": skin_test_context is not None,
                "behavior_personalization_applied": behavior_personalization_context is not None,
            },
        )
        return response
    except Exception as exc:
        session.rollback()
        log_performance_event(
            "recommendation_pipeline_failed",
            duration_ms=elapsed_ms(total_started_at),
            metadata={
                **stage_durations,
                "llm_available": llm_parser is not None,
                "llm_used": intent.llm_used,
                "result_limit": result_limit,
                "page": pagination.page,
                "page_size": pagination.page_size,
                "error": type(exc).__name__,
            },
        )
        raise


def get_recommendation_response(
    session: Session,
    recommendation_id: str,
    *,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> RecommendationResponse:
    pagination = normalize_pagination(page, page_size)
    run = load_recommendation_run(session, recommendation_id)
    total_items = _count_result_rows(session, run.id)
    result_rows = _load_result_rows(
        session,
        run.id,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    evidence_by_result_id = _load_result_evidence(session, [row.result.id for row in result_rows])

    return RecommendationResponse(
        recommendation_id=run.recommendation_code,
        summary=_build_summary_from_run(run),
        unmatched_terms=_run_unmatched_terms(run),
        products=[
            _result_row_to_recommended_product(
                row,
                evidence_by_result_id.get(row.result.id, ()),
                recommendation_id=run.recommendation_code,
            )
            for row in result_rows
        ],
        pagination=_build_pagination(
            page=pagination.page,
            page_size=pagination.page_size,
            total_items=total_items,
        ),
    )


def _record_stage_duration(
    stage_durations: dict[str, float],
    key: str,
    started_at: float,
) -> None:
    stage_durations[key] = round(elapsed_ms(started_at), 2)


def normalize_recommendation_request(
    request: RecommendationRequest,
    *,
    saved_skin_profile: Any | None = None,
) -> NormalizedRecommendationRequest:
    concern_text = (request.concern_text or "").strip()
    if not concern_text:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 필수입니다.")
    if len(concern_text) > 100:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 100자 이하로 입력해 주세요.")

    request_skin_type = _normalize_skin_type_or_none(request.skin_type)
    saved_skin_type = _manual_skin_type_from_profile(saved_skin_profile)
    skin_type = request_skin_type or saved_skin_type or DEFAULT_SKIN_TYPE

    request_sensitivity = _normalize_sensitivity_or_none(request.sensitivity)
    saved_sensitivity = _manual_sensitivity_from_profile(saved_skin_profile)
    if request_sensitivity is not None:
        sensitivity = request_sensitivity
        manual_sensitivity_explicit = True
    elif _has_sensitive_intent(concern_text):
        sensitivity = "높음"
        manual_sensitivity_explicit = False
    elif saved_sensitivity is not None:
        sensitivity = saved_sensitivity
        manual_sensitivity_explicit = True
    else:
        sensitivity = DEFAULT_SENSITIVITY
        manual_sensitivity_explicit = False

    request_avoid_ingredients = _normalize_avoid_ingredients(request.avoid_ingredients)
    saved_avoid_ingredients = _normalize_avoid_ingredients(
        getattr(saved_skin_profile, "avoid_ingredients", None),
    )

    return NormalizedRecommendationRequest(
        concern_text=concern_text,
        skin_type=skin_type,
        sensitivity=sensitivity,
        avoid_ingredients=_dedupe([*request_avoid_ingredients, *saved_avoid_ingredients]),
        manual_skin_type_explicit=request_skin_type is not None or saved_skin_type is not None,
        manual_sensitivity_explicit=manual_sensitivity_explicit,
    )


def normalize_pagination(page: int, page_size: int) -> NormalizedPagination:
    if page < 1:
        raise ApiError(400, "INVALID_INPUT", "page는 1 이상이어야 합니다.")
    if page_size < 1:
        raise ApiError(400, "INVALID_INPUT", "page_size는 1 이상이어야 합니다.")
    if page_size > MAX_PAGE_SIZE:
        raise ApiError(400, "INVALID_INPUT", f"page_size는 {MAX_PAGE_SIZE} 이하여야 합니다.")
    return NormalizedPagination(page=page, page_size=page_size)


def load_recommendation_run(session: Session, recommendation_id: str) -> RecommendationRun:
    run = session.execute(
        select(RecommendationRun).where(
            RecommendationRun.recommendation_code == recommendation_id,
        )
    ).scalar_one_or_none()
    if run is None:
        raise ApiError(404, "NOT_FOUND", "추천 결과를 찾을 수 없습니다.")
    ensure_recommendation_run_active(run)
    return run


def _count_result_rows(session: Session, recommendation_run_id: int) -> int:
    return int(
        session.execute(
            select(func.count(RecommendationResult.id)).where(
                RecommendationResult.recommendation_run_id == recommendation_run_id,
            )
        ).scalar_one()
    )


def _load_result_rows(
    session: Session,
    recommendation_run_id: int,
    *,
    offset: int,
    limit: int,
) -> list[_ResultRow]:
    lowest_prices = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )

    rows = session.execute(
        select(
            RecommendationResult,
            Product,
            Brand,
            lowest_prices.c.lowest_price,
        )
        .join(Product, RecommendationResult.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .outerjoin(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(RecommendationResult.recommendation_run_id == recommendation_run_id)
        .order_by(RecommendationResult.rank_order.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    thumbnail_storage_keys = load_thumbnail_storage_keys(
        session,
        [int(product.id) for _, product, _, _ in rows],
    )

    return [
        _ResultRow(
            result=result,
            product=product,
            brand=brand,
            lowest_price=int(lowest_price or 0),
            thumbnail_storage_key=thumbnail_storage_keys.get(int(product.id), ""),
        )
        for result, product, brand, lowest_price in rows
    ]


def _build_pagination(*, page: int, page_size: int, total_items: int) -> Pagination:
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return Pagination(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1 and total_items > 0,
    )


def _load_result_evidence(
    session: Session,
    recommendation_result_ids: list[int],
) -> dict[int, tuple[_ResultEvidence, ...]]:
    if not recommendation_result_ids:
        return {}

    rows = session.execute(
        select(
            RecommendationScoreEvidence.recommendation_result_id,
            Ingredient.name_ko,
            Effect.name,
            IngredientEvidence.evidence_level,
        )
        .outerjoin(Ingredient, RecommendationScoreEvidence.ingredient_id == Ingredient.id)
        .outerjoin(Effect, RecommendationScoreEvidence.effect_id == Effect.id)
        .outerjoin(
            IngredientEvidence,
            RecommendationScoreEvidence.evidence_id == IngredientEvidence.id,
        )
        .where(
            RecommendationScoreEvidence.recommendation_result_id.in_(
                recommendation_result_ids,
            )
        )
        .order_by(
            RecommendationScoreEvidence.recommendation_result_id.asc(),
            RecommendationScoreEvidence.id.asc(),
        )
    ).all()

    grouped: dict[int, list[_ResultEvidence]] = {}
    for result_id, ingredient_name, effect_name, evidence_level in rows:
        if not ingredient_name and not effect_name:
            continue
        grouped.setdefault(int(result_id), []).append(
            _ResultEvidence(
                ingredient_name=ingredient_name or "",
                effect_name=effect_name or "근거",
                evidence_level=evidence_level,
            )
        )

    return {result_id: tuple(evidence) for result_id, evidence in grouped.items()}


def _result_row_to_recommended_product(
    row: _ResultRow,
    evidence: tuple[_ResultEvidence, ...],
    *,
    recommendation_id: str,
) -> RecommendedProduct:
    product_id = row.product.product_code
    rank = row.result.rank_order
    return RecommendedProduct(
        product_id=product_id,
        rank=rank,
        total_score=_score_to_int(row.result.total_score),
        reason_summary=row.result.reason_summary or "조건에 맞는 상품을 추천 후보로 선정했습니다.",
        brand=row.brand.name,
        name=row.product.product_name,
        thumbnail_url=row.thumbnail_storage_key,
        lowest_price=row.lowest_price,
        evidence_tags=_evidence_tags(evidence),
        key_ingredients=_key_ingredients(evidence),
        score_breakdown=score_breakdown_to_api(row.result.score_breakdown),
        cart_handoff=CartHandoff(
            product_id=product_id,
            recommendation_id=recommendation_id,
            recommendation_rank=rank,
        ),
    )


def _build_summary_from_run(run: RecommendationRun) -> RecommendationSummary:
    return RecommendationSummary(
        concern_text=run.concern_text,
        skin_type=run.skin_type,
        sensitivity=run.sensitivity,
        avoid_ingredients=list(run.avoid_ingredients or []),
        matched_concerns=[
            str(concern.get("name"))
            for concern in _parser_items(run, "concerns")
            if concern.get("name")
        ],
        expected_effects=[
            str(effect.get("name"))
            for effect in _parser_items(run, "effects")
            if effect.get("name")
        ],
        purchase_constraints=_purchase_constraints_from_context(run.request_context or {}),
    )


def _parser_items(run: RecommendationRun, key: str) -> list[dict[str, Any]]:
    parser_result = run.parser_result or {}
    items = parser_result.get(key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _run_unmatched_terms(run: RecommendationRun) -> list[str]:
    parser_result = run.parser_result or {}
    unmatched_terms = parser_result.get("unmatched_terms", [])
    if not isinstance(unmatched_terms, list):
        return []
    return [str(term) for term in unmatched_terms if str(term).strip()]


def _purchase_constraints_from_context(request_context: dict) -> PurchaseConstraints:
    purchase_conditions = request_context.get("purchase_conditions", {})
    if not isinstance(purchase_conditions, dict):
        purchase_conditions = {}

    return PurchaseConstraints(
        categories=[
            MatchedCategoryConstraint(
                category_code=str(category.get("category_code", "")),
                name=str(category.get("name", "")),
                matched_text=str(category.get("matched_text", "")),
            )
            for category in _dict_items(purchase_conditions.get("categories"))
        ],
        brands=[
            MatchedBrandConstraint(
                brand_code=str(brand.get("brand_code", "")),
                name=str(brand.get("name", "")),
                matched_text=str(brand.get("matched_text", "")),
            )
            for brand in _dict_items(purchase_conditions.get("brands"))
        ],
        price_min=_optional_int(purchase_conditions.get("price_min")),
        price_max=_optional_int(purchase_conditions.get("price_max")),
        price_text=_optional_str(purchase_conditions.get("price_text")),
        price_max_text=_optional_str(purchase_conditions.get("price_max_text")),
    )


def _attach_candidate_pool_diagnostics(
    run: RecommendationRun,
    *,
    candidate_pool: CandidatePool,
    result_limit: int,
    search_join_document_count: int,
    search_match_count: int,
    search_no_result_diagnostics: SearchNoResultDiagnostics,
    scored_candidate_count: int,
    final_result_count: int,
) -> None:
    request_context = dict(run.request_context or {})
    diagnostics = candidate_pool.to_diagnostics()
    diagnostics.update(
        {
            "result_limit": result_limit,
            "join_document_count": search_join_document_count,
            "search_match_count": search_match_count,
            "scored_candidate_count": scored_candidate_count,
            "final_result_count": final_result_count,
        }
    )
    request_context["candidate_pool_diagnostics"] = diagnostics
    request_context["search_no_result_diagnostics"] = search_no_result_diagnostics.to_dict()
    run.request_context = request_context


def score_breakdown_to_api(score_breakdown: dict | None) -> ScoreBreakdown:
    raw = score_breakdown or {}
    skin_score = raw.get("skin_profile_score", raw.get("skin_type_score", 0))
    return ScoreBreakdown(
        ingredient_effect_score=_component_to_percent(raw.get("ingredient_effect_score")),
        ingredient_evidence_score=_component_to_percent(raw.get("ingredient_evidence_score")),
        functional_claim_score=_component_to_percent(raw.get("functional_claim_score")),
        concentration_fit_score=_component_to_percent(raw.get("concentration_fit_score", 0.5)),
        concentration_bucket=_optional_str(raw.get("concentration_bucket")),
        concentration_warning=_optional_str(raw.get("concentration_warning")),
        skin_profile_score=_component_to_percent(raw.get("skin_profile_score")),
        skin_type_score=_component_to_percent(skin_score),
        sensitivity_score=_component_to_percent(raw.get("sensitivity_score")),
        price_score=_component_to_percent(raw.get("price_score")),
        keyword_score=_component_to_percent(raw.get("keyword_score")),
        vector_score=_component_to_percent(raw.get("vector_score")),
        search_match_score=_component_to_percent(raw.get("search_match_score")),
        market_signal_score=_component_to_percent(raw.get("market_signal_score", 0.5)),
        skin_test_context_score=_component_to_percent(raw.get("skin_test_context_score", 0.5)),
        skin_test_context_applied=raw.get("skin_test_context_applied") is True,
        skin_test_context_axes=_component_percent_dict(raw.get("skin_test_context_axes")),
        skin_test_context_matched_axes=_string_list(raw.get("skin_test_context_matched_axes")),
        skin_test_context_query_conflict_axes=_string_list(raw.get("skin_test_context_query_conflict_axes")),
        skin_test_context_manual_conflict_axes=_string_list(raw.get("skin_test_context_manual_conflict_axes")),
        behavior_personalization_score=_component_to_percent(raw.get("behavior_personalization_score")),
        behavior_personalization_applied=raw.get("behavior_personalization_applied") is True,
        behavior_personalization_sources=_string_list(raw.get("behavior_personalization_sources")),
        behavior_personalization_source_scores=_component_percent_dict(
            raw.get("behavior_personalization_source_scores")
        ),
        behavior_personalization_affinity_components=_component_percent_dict(
            raw.get("behavior_personalization_affinity_components")
        ),
        behavior_personalization_negative_guard_score=_component_to_percent(
            raw.get("behavior_personalization_negative_guard_score", 1.0)
        ),
        behavior_personalization_event_counts=_int_dict(raw.get("behavior_personalization_event_counts")),
        base_weights=_float_dict(raw.get("base_weights")),
        adjusted_weights=_float_dict(raw.get("weights")),
        applied_multipliers=_float_dict(raw.get("applied_multipliers")),
        risk_penalty=_score_to_int(raw.get("risk_penalty", 0)),
        risk_flag_count=_optional_int(raw.get("risk_flag_count")) or 0,
        risk_warnings=_string_list(raw.get("risk_warnings")),
        risk_policy=_optional_str(raw.get("risk_policy")),
    )


def _component_to_percent(value: object) -> int:
    number = _to_float(value)
    if 0 <= number <= 1:
        number *= 100
    return _score_to_int(number)


def _score_to_int(value: object) -> int:
    return int(round(max(0.0, min(100.0, _to_float(value)))))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _component_percent_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _component_to_percent(item)
        for key, item in value.items()
        if str(key).strip()
    }


def _float_dict(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): round(_to_float(item), 6)
        for key, item in value.items()
        if str(key).strip()
    }


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): max(0, int(_to_float(item)))
        for key, item in value.items()
        if str(key).strip()
    }


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _evidence_tags(evidence: tuple[_ResultEvidence, ...]) -> list[str]:
    tags = [
        f"{item.effect_name}:{item.evidence_level or '근거확인'}"
        for item in evidence
        if item.effect_name
    ]
    return _dedupe(tags) or ["조건 매칭"]


def _key_ingredients(evidence: tuple[_ResultEvidence, ...]) -> list[str]:
    return _dedupe([item.ingredient_name for item in evidence if item.ingredient_name])


def _normalize_choice(
    value: str | None,
    default: str,
    allowed_values: set[str],
    error_message: str,
) -> str:
    if value is None or not value.strip():
        return default

    normalized = value.strip()
    if normalized not in allowed_values:
        raise ApiError(400, "INVALID_INPUT", error_message)
    return normalized


def _normalize_skin_type_or_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if normalized not in ALLOWED_SKIN_TYPES:
        raise ApiError(400, "INVALID_INPUT", "피부 타입 값이 올바르지 않습니다.")
    return normalized


def _normalize_sensitivity_or_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    normalized = SENSITIVITY_ALIASES.get(stripped.casefold().replace(" ", ""), stripped)
    if normalized not in ALLOWED_SENSITIVITIES:
        raise ApiError(400, "INVALID_INPUT", "민감도 값이 올바르지 않습니다.")
    return normalized


def _manual_skin_type_from_profile(profile: Any | None) -> str | None:
    if profile is None:
        return None
    explicit_skin_type = _normalize_skin_type_or_none(getattr(profile, "explicit_skin_type", None))
    if explicit_skin_type is not None:
        return explicit_skin_type
    if getattr(profile, "skin_type_source", None) == "manual":
        return _normalize_skin_type_or_none(getattr(profile, "skin_type", None))
    return None


def _manual_sensitivity_from_profile(profile: Any | None) -> str | None:
    if profile is None:
        return None
    explicit_sensitivity = _normalize_sensitivity_or_none(getattr(profile, "explicit_sensitivity", None))
    if explicit_sensitivity is not None:
        return explicit_sensitivity
    if getattr(profile, "sensitivity_source", None) == "manual":
        return _normalize_sensitivity_or_none(getattr(profile, "sensitivity", None))
    return None


def _normalize_sensitivity(value: str | None, concern_text: str) -> str:
    normalized = _normalize_sensitivity_or_none(value)
    if normalized is not None:
        return normalized
    if _has_sensitive_intent(concern_text):
        return "높음"
    return DEFAULT_SENSITIVITY


def _has_sensitive_intent(concern_text: str) -> bool:
    return SENSITIVE_INTENT_PATTERN.search(concern_text.strip().lower()) is not None


def _normalize_avoid_ingredients(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    return [ingredient.strip() for ingredient in value if ingredient and ingredient.strip()]


def _dict_items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped
