from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.catalog import Brand, Product, ProductIngredient, ProductPrice
from app.db.models.recommendation import (
    RecommendationResult,
    RecommendationRun,
    RecommendationScoreEvidence,
)
from app.db.models.taxonomy import Effect, Ingredient, IngredientEvidence
from app.schemas.common import ApiError
from app.schemas.recommendation import (
    MatchedBrandConstraint,
    MatchedCategoryConstraint,
    PurchaseConstraints,
    RecommendedProduct,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSummary,
    ScoreBreakdown,
)
from app.services.product_candidates import ProductCandidate, list_product_candidates
from app.services.concern_llm_parser import get_default_concern_llm_parser
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_result_store import save_recommendation_results
from app.services.recommendation_run_store import (
    ensure_recommendation_run_active,
    save_recommendation_run,
)
from app.services.scoring import SCORING_VERSION, score_candidates
from app.services.search_candidate_store import save_search_candidates
from app.services.search_matching import match_product_search_documents


DEFAULT_RESULT_LIMIT = 50
DEFAULT_CANDIDATE_POOL_LIMIT = settings.recommendation_candidate_pool_limit
ALLOWED_SKIN_TYPES = {"건성", "지성", "복합성", "중성", "수부지"}
ALLOWED_SENSITIVITIES = {"낮음", "보통", "높음", "민감"}
DEFAULT_SKIN_TYPE = "중성"
DEFAULT_SENSITIVITY = "보통"


@dataclass(frozen=True)
class NormalizedRecommendationRequest:
    concern_text: str
    skin_type: str
    sensitivity: str
    avoid_ingredients: list[str]


@dataclass(frozen=True)
class _ResultRow:
    result: RecommendationResult
    product: Product
    brand: Brand
    lowest_price: int


@dataclass(frozen=True)
class _ResultEvidence:
    ingredient_name: str
    effect_name: str
    evidence_level: str | None


def create_recommendation_response(
    session: Session,
    request: RecommendationRequest,
    *,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    candidate_pool_limit: int = DEFAULT_CANDIDATE_POOL_LIMIT,
    commit: bool = True,
) -> RecommendationResponse:
    normalized_request = normalize_recommendation_request(request)
    llm_parser = get_default_concern_llm_parser() if settings.openai_api_key else None
    intent = build_recommendation_intent(
        normalized_request.concern_text,
        llm_parser=llm_parser,
    )

    try:
        saved_run = save_recommendation_run(
            session,
            intent,
            skin_type=normalized_request.skin_type,
            sensitivity=normalized_request.sensitivity,
            avoid_ingredients=normalized_request.avoid_ingredients,
            scoring_version=SCORING_VERSION,
        )
        candidates = list_product_candidates(
            session,
            intent.purchase_conditions,
            limit=max(candidate_pool_limit, result_limit),
        )
        candidates = _filter_avoided_ingredients(
            session,
            candidates,
            normalized_request.avoid_ingredients,
        )
        matches = match_product_search_documents(session, intent, candidates)
        save_search_candidates(session, saved_run.run.id, candidates, matches)

        scored_products = score_candidates(
            session,
            intent,
            candidates,
            matches,
            skin_type=normalized_request.skin_type,
            sensitivity=normalized_request.sensitivity,
        )
        scored_products = scored_products[:result_limit]
        save_recommendation_results(
            session,
            saved_run.run.id,
            scored_products,
            result_limit=result_limit,
        )
        recommendation_code = saved_run.run.recommendation_code
        if commit:
            session.commit()
        else:
            session.flush()
        return get_recommendation_response(session, recommendation_code)
    except Exception:
        session.rollback()
        raise


def get_recommendation_response(
    session: Session,
    recommendation_id: str,
) -> RecommendationResponse:
    run = load_recommendation_run(session, recommendation_id)
    result_rows = _load_result_rows(session, run.id)
    evidence_by_result_id = _load_result_evidence(session, [row.result.id for row in result_rows])

    return RecommendationResponse(
        recommendation_id=run.recommendation_code,
        summary=_build_summary_from_run(run),
        unmatched_terms=_run_unmatched_terms(run),
        products=[
            _result_row_to_recommended_product(
                row,
                evidence_by_result_id.get(row.result.id, ()),
            )
            for row in result_rows
        ],
    )


def normalize_recommendation_request(
    request: RecommendationRequest,
) -> NormalizedRecommendationRequest:
    concern_text = (request.concern_text or "").strip()
    if not concern_text:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 필수입니다.")
    if len(concern_text) > 100:
        raise ApiError(400, "INVALID_INPUT", "고민 텍스트는 100자 이하로 입력해 주세요.")

    skin_type = _normalize_choice(
        request.skin_type,
        DEFAULT_SKIN_TYPE,
        ALLOWED_SKIN_TYPES,
        "피부 타입 값이 올바르지 않습니다.",
    )
    sensitivity = _normalize_choice(
        request.sensitivity,
        DEFAULT_SENSITIVITY,
        ALLOWED_SENSITIVITIES,
        "민감도 값이 올바르지 않습니다.",
    )

    return NormalizedRecommendationRequest(
        concern_text=concern_text,
        skin_type=skin_type,
        sensitivity=sensitivity,
        avoid_ingredients=_normalize_avoid_ingredients(request.avoid_ingredients),
    )


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


def _load_result_rows(session: Session, recommendation_run_id: int) -> list[_ResultRow]:
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
    ).all()

    return [
        _ResultRow(
            result=result,
            product=product,
            brand=brand,
            lowest_price=int(lowest_price or 0),
        )
        for result, product, brand, lowest_price in rows
    ]


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
) -> RecommendedProduct:
    return RecommendedProduct(
        product_id=row.product.product_code,
        rank=row.result.rank_order,
        total_score=_score_to_int(row.result.total_score),
        reason_summary=row.result.reason_summary or "조건에 맞는 상품을 추천 후보로 선정했습니다.",
        brand=row.brand.name,
        name=row.product.product_name,
        thumbnail_url=row.product.thumbnail_url or "",
        lowest_price=row.lowest_price,
        evidence_tags=_evidence_tags(evidence),
        key_ingredients=_key_ingredients(evidence),
        score_breakdown=score_breakdown_to_api(row.result.score_breakdown),
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


def score_breakdown_to_api(score_breakdown: dict | None) -> ScoreBreakdown:
    raw = score_breakdown or {}
    skin_score = raw.get("skin_profile_score", raw.get("skin_type_score", 0))
    return ScoreBreakdown(
        ingredient_effect_score=_component_to_percent(raw.get("ingredient_effect_score")),
        ingredient_evidence_score=_component_to_percent(raw.get("ingredient_evidence_score")),
        concentration_fit_score=_component_to_percent(raw.get("concentration_fit_score", 0.5)),
        concentration_bucket=_optional_str(raw.get("concentration_bucket")),
        concentration_warning=_optional_str(raw.get("concentration_warning")),
        skin_type_score=_component_to_percent(skin_score),
        price_score=_component_to_percent(raw.get("price_score")),
        keyword_score=_component_to_percent(raw.get("keyword_score")),
        vector_score=_component_to_percent(raw.get("vector_score")),
        search_match_score=_component_to_percent(raw.get("search_match_score")),
        risk_penalty=_score_to_int(raw.get("risk_penalty", 0)),
    )


def _component_to_percent(value: object) -> int:
    number = _to_float(value)
    if 0 <= number <= 1:
        number *= 100
    return _score_to_int(number)


def _score_to_int(value: object) -> int:
    return int(round(max(0.0, min(100.0, _to_float(value)))))


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


def _normalize_avoid_ingredients(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    return [ingredient.strip() for ingredient in value if ingredient and ingredient.strip()]


def _normalize_match_text(value: str) -> str:
    return "".join(value.casefold().split())


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
