from dataclasses import dataclass, replace
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.skin import SkinProfile, SkinTestResult
from app.db.models.taxonomy import (
    Effect,
    Ingredient,
    IngredientEffect,
    IngredientEffectRange,
    IngredientEvidence,
    RiskFlag,
)
from app.services.product_candidates import ProductCandidate
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent
from app.services.search_matching import SearchMatch


SCORING_VERSION = "v2_skin_test_context"
EFFECT_CAP = 1.2
TOP_INGREDIENT_DECAYS = (1.0, 0.5, 0.25)
PRIORITY_EFFECT_MULTIPLIER = 1.25
DEFAULT_PROFILE_SCORE = 0.5
FUNCTIONAL_CONFIRMED_STATUS = "FUNCTIONAL_CONFIRMED"
FUNCTIONAL_BASE_SCORE = 0.2
FUNCTIONAL_MATCH_SCORE = 0.75
FUNCTIONAL_PRIORITY_MATCH_SCORE = 1.0
FUNCTIONAL_CLAIM_EFFECT_CODES = {
    "미백": "effect_brightening",
    "주름개선": "effect_wrinkle",
}
CONFIDENCE_MULTIPLIERS = {
    "high": 1.0,
    "medium": 0.8,
    "med": 0.8,
    "low": 0.5,
    "unknown": 0.0,
    "not_applicable": 0.0,
    None: 0.0,
}
SENSITIVE_RISK_PENALTY_CAP = 8.0
MARKET_SIGNAL_WINDOW_DAYS = 7
SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS = {
    "OD": 0.20,
    "SR": 0.20,
    "CATEGORY_PREF": 0.12,
    "PN": 0.18,
    "WT": 0.18,
    "SENSITIVE_SAFETY": 0.12,
}
SKIN_TEST_AXIS_STRENGTH_MULTIPLIERS = {
    "strong": 1.0,
    "weak": 0.6,
}
WEIGHT_MULTIPLIER_CAPS = {
    "ingredient_effect": (0.95, 1.12),
    "ingredient_evidence": (0.95, 1.30),
    "concentration_fit": (0.95, 1.25),
    "functional_claim": (0.95, 1.30),
    "price": (0.60, 1.80),
    "market_signal": (1.00, 4.00),
}
SCORE_WEIGHT_FIELDS = (
    "ingredient_effect",
    "ingredient_evidence",
    "skin_profile",
    "concentration_fit",
    "functional_claim",
    "search_match",
    "price",
    "market_signal",
    "skin_test_context",
)
VALUE_ORIENTED_BUYING_CRITERIA = {"value"}
VALUE_ORIENTED_PRICE_INVESTMENTS = {"daily_repeat_value", "value_volume"}
PIGMENT_EFFECT_CODES = ("effect_brightening",)
WRINKLE_EFFECT_CODES = ("effect_wrinkle",)


@dataclass(frozen=True)
class ScoreWeights:
    ingredient_effect: float = 0.32
    ingredient_evidence: float = 0.23
    skin_profile: float = 0.14
    concentration_fit: float = 0.08
    functional_claim: float = 0.05
    search_match: float = 0.07
    price: float = 0.04
    market_signal: float = 0.02
    skin_test_context: float = 0.05


DEFAULT_SCORE_WEIGHTS = ScoreWeights()
SEARCH_INTENT_SCORE_WEIGHTS = ScoreWeights(
    ingredient_effect=0.29,
    ingredient_evidence=0.19,
    skin_profile=0.14,
    concentration_fit=0.08,
    functional_claim=0.05,
    search_match=0.15,
    price=0.04,
    market_signal=0.02,
    skin_test_context=0.05,
)


@dataclass(frozen=True)
class ScoreMultipliers:
    ingredient_effect: float = 1.0
    ingredient_evidence: float = 1.0
    skin_profile: float = 1.0
    concentration_fit: float = 1.0
    functional_claim: float = 1.0
    search_match: float = 1.0
    price: float = 1.0
    market_signal: float = 1.0
    skin_test_context: float = 1.0


@dataclass(frozen=True)
class ScoreWeightResolution:
    weights: ScoreWeights
    base_weights: ScoreWeights
    multipliers: ScoreMultipliers
    weight_profile: str
    search_intent_signals: tuple[str, ...]


@dataclass(frozen=True)
class SkinTestScoringContext:
    result_id: int
    type_code: str
    mapped_skin_type: str
    mapped_sensitivity: str
    axis_scores: dict
    commerce_profile: dict


@dataclass(frozen=True)
class ConcentrationScorePolicy:
    unknown: float = 0.50
    below_meaningful: float = 0.55
    meaningful: float = 0.75
    optimal: float = 1.00
    above_optimal: float = 0.80
    excessive: float = 0.60


@dataclass(frozen=True)
class SkinProfileWeights:
    skin_type: float = 0.60
    sensitivity: float = 0.40


@dataclass(frozen=True)
class ScoreEvidence:
    ingredient_id: int
    effect_id: int
    evidence_id: int | None
    ingredient_name: str
    effect_name: str
    evidence_level: str | None
    contribution_score: float
    reason: str


@dataclass(frozen=True)
class ScoredProduct:
    product_id: str
    db_product_id: int
    rank: int
    total_score: float
    reason_summary: str
    evidence_tags: tuple[str, ...]
    key_ingredients: tuple[str, ...]
    score_breakdown: dict
    score_evidence: tuple[ScoreEvidence, ...]


@dataclass(frozen=True)
class _DesiredEffect:
    effect_code: str
    name: str
    weight: float


@dataclass(frozen=True)
class _EvidenceInfo:
    evidence_id: int
    evidence_score: float
    evidence_level: str | None
    summary: str | None
    source_type: str | None
    pmid: str | None
    doi: str | None
    source_authority_score: float | None


@dataclass(frozen=True)
class _ConcentrationRangeInfo:
    meaningful_min: float
    optimal_min: float
    optimal_max: float
    excessive_min: float | None
    range_confidence: str
    source_type: str
    source_url: str | None
    note: str | None


@dataclass(frozen=True)
class _ConcentrationInfo:
    value: float | None
    unit: str | None
    text: str | None
    confidence: str | None
    range: _ConcentrationRangeInfo | None


@dataclass(frozen=True)
class _ConcentrationResult:
    bucket: str
    score: float
    ingredient_name: str | None = None
    effect_name: str | None = None
    concentration_text: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class _IngredientEffectInfo:
    product_db_id: int
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    effect_id: int
    effect_code: str
    effect_name: str
    effect_score: float
    display_order: int
    evidence: _EvidenceInfo | None
    concentration: _ConcentrationInfo


@dataclass(frozen=True)
class _SkinProfileInfo:
    dry_fit: float
    oily_fit: float
    combination_fit: float
    normal_fit: float
    dehydrated_oily_fit: float
    sensitive_fit: float
    sensitivity_tag: str | None
    confidence: str | None
    reason: str | None


@dataclass(frozen=True)
class _FunctionalInfo:
    status: str | None
    claims: tuple[str, ...]
    claim_confidence: str | None
    basis: str | None


@dataclass(frozen=True)
class _MarketSignalInfo:
    popularity_score: float
    review_count: int
    average_rating: float | None


@dataclass(frozen=True)
class _PriceScoreContext:
    min_price: int
    max_price: int


@dataclass(frozen=True)
class _SkinTestContextScore:
    score: float
    axis_scores: dict[str, float]
    matched_axes: tuple[str, ...]
    query_conflict_axes: tuple[str, ...]
    manual_conflict_axes: tuple[str, ...]


@dataclass(frozen=True)
class _EffectContribution:
    ingredient: _IngredientEffectInfo
    decay: float
    effect_component: float
    evidence_component: float


def load_skin_test_scoring_context(
    session: Session,
    user_id: int | None,
) -> SkinTestScoringContext | None:
    if user_id is None:
        return None

    profile = session.execute(
        select(SkinProfile).where(SkinProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None or profile.latest_skin_test_result_id is None:
        return None

    result = session.get(SkinTestResult, profile.latest_skin_test_result_id)
    if result is None:
        return None
    if result.user_id is not None and result.user_id != user_id:
        return None

    return SkinTestScoringContext(
        result_id=int(result.id),
        type_code=result.type_code,
        mapped_skin_type=result.mapped_skin_type,
        mapped_sensitivity=result.mapped_sensitivity,
        axis_scores=dict(result.axis_scores or {}),
        commerce_profile=dict(result.commerce_profile or {}),
    )


def score_candidates(
    session: Session,
    intent: RecommendationIntent,
    candidates: list[ProductCandidate],
    matches: list[SearchMatch],
    *,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    skin_test_context: SkinTestScoringContext | None = None,
    manual_skin_type_explicit: bool = False,
    manual_sensitivity_explicit: bool = False,
    weights: ScoreWeights = DEFAULT_SCORE_WEIGHTS,
    concentration_policy: ConcentrationScorePolicy = ConcentrationScorePolicy(),
    skin_profile_weights: SkinProfileWeights = SkinProfileWeights(),
) -> list[ScoredProduct]:
    if not candidates:
        return []

    desired_effects = _build_desired_effects(intent)
    priority_effect_codes = tuple(effect.effect_id for effect in intent.priority_effects)
    product_ids = [candidate.db_product_id for candidate in candidates]
    ingredients_by_product = _load_ingredient_effects(session, product_ids, desired_effects)
    functional_info_by_product = _load_functional_info(session, product_ids)
    skin_tags_by_product = _load_skin_tags(session, product_ids)
    skin_profiles_by_product = _load_skin_profiles(session, product_ids)
    risk_flags_by_product = _load_risk_flags(session, product_ids)
    market_signals_by_product = _load_market_signals(session, product_ids)
    price_context = _build_price_score_context(candidates)
    matches_by_product_code = {match.product_id: match for match in matches}
    weight_resolution = _resolve_score_weights(
        intent,
        weights,
        skin_test_context=skin_test_context,
    )

    scored_products = [
        _score_candidate(
            candidate,
            desired_effects,
            priority_effect_codes,
            ingredients_by_product.get(candidate.db_product_id, ()),
            functional_info_by_product.get(candidate.db_product_id),
            skin_tags_by_product.get(candidate.db_product_id, ()),
            skin_profiles_by_product.get(candidate.db_product_id),
            risk_flags_by_product.get(candidate.db_product_id, ()),
            market_signals_by_product.get(candidate.db_product_id),
            matches_by_product_code.get(candidate.product_id),
            intent.purchase_conditions,
            skin_type=skin_type,
            sensitivity=sensitivity,
            skin_test_context=skin_test_context,
            manual_skin_type_explicit=manual_skin_type_explicit,
            manual_sensitivity_explicit=manual_sensitivity_explicit,
            price_context=price_context,
            weight_resolution=weight_resolution,
            concentration_policy=concentration_policy,
            skin_profile_weights=skin_profile_weights,
        )
        for candidate in candidates
    ]

    ranked_products = sorted(
        scored_products,
        key=lambda product: (-product.total_score, product.rank),
    )

    return [
        ScoredProduct(
            product_id=product.product_id,
            db_product_id=product.db_product_id,
            rank=rank,
            total_score=product.total_score,
            reason_summary=product.reason_summary,
            evidence_tags=product.evidence_tags,
            key_ingredients=product.key_ingredients,
            score_breakdown=product.score_breakdown,
            score_evidence=product.score_evidence,
        )
        for rank, product in enumerate(ranked_products, start=1)
    ]


def _score_candidate(
    candidate: ProductCandidate,
    desired_effects: tuple[_DesiredEffect, ...],
    priority_effect_codes: tuple[str, ...],
    ingredients: tuple[_IngredientEffectInfo, ...],
    functional_info: _FunctionalInfo | None,
    skin_tags: tuple[str, ...],
    skin_profile: _SkinProfileInfo | None,
    risk_flags: tuple[RiskFlag, ...],
    market_signal: _MarketSignalInfo | None,
    match: SearchMatch | None,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    skin_type: str | None,
    sensitivity: str | None,
    skin_test_context: SkinTestScoringContext | None,
    manual_skin_type_explicit: bool,
    manual_sensitivity_explicit: bool,
    price_context: _PriceScoreContext | None,
    weight_resolution: ScoreWeightResolution,
    concentration_policy: ConcentrationScorePolicy,
    skin_profile_weights: SkinProfileWeights,
) -> ScoredProduct:
    contributions_by_effect = _build_contributions_by_effect(ingredients)
    ingredient_effect_score = _score_ingredient_effects(desired_effects, contributions_by_effect)
    ingredient_evidence_score = _score_ingredient_evidence(desired_effects, contributions_by_effect)
    functional_claim_score, functional_claim_context = _score_functional_claim(
        functional_info,
        desired_effects,
        priority_effect_codes,
    )
    concentration_result = _score_concentration_fit(
        desired_effects,
        contributions_by_effect,
        concentration_policy,
    )
    skin_type_score = _score_skin_type(skin_type, skin_tags, skin_profile)
    sensitivity_score = _score_sensitivity(sensitivity, skin_tags, risk_flags, skin_profile)
    skin_profile_score = _weighted_average(
        (
            (skin_type_score, skin_profile_weights.skin_type),
            (sensitivity_score, skin_profile_weights.sensitivity),
        )
    )
    search_match_score = match.search_match_score if match else 0.0
    keyword_score = match.keyword_score if match else 0.0
    vector_score = match.vector_score if match else 0.0
    price_score = _score_price(
        candidate.lowest_price,
        purchase_conditions,
        skin_test_context=skin_test_context,
        price_context=price_context,
    )
    market_signal_score = _score_market_signal(market_signal)
    skin_test_score = _score_skin_test_context(
        skin_test_context,
        intent_purchase_conditions=purchase_conditions,
        candidate=candidate,
        skin_profile=skin_profile,
        risk_flags=risk_flags,
        contributions_by_effect=contributions_by_effect,
        functional_info=functional_info,
        manual_skin_type=skin_type,
        manual_sensitivity=sensitivity,
        manual_skin_type_explicit=manual_skin_type_explicit,
        manual_sensitivity_explicit=manual_sensitivity_explicit,
    )
    risk_penalty = _score_risk_penalty(sensitivity, risk_flags)
    weights = weight_resolution.weights

    raw_score = (
        ingredient_effect_score * weights.ingredient_effect
        + ingredient_evidence_score * weights.ingredient_evidence
        + skin_profile_score * weights.skin_profile
        + concentration_result.score * weights.concentration_fit
        + functional_claim_score * weights.functional_claim
        + search_match_score * weights.search_match
        + price_score * weights.price
        + market_signal_score * weights.market_signal
        + skin_test_score.score * weights.skin_test_context
    )
    total_score = _round_score(_clamp(raw_score) * 100 - risk_penalty)
    score_evidence = _build_score_evidence(contributions_by_effect)
    score_breakdown = {
        "scoring_version": SCORING_VERSION,
        "ingredient_effect_score": _round_component(ingredient_effect_score),
        "ingredient_evidence_score": _round_component(ingredient_evidence_score),
        "functional_claim_score": _round_component(functional_claim_score),
        "functional_status": functional_claim_context["status"],
        "functional_claims": functional_claim_context["claims"],
        "functional_matched_claims": functional_claim_context["matched_claims"],
        "functional_claim_confidence": functional_claim_context["claim_confidence"],
        "concentration_fit_score": _round_component(concentration_result.score),
        "concentration_bucket": concentration_result.bucket,
        "concentration_warning": concentration_result.warning,
        "skin_profile_score": _round_component(skin_profile_score),
        "skin_type_score": _round_component(skin_type_score),
        "sensitivity_score": _round_component(sensitivity_score),
        "keyword_score": _round_component(keyword_score),
        "vector_score": _round_component(vector_score),
        "search_match_score": _round_component(search_match_score),
        "price_score": _round_component(price_score),
        "market_signal_score": _round_component(market_signal_score),
        "skin_test_context_score": _round_component(skin_test_score.score),
        "skin_test_context_applied": skin_test_context is not None,
        "skin_test_context_axes": {
            axis: _round_component(score)
            for axis, score in skin_test_score.axis_scores.items()
        },
        "skin_test_context_matched_axes": list(skin_test_score.matched_axes),
        "skin_test_context_query_conflict_axes": list(skin_test_score.query_conflict_axes),
        "skin_test_context_manual_conflict_axes": list(skin_test_score.manual_conflict_axes),
        "skin_test_context_type_code": skin_test_context.type_code if skin_test_context else None,
        "risk_penalty": risk_penalty,
        "risk_policy": "display_all_penalize_sensitive",
        "risk_flag_count": len(risk_flags),
        "risk_warnings": _risk_warning_texts(risk_flags),
        "sensitive_risk_penalty_cap": SENSITIVE_RISK_PENALTY_CAP,
        "weights": {
            "ingredient_effect": weights.ingredient_effect,
            "ingredient_evidence": weights.ingredient_evidence,
            "skin_profile": weights.skin_profile,
            "concentration_fit": weights.concentration_fit,
            "functional_claim": weights.functional_claim,
            "search_match": weights.search_match,
            "price": weights.price,
            "market_signal": weights.market_signal,
            "skin_test_context": weights.skin_test_context,
        },
        "base_weights": _weights_to_dict(weight_resolution.base_weights),
        "applied_multipliers": _multipliers_to_dict(weight_resolution.multipliers),
        "weight_profile": weight_resolution.weight_profile,
        "search_intent_signals": list(weight_resolution.search_intent_signals),
        "skin_profile_weights": {
            "skin_type": skin_profile_weights.skin_type,
            "sensitivity": skin_profile_weights.sensitivity,
        },
        "concentration_policy": {
            "unknown": concentration_policy.unknown,
            "below_meaningful": concentration_policy.below_meaningful,
            "meaningful": concentration_policy.meaningful,
            "optimal": concentration_policy.optimal,
            "above_optimal": concentration_policy.above_optimal,
            "excessive": concentration_policy.excessive,
        },
        "confidence_multipliers": {
            "high": CONFIDENCE_MULTIPLIERS["high"],
            "medium": CONFIDENCE_MULTIPLIERS["medium"],
            "low": CONFIDENCE_MULTIPLIERS["low"],
            "unknown": CONFIDENCE_MULTIPLIERS["unknown"],
        },
        "concentration_weight_mode": "direct_axis",
        "effect_cap": EFFECT_CAP,
        "top_ingredient_decays": list(TOP_INGREDIENT_DECAYS),
        "total_score": total_score,
    }

    return ScoredProduct(
        product_id=candidate.product_id,
        db_product_id=candidate.db_product_id,
        rank=0,
        total_score=total_score,
        reason_summary=_build_reason_summary(score_evidence),
        evidence_tags=_build_evidence_tags(score_evidence),
        key_ingredients=_build_key_ingredients(score_evidence),
        score_breakdown=score_breakdown,
        score_evidence=score_evidence,
    )


def _resolve_score_weights(
    intent: RecommendationIntent,
    weights: ScoreWeights,
    *,
    skin_test_context: SkinTestScoringContext | None,
) -> ScoreWeightResolution:
    signals = _search_intent_signals(intent)
    if weights != DEFAULT_SCORE_WEIGHTS:
        base_weights = weights
        weight_profile = "custom"
    elif _has_strong_search_intent(intent, signals):
        base_weights = SEARCH_INTENT_SCORE_WEIGHTS
        weight_profile = "search_intent_boost"
    else:
        base_weights = weights
        weight_profile = "default"

    active_base_weights = (
        base_weights
        if skin_test_context is not None
        else replace(base_weights, skin_test_context=0.0)
    )
    multipliers = _build_weight_multipliers(skin_test_context)
    resolved_weights = _normalize_weights(active_base_weights, multipliers)
    return ScoreWeightResolution(
        weights=resolved_weights,
        base_weights=active_base_weights,
        multipliers=multipliers,
        weight_profile=weight_profile,
        search_intent_signals=signals,
    )


def _build_weight_multipliers(
    skin_test_context: SkinTestScoringContext | None,
) -> ScoreMultipliers:
    values = {field: 1.0 for field in SCORE_WEIGHT_FIELDS}
    if skin_test_context is None:
        return ScoreMultipliers()

    buying_criteria = _commerce_code(skin_test_context, "buying_criteria")
    if buying_criteria == "ingredient":
        values["ingredient_effect"] *= 1.04
        values["ingredient_evidence"] *= 1.12
    elif buying_criteria == "review":
        values["market_signal"] *= 2.50
    elif buying_criteria == "value":
        values["price"] *= 1.60

    price_investment = _commerce_code(skin_test_context, "price_investment")
    if price_investment == "daily_repeat_value":
        values["price"] *= 1.40
    elif price_investment == "value_volume":
        values["price"] *= 1.60
    elif price_investment == "functional_investment":
        values["ingredient_evidence"] *= 1.08
        values["concentration_fit"] *= 1.15
        values["functional_claim"] *= 1.20
    elif price_investment == "premium_effect":
        values["price"] *= 0.70
        values["ingredient_evidence"] *= 1.10
        values["functional_claim"] *= 1.15

    decision_trigger = _commerce_code(skin_test_context, "decision_trigger")
    if decision_trigger == "clinical_evidence":
        values["ingredient_evidence"] *= 1.15
        values["concentration_fit"] *= 1.12
        values["functional_claim"] *= 1.15
    elif decision_trigger == "similar_review":
        values["market_signal"] *= 2.50

    capped = {
        field: _cap_weight_multiplier(field, multiplier)
        for field, multiplier in values.items()
    }
    return ScoreMultipliers(**capped)


def _normalize_weights(
    base_weights: ScoreWeights,
    multipliers: ScoreMultipliers,
) -> ScoreWeights:
    weighted_values = {
        field: max(0.0, getattr(base_weights, field) * getattr(multipliers, field))
        for field in SCORE_WEIGHT_FIELDS
    }
    total = sum(weighted_values.values())
    if total <= 0:
        return base_weights
    return ScoreWeights(
        **{
            field: weighted_values[field] / total
            for field in SCORE_WEIGHT_FIELDS
        }
    )


def _cap_weight_multiplier(field: str, multiplier: float) -> float:
    cap = WEIGHT_MULTIPLIER_CAPS.get(field)
    if cap is None:
        return multiplier
    lower, upper = cap
    return max(lower, min(upper, multiplier))


def _weights_to_dict(weights: ScoreWeights) -> dict[str, float]:
    return {
        field: getattr(weights, field)
        for field in SCORE_WEIGHT_FIELDS
    }


def _multipliers_to_dict(multipliers: ScoreMultipliers) -> dict[str, float]:
    return {
        field: getattr(multipliers, field)
        for field in SCORE_WEIGHT_FIELDS
    }


def _has_strong_search_intent(
    intent: RecommendationIntent,
    signals: tuple[str, ...],
) -> bool:
    has_product_selector = bool(
        intent.purchase_conditions.categories
        or intent.purchase_conditions.brands
    )
    if not has_product_selector:
        return False

    selector_count = sum(
        1
        for active in (
            bool(intent.purchase_conditions.categories),
            bool(intent.purchase_conditions.brands),
            intent.purchase_conditions.price_min is not None
            or intent.purchase_conditions.price_max is not None,
        )
        if active
    )
    has_relevance_terms = bool(
        intent.search_terms
        or intent.priority_effects
        or selector_count >= 2
    )
    return has_relevance_terms and bool(signals)


def _search_intent_signals(intent: RecommendationIntent) -> tuple[str, ...]:
    signals: list[str] = []
    if intent.purchase_conditions.categories:
        signals.append("category")
    if intent.purchase_conditions.brands:
        signals.append("brand")
    if (
        intent.purchase_conditions.price_min is not None
        or intent.purchase_conditions.price_max is not None
    ):
        signals.append("price")
    if intent.search_terms:
        signals.append("search_terms")
    if intent.priority_effects:
        signals.append("priority_effect")
    return tuple(signals)


def _build_desired_effects(intent: RecommendationIntent) -> tuple[_DesiredEffect, ...]:
    effects_by_code: dict[str, _DesiredEffect] = {}
    for effect in intent.effects:
        _upsert_desired_effect(effects_by_code, effect.effect_id, effect.name, effect.weight)

    for effect in intent.priority_effects:
        priority_weight = effect.weight * PRIORITY_EFFECT_MULTIPLIER
        _upsert_desired_effect(effects_by_code, effect.effect_id, effect.name, priority_weight)

    return tuple(effects_by_code.values())


def _upsert_desired_effect(
    effects_by_code: dict[str, _DesiredEffect],
    effect_code: str,
    name: str,
    weight: float,
) -> None:
    existing = effects_by_code.get(effect_code)
    if existing is None or weight > existing.weight:
        effects_by_code[effect_code] = _DesiredEffect(
            effect_code=effect_code,
            name=name,
            weight=max(weight, 0.0),
        )


def _load_ingredient_effects(
    session: Session,
    product_ids: list[int],
    desired_effects: tuple[_DesiredEffect, ...],
) -> dict[int, tuple[_IngredientEffectInfo, ...]]:
    if not product_ids or not desired_effects:
        return {}

    desired_effect_codes = [effect.effect_code for effect in desired_effects]
    rows = session.execute(
        select(
            ProductIngredient.product_id.label("product_db_id"),
            ProductIngredient.display_order,
            ProductIngredient.concentration_text,
            ProductIngredient.concentration_confidence,
            ProductIngredient.normalized_concentration_value,
            ProductIngredient.normalized_concentration_unit,
            Ingredient.id.label("ingredient_id"),
            Ingredient.ingredient_code,
            Ingredient.name_ko.label("ingredient_name"),
            Effect.id.label("effect_id"),
            Effect.effect_code,
            Effect.name.label("effect_name"),
            IngredientEffect.effect_score,
            IngredientEvidence.id.label("evidence_id"),
            IngredientEvidence.evidence_score,
            IngredientEvidence.evidence_level,
            IngredientEvidence.summary,
            IngredientEvidence.source_type,
            IngredientEvidence.pmid,
            IngredientEvidence.doi,
            IngredientEvidence.source_authority_score,
            IngredientEffectRange.meaningful_min,
            IngredientEffectRange.optimal_min,
            IngredientEffectRange.optimal_max,
            IngredientEffectRange.excessive_min,
            IngredientEffectRange.range_confidence,
            IngredientEffectRange.source_type,
            IngredientEffectRange.source_url.label("range_source_url"),
            IngredientEffectRange.note.label("range_note"),
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .join(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .join(Effect, IngredientEffect.effect_id == Effect.id)
        .outerjoin(
            IngredientEffectRange,
            and_(
                IngredientEffectRange.ingredient_id == Ingredient.id,
                IngredientEffectRange.effect_id == Effect.id,
                IngredientEffectRange.unit == ProductIngredient.normalized_concentration_unit,
            ),
        )
        .outerjoin(
            IngredientEvidence,
            and_(
                IngredientEvidence.ingredient_id == Ingredient.id,
                IngredientEvidence.effect_id == Effect.id,
            ),
        )
        .where(
            ProductIngredient.product_id.in_(product_ids),
            Effect.effect_code.in_(desired_effect_codes),
        )
    ).all()

    grouped: dict[tuple[int, int, str], _IngredientEffectInfo] = {}
    for row in rows:
        key = (int(row.product_db_id), int(row.ingredient_id), row.effect_code)
        evidence = _row_to_evidence(row)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = _IngredientEffectInfo(
                product_db_id=int(row.product_db_id),
                ingredient_id=int(row.ingredient_id),
                ingredient_code=row.ingredient_code,
                ingredient_name=row.ingredient_name,
                effect_id=int(row.effect_id),
                effect_code=row.effect_code,
                effect_name=row.effect_name,
                effect_score=_decimal_to_float(row.effect_score),
                display_order=row.display_order or 999,
                evidence=evidence,
                concentration=_row_to_concentration(row),
            )
            continue

        if _is_better_evidence(evidence, existing.evidence):
            grouped[key] = _IngredientEffectInfo(
                product_db_id=existing.product_db_id,
                ingredient_id=existing.ingredient_id,
                ingredient_code=existing.ingredient_code,
                ingredient_name=existing.ingredient_name,
                effect_id=existing.effect_id,
                effect_code=existing.effect_code,
                effect_name=existing.effect_name,
                effect_score=existing.effect_score,
                display_order=existing.display_order,
                evidence=evidence,
                concentration=existing.concentration,
            )

    ingredients_by_product: dict[int, list[_IngredientEffectInfo]] = {}
    for info in grouped.values():
        ingredients_by_product.setdefault(info.product_db_id, []).append(info)

    return {
        product_id: tuple(ingredients)
        for product_id, ingredients in ingredients_by_product.items()
    }


def _load_functional_info(session: Session, product_ids: list[int]) -> dict[int, _FunctionalInfo]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(
            Product.id,
            Product.functional_cosmetic_status,
            Product.functional_cosmetic_claims,
            Product.functional_claim_confidence,
            Product.functional_claim_basis,
        ).where(Product.id.in_(product_ids))
    ).all()

    return {
        int(row.id): _FunctionalInfo(
            status=row.functional_cosmetic_status,
            claims=_split_tags(row.functional_cosmetic_claims),
            claim_confidence=row.functional_claim_confidence,
            basis=row.functional_claim_basis,
        )
        for row in rows
    }


def _row_to_evidence(row) -> _EvidenceInfo | None:
    if row.evidence_id is None:
        return None
    return _EvidenceInfo(
        evidence_id=int(row.evidence_id),
        evidence_score=_decimal_to_float(row.evidence_score),
        evidence_level=row.evidence_level,
        summary=row.summary,
        source_type=row.source_type,
        pmid=row.pmid,
        doi=row.doi,
        source_authority_score=_optional_decimal_to_float(row.source_authority_score),
    )


def _row_to_concentration(row) -> _ConcentrationInfo:
    concentration_range = None
    if row.meaningful_min is not None and row.optimal_min is not None and row.optimal_max is not None:
        concentration_range = _ConcentrationRangeInfo(
            meaningful_min=_decimal_to_float(row.meaningful_min),
            optimal_min=_decimal_to_float(row.optimal_min),
            optimal_max=_decimal_to_float(row.optimal_max),
            excessive_min=_optional_decimal_to_float(row.excessive_min),
            range_confidence=row.range_confidence,
            source_type=row.source_type,
            source_url=row.range_source_url,
            note=row.range_note,
        )

    return _ConcentrationInfo(
        value=_optional_decimal_to_float(row.normalized_concentration_value),
        unit=row.normalized_concentration_unit,
        text=row.concentration_text,
        confidence=row.concentration_confidence,
        range=concentration_range,
    )


def _is_better_evidence(candidate: _EvidenceInfo | None, existing: _EvidenceInfo | None) -> bool:
    if candidate is None:
        return False
    if existing is None:
        return True
    return _effective_evidence_score(candidate) > _effective_evidence_score(existing)


def _load_skin_tags(session: Session, product_ids: list[int]) -> dict[int, tuple[str, ...]]:
    rows = session.execute(
        select(Product.id, Product.skin_type_tags).where(Product.id.in_(product_ids))
    ).all()
    return {
        int(row.id): _split_tags(row.skin_type_tags)
        for row in rows
    }


def _load_skin_profiles(session: Session, product_ids: list[int]) -> dict[int, _SkinProfileInfo]:
    rows = session.execute(
        select(ProductSkinProfile).where(ProductSkinProfile.product_id.in_(product_ids))
    ).scalars()
    return {
        int(row.product_id): _SkinProfileInfo(
            dry_fit=_decimal_to_float(row.dry_fit),
            oily_fit=_decimal_to_float(row.oily_fit),
            combination_fit=_decimal_to_float(row.combination_fit),
            normal_fit=_decimal_to_float(row.normal_fit),
            dehydrated_oily_fit=_decimal_to_float(row.dehydrated_oily_fit),
            sensitive_fit=_decimal_to_float(row.sensitive_fit),
            sensitivity_tag=row.sensitivity_tag,
            confidence=row.confidence,
            reason=row.reason,
        )
        for row in rows
    }


def _load_risk_flags(session: Session, product_ids: list[int]) -> dict[int, tuple[RiskFlag, ...]]:
    rows = (
        session.execute(
            select(ProductIngredient.product_id, RiskFlag)
            .join(RiskFlag, RiskFlag.ingredient_id == ProductIngredient.ingredient_id)
            .where(ProductIngredient.product_id.in_(product_ids))
        )
        .all()
    )
    flags_by_product: dict[int, list[RiskFlag]] = {}
    for product_id, flag in rows:
        flags_by_product.setdefault(int(product_id), []).append(flag)
    return {
        product_id: tuple(flags)
        for product_id, flags in flags_by_product.items()
    }


def _load_market_signals(session: Session, product_ids: list[int]) -> dict[int, _MarketSignalInfo]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(ProductPopularityMetric).where(
            ProductPopularityMetric.product_id.in_(product_ids),
            ProductPopularityMetric.window_days == MARKET_SIGNAL_WINDOW_DAYS,
        )
    ).scalars()
    return {
        int(row.product_id): _MarketSignalInfo(
            popularity_score=_decimal_to_float(row.popularity_score),
            review_count=int(row.review_count),
            average_rating=_optional_decimal_to_float(row.average_rating),
        )
        for row in rows
    }


def _build_price_score_context(candidates: list[ProductCandidate]) -> _PriceScoreContext | None:
    prices = [candidate.lowest_price for candidate in candidates if candidate.lowest_price > 0]
    if not prices:
        return None
    return _PriceScoreContext(min_price=min(prices), max_price=max(prices))


def _build_contributions_by_effect(
    ingredients: tuple[_IngredientEffectInfo, ...],
) -> dict[str, tuple[_EffectContribution, ...]]:
    ingredients_by_effect: dict[str, list[_IngredientEffectInfo]] = {}
    for ingredient in ingredients:
        ingredients_by_effect.setdefault(ingredient.effect_code, []).append(ingredient)

    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]] = {}
    for effect_code, effect_ingredients in ingredients_by_effect.items():
        ranked_ingredients = sorted(
            effect_ingredients,
            key=lambda ingredient: (-ingredient.effect_score, ingredient.display_order),
        )
        contributions = [
            _EffectContribution(
                ingredient=ingredient,
                decay=decay,
                effect_component=(ingredient.effect_score / 100) * decay,
                evidence_component=_evidence_component(ingredient.evidence, decay),
            )
            for ingredient, decay in zip(ranked_ingredients, TOP_INGREDIENT_DECAYS, strict=False)
        ]
        contributions_by_effect[effect_code] = tuple(contributions)

    return contributions_by_effect


def _evidence_component(evidence: _EvidenceInfo | None, decay: float) -> float:
    if evidence is None:
        return 0.0
    return (_effective_evidence_score(evidence) / 100) * decay


def _effective_evidence_score(evidence: _EvidenceInfo) -> float:
    authority_score = evidence.source_authority_score
    authority_multiplier = _clamp(authority_score) if authority_score is not None else 1.0
    return evidence.evidence_score * authority_multiplier


def _score_ingredient_effects(
    desired_effects: tuple[_DesiredEffect, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
) -> float:
    return _score_weighted_effect_axis(
        desired_effects,
        contributions_by_effect,
        component_name="effect_component",
    )


def _score_ingredient_evidence(
    desired_effects: tuple[_DesiredEffect, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
) -> float:
    return _score_weighted_effect_axis(
        desired_effects,
        contributions_by_effect,
        component_name="evidence_component",
    )


def _score_functional_claim(
    functional_info: _FunctionalInfo | None,
    desired_effects: tuple[_DesiredEffect, ...],
    priority_effect_codes: tuple[str, ...],
) -> tuple[float, dict]:
    if functional_info is None:
        return 0.0, _functional_context(None, (), (), None)

    claims = functional_info.claims
    if functional_info.status != FUNCTIONAL_CONFIRMED_STATUS:
        return 0.0, _functional_context(functional_info.status, claims, (), functional_info.claim_confidence)

    desired_effect_codes = {effect.effect_code for effect in desired_effects}
    priority_codes = set(priority_effect_codes)
    claim_effect_codes = {
        effect_code
        for claim in claims
        for effect_code in (FUNCTIONAL_CLAIM_EFFECT_CODES.get(claim),)
        if effect_code
    }
    matched_effect_codes = claim_effect_codes & desired_effect_codes
    matched_claims = tuple(
        claim
        for claim in claims
        if FUNCTIONAL_CLAIM_EFFECT_CODES.get(claim) in matched_effect_codes
    )

    if not matched_effect_codes:
        return FUNCTIONAL_BASE_SCORE, _functional_context(
            functional_info.status,
            claims,
            matched_claims,
            functional_info.claim_confidence,
        )

    raw_score = (
        FUNCTIONAL_PRIORITY_MATCH_SCORE
        if matched_effect_codes & priority_codes
        else FUNCTIONAL_MATCH_SCORE
    )
    adjusted_score = _adjust_score_by_confidence(
        raw_score,
        functional_info.claim_confidence,
        baseline=FUNCTIONAL_BASE_SCORE,
    )
    return adjusted_score, _functional_context(
        functional_info.status,
        claims,
        matched_claims,
        functional_info.claim_confidence,
    )


def _functional_context(
    status: str | None,
    claims: tuple[str, ...],
    matched_claims: tuple[str, ...],
    claim_confidence: str | None,
) -> dict:
    return {
        "status": status,
        "claims": list(claims),
        "matched_claims": list(matched_claims),
        "claim_confidence": claim_confidence,
    }


def _score_concentration_fit(
    desired_effects: tuple[_DesiredEffect, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    policy: ConcentrationScorePolicy,
) -> _ConcentrationResult:
    if not desired_effects:
        return _ConcentrationResult(bucket="unknown", score=policy.unknown)

    effect_scores: list[tuple[float, float]] = []
    concentration_results: list[_ConcentrationResult] = []
    for desired_effect in desired_effects:
        contributions = contributions_by_effect.get(desired_effect.effect_code, ())
        if not contributions:
            effect_scores.append((policy.unknown, desired_effect.weight))
            continue

        contribution_scores: list[tuple[float, float]] = []
        for contribution in contributions:
            result = _score_single_concentration(contribution.ingredient, policy)
            concentration_results.append(result)
            contribution_scores.append((result.score, contribution.decay))

        effect_scores.append((_weighted_average(tuple(contribution_scores)), desired_effect.weight))

    aggregate_score = _clamp(_weighted_average(tuple(effect_scores)))
    display_result = _select_display_concentration_result(concentration_results, policy)
    warning_result = next((result for result in concentration_results if result.warning), None)
    return _ConcentrationResult(
        bucket=display_result.bucket,
        score=aggregate_score,
        ingredient_name=display_result.ingredient_name,
        effect_name=display_result.effect_name,
        concentration_text=display_result.concentration_text,
        warning=warning_result.warning if warning_result else None,
    )


def _score_single_concentration(
    ingredient: _IngredientEffectInfo,
    policy: ConcentrationScorePolicy,
) -> _ConcentrationResult:
    concentration = ingredient.concentration
    concentration_range = concentration.range
    if concentration.value is None or concentration_range is None:
        return _build_concentration_result("unknown", policy.unknown, ingredient)

    value = concentration.value
    if concentration_range.excessive_min is not None and value >= concentration_range.excessive_min:
        warning = (
            f"{ingredient.ingredient_name} 함량이 과다 기준 이상으로 표시되어 "
            "민감 피부는 주의가 필요합니다."
        )
        return _build_concentration_result(
            "excessive",
            _adjust_concentration_score(policy.excessive, concentration),
            ingredient,
            warning=warning,
        )
    if value < concentration_range.meaningful_min:
        return _build_concentration_result(
            "below_meaningful",
            _adjust_concentration_score(policy.below_meaningful, concentration),
            ingredient,
        )
    if value < concentration_range.optimal_min:
        return _build_concentration_result(
            "meaningful",
            _adjust_concentration_score(policy.meaningful, concentration),
            ingredient,
        )
    if value <= concentration_range.optimal_max:
        return _build_concentration_result(
            "optimal",
            _adjust_concentration_score(policy.optimal, concentration),
            ingredient,
        )
    return _build_concentration_result(
        "above_optimal",
        _adjust_concentration_score(policy.above_optimal, concentration),
        ingredient,
    )


def _adjust_concentration_score(score: float, concentration: _ConcentrationInfo) -> float:
    confidence_multiplier = min(
        _confidence_multiplier(concentration.confidence),
        _confidence_multiplier(concentration.range.range_confidence if concentration.range else None),
    )
    return _adjust_score_by_multiplier(score, confidence_multiplier)


def _build_concentration_result(
    bucket: str,
    score: float,
    ingredient: _IngredientEffectInfo,
    *,
    warning: str | None = None,
) -> _ConcentrationResult:
    return _ConcentrationResult(
        bucket=bucket,
        score=_clamp(score),
        ingredient_name=ingredient.ingredient_name,
        effect_name=ingredient.effect_name,
        concentration_text=ingredient.concentration.text,
        warning=warning,
    )


def _select_display_concentration_result(
    results: list[_ConcentrationResult],
    policy: ConcentrationScorePolicy,
) -> _ConcentrationResult:
    known_results = [result for result in results if result.bucket != "unknown"]
    if not known_results:
        return _ConcentrationResult(bucket="unknown", score=policy.unknown)
    return max(known_results, key=lambda result: result.score)


def _score_weighted_effect_axis(
    desired_effects: tuple[_DesiredEffect, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    *,
    component_name: str,
) -> float:
    weighted_scores: list[tuple[float, float]] = []
    for desired_effect in desired_effects:
        contributions = contributions_by_effect.get(desired_effect.effect_code, ())
        raw_effect_score = sum(getattr(contribution, component_name) for contribution in contributions)
        capped_effect_score = min(raw_effect_score, EFFECT_CAP)
        weighted_scores.append((capped_effect_score, desired_effect.weight))

    return _clamp(_weighted_average(tuple(weighted_scores)))


def _score_skin_type(
    skin_type: str | None,
    skin_tags: tuple[str, ...],
    skin_profile: _SkinProfileInfo | None,
) -> float:
    normalized_skin_type = _normalize_profile_value(skin_type) or "중성"
    if skin_profile is not None:
        profile_score = _skin_type_profile_score(normalized_skin_type, skin_profile)
        if profile_score is not None:
            return _adjust_score_by_confidence(profile_score, skin_profile.confidence)

    normalized_tags = {_normalize_profile_value(tag) for tag in skin_tags}
    normalized_tags.discard("")

    if not normalized_tags:
        return DEFAULT_PROFILE_SCORE
    if normalized_skin_type in {"중성", "보통"}:
        return 1.0 if "중성" in normalized_tags else 0.7
    if normalized_skin_type in normalized_tags:
        return 1.0
    if normalized_tags & _compatible_skin_types(normalized_skin_type):
        return 0.75
    return 0.3


def _compatible_skin_types(skin_type: str) -> set[str]:
    compatibility = {
        "건성": {"수부지", "중성"},
        "지성": {"복합성"},
        "복합성": {"지성", "수부지", "중성"},
        "수부지": {"건성", "복합성", "중성"},
        "중성": {"건성", "지성", "복합성", "수부지"},
    }
    return compatibility.get(skin_type, set())


def _score_sensitivity(
    sensitivity: str | None,
    skin_tags: tuple[str, ...],
    risk_flags: tuple[RiskFlag, ...],
    skin_profile: _SkinProfileInfo | None,
) -> float:
    normalized_sensitivity = _normalize_profile_value(sensitivity) or "보통"
    if skin_profile is not None:
        return _adjust_score_by_confidence(
            _sensitivity_profile_score(normalized_sensitivity, skin_profile),
            skin_profile.confidence,
        )

    normalized_tags = {_normalize_profile_value(tag) for tag in skin_tags}
    normalized_tags.discard("")
    most_severe = _most_severe_risk(risk_flags)

    if normalized_sensitivity in {"높음", "민감", "예민"}:
        if normalized_tags & {"민감", "저자극", "민감추천", "민감가능"}:
            return 1.0
        if most_severe == "high":
            return 0.3
        if most_severe == "medium":
            return 0.55
        if most_severe == "low":
            return 0.75
        return 0.6

    if normalized_sensitivity == "낮음":
        return 0.85 if most_severe == "high" else 0.95

    if most_severe == "high":
        return 0.7
    if most_severe == "medium":
        return 0.8
    return 0.9


def _score_risk_penalty(sensitivity: str | None, risk_flags: tuple[RiskFlag, ...]) -> float:
    if not _is_sensitive_user(sensitivity):
        return 0.0

    penalties_by_type: dict[str, float] = {}
    for flag in risk_flags:
        if not _risk_applies_to_sensitive(flag):
            continue
        penalty = _risk_penalty_value(flag)
        current = penalties_by_type.get(flag.risk_type, 0.0)
        if penalty > current:
            penalties_by_type[flag.risk_type] = penalty

    return round(min(SENSITIVE_RISK_PENALTY_CAP, sum(penalties_by_type.values())), 2)


def _risk_warning_texts(risk_flags: tuple[RiskFlag, ...], *, limit: int = 3) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for flag in risk_flags:
        text = (flag.display_text or "").strip()
        if not text or text in seen:
            continue
        warnings.append(text)
        seen.add(text)
        if len(warnings) >= limit:
            break
    return warnings


def _is_sensitive_user(sensitivity: str | None) -> bool:
    normalized_sensitivity = _normalize_profile_value(sensitivity) or "보통"
    return normalized_sensitivity in {"높음", "민감", "예민"}


def _risk_applies_to_sensitive(flag: RiskFlag) -> bool:
    applies_to = {value.casefold() for value in _split_tags(flag.applies_to)}
    return "sensitive" in applies_to


def _risk_penalty_value(flag: RiskFlag) -> float:
    severity_penalty = {
        "high": 6.0,
        "medium": 3.0,
        "low": 1.0,
    }
    severity = (flag.severity or "").casefold()
    if severity in severity_penalty:
        return severity_penalty[severity]
    severity_score = _optional_decimal_to_float(flag.severity_score)
    return _clamp(severity_score or 0.0) * 6.0


def _skin_type_profile_score(skin_type: str, skin_profile: _SkinProfileInfo) -> float | None:
    scores = {
        "건성": skin_profile.dry_fit,
        "지성": skin_profile.oily_fit,
        "복합성": skin_profile.combination_fit,
        "중성": skin_profile.normal_fit,
        "보통": skin_profile.normal_fit,
        "수부지": skin_profile.dehydrated_oily_fit,
    }
    score = scores.get(skin_type)
    return _clamp(score) if score is not None else None


def _sensitivity_profile_score(sensitivity: str, skin_profile: _SkinProfileInfo) -> float:
    sensitive_score = _clamp(skin_profile.sensitive_fit)
    if sensitivity in {"높음", "민감", "예민"}:
        return sensitive_score
    if sensitivity == "낮음":
        return max(sensitive_score, 0.85)
    return max(sensitive_score, 0.6)


def _most_severe_risk(risk_flags: tuple[RiskFlag, ...]) -> str | None:
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    severities = [flag.severity for flag in risk_flags if flag.severity in severity_rank]
    if not severities:
        return None
    return max(severities, key=lambda severity: severity_rank[severity])


def _score_price(
    price: int,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    skin_test_context: SkinTestScoringContext | None,
    price_context: _PriceScoreContext | None,
) -> float:
    has_price_condition = (
        purchase_conditions.price_min is not None
        or purchase_conditions.price_max is not None
    )
    if has_price_condition:
        if purchase_conditions.price_min is not None and price < purchase_conditions.price_min:
            return 0.0
        if purchase_conditions.price_max is not None and price > purchase_conditions.price_max:
            return 0.0
        return 1.0

    if _is_value_oriented(skin_test_context) and price_context is not None:
        return _score_relative_affordability(price, price_context)
    return DEFAULT_PROFILE_SCORE


def _score_market_signal(market_signal: _MarketSignalInfo | None) -> float:
    if market_signal is None:
        return DEFAULT_PROFILE_SCORE
    return _clamp(market_signal.popularity_score / 100)


def _score_skin_test_context(
    skin_test_context: SkinTestScoringContext | None,
    *,
    intent_purchase_conditions: ParsedPurchaseConditions,
    candidate: ProductCandidate,
    skin_profile: _SkinProfileInfo | None,
    risk_flags: tuple[RiskFlag, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    functional_info: _FunctionalInfo | None,
    manual_skin_type: str | None,
    manual_sensitivity: str | None,
    manual_skin_type_explicit: bool,
    manual_sensitivity_explicit: bool,
) -> _SkinTestContextScore:
    if skin_test_context is None:
        return _SkinTestContextScore(
            score=DEFAULT_PROFILE_SCORE,
            axis_scores={},
            matched_axes=(),
            query_conflict_axes=(),
            manual_conflict_axes=(),
        )

    query_conflict_axes: list[str] = []
    manual_conflict_axes: list[str] = []
    components: list[tuple[float, float]] = []
    axis_scores: dict[str, float] = {}

    od_conflict = _has_manual_skin_type_conflict(
        skin_test_context,
        manual_skin_type,
        manual_skin_type_explicit=manual_skin_type_explicit,
    )
    if od_conflict:
        manual_conflict_axes.append("OD")
    od_score = _score_od_fit(skin_test_context, skin_profile, manual_conflict=od_conflict)
    axis_scores["OD"] = od_score
    components.append((od_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["OD"]))

    sr_conflict = _has_manual_sensitivity_conflict(
        skin_test_context,
        manual_sensitivity,
        manual_sensitivity_explicit=manual_sensitivity_explicit,
    )
    if sr_conflict:
        manual_conflict_axes.append("SR")
    sr_score = _score_sr_fit(
        skin_test_context,
        skin_profile,
        risk_flags,
        manual_conflict=sr_conflict,
    )
    axis_scores["SR"] = sr_score
    components.append((sr_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["SR"]))

    category_query_conflict = bool(intent_purchase_conditions.categories)
    if category_query_conflict:
        query_conflict_axes.append("CATEGORY_PREF")
    category_score = _score_category_preference_fit(
        skin_test_context,
        candidate,
        query_conflict=category_query_conflict,
    )
    axis_scores["CATEGORY_PREF"] = category_score
    components.append((category_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["CATEGORY_PREF"]))

    pn_score = _score_pn_effect_fit(
        skin_test_context,
        contributions_by_effect,
        functional_info,
    )
    axis_scores["PN"] = pn_score
    components.append((pn_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["PN"]))

    wt_score = _score_wt_effect_fit(
        skin_test_context,
        contributions_by_effect,
        functional_info,
    )
    axis_scores["WT"] = wt_score
    components.append((wt_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["WT"]))

    sensitive_safety_score = _score_sensitive_safety_fit(skin_test_context, risk_flags)
    axis_scores["SENSITIVE_SAFETY"] = sensitive_safety_score
    components.append(
        (
            sensitive_safety_score,
            SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["SENSITIVE_SAFETY"],
        )
    )

    score = _clamp(_weighted_average(tuple(components)))
    matched_axes = tuple(
        axis
        for axis, axis_score in axis_scores.items()
        if axis_score > DEFAULT_PROFILE_SCORE
    )
    return _SkinTestContextScore(
        score=score,
        axis_scores=axis_scores,
        matched_axes=matched_axes,
        query_conflict_axes=tuple(query_conflict_axes),
        manual_conflict_axes=tuple(manual_conflict_axes),
    )


def _score_od_fit(
    skin_test_context: SkinTestScoringContext,
    skin_profile: _SkinProfileInfo | None,
    *,
    manual_conflict: bool,
) -> float:
    winner = _axis_winner(skin_test_context, "OD")
    if skin_profile is None or winner not in {"O", "D"}:
        raw_score = DEFAULT_PROFILE_SCORE
    elif winner == "O":
        raw_score = skin_profile.oily_fit
    else:
        raw_score = skin_profile.dry_fit
    return _adjust_skin_test_axis_score(
        raw_score,
        _axis_strength(skin_test_context, "OD"),
        manual_conflict=manual_conflict,
    )


def _score_sr_fit(
    skin_test_context: SkinTestScoringContext,
    skin_profile: _SkinProfileInfo | None,
    risk_flags: tuple[RiskFlag, ...],
    *,
    manual_conflict: bool,
) -> float:
    winner = _axis_winner(skin_test_context, "SR")
    if winner == "S":
        raw_score = skin_profile.sensitive_fit if skin_profile is not None else _sensitive_safety_score(risk_flags)
    elif winner == "R":
        raw_score = _resistant_safety_score(risk_flags)
    else:
        raw_score = DEFAULT_PROFILE_SCORE
    return _adjust_skin_test_axis_score(
        raw_score,
        _axis_strength(skin_test_context, "SR"),
        manual_conflict=manual_conflict,
    )


def _score_category_preference_fit(
    skin_test_context: SkinTestScoringContext,
    candidate: ProductCandidate,
    *,
    query_conflict: bool,
) -> float:
    preferred_code = _commerce_code(skin_test_context, "category_preference")
    if preferred_code is None:
        return DEFAULT_PROFILE_SCORE
    if _category_matches_preference(candidate.category_code, preferred_code):
        return 1.0
    if query_conflict:
        return 0.0
    return DEFAULT_PROFILE_SCORE


def _score_pn_effect_fit(
    skin_test_context: SkinTestScoringContext,
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    functional_info: _FunctionalInfo | None,
) -> float:
    winner = _axis_winner(skin_test_context, "PN")
    if winner != "P":
        return DEFAULT_PROFILE_SCORE
    raw_score = _score_effect_signal(PIGMENT_EFFECT_CODES, contributions_by_effect, functional_info)
    return _adjust_skin_test_axis_score(raw_score, _axis_strength(skin_test_context, "PN"))


def _score_wt_effect_fit(
    skin_test_context: SkinTestScoringContext,
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    functional_info: _FunctionalInfo | None,
) -> float:
    winner = _axis_winner(skin_test_context, "WT")
    if winner != "W":
        return DEFAULT_PROFILE_SCORE
    raw_score = _score_effect_signal(WRINKLE_EFFECT_CODES, contributions_by_effect, functional_info)
    return _adjust_skin_test_axis_score(raw_score, _axis_strength(skin_test_context, "WT"))


def _score_sensitive_safety_fit(
    skin_test_context: SkinTestScoringContext,
    risk_flags: tuple[RiskFlag, ...],
) -> float:
    if _axis_winner(skin_test_context, "SR") != "S":
        return DEFAULT_PROFILE_SCORE
    return _adjust_skin_test_axis_score(
        _sensitive_safety_score(risk_flags),
        _axis_strength(skin_test_context, "SR"),
    )


def _score_effect_signal(
    effect_codes: tuple[str, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    functional_info: _FunctionalInfo | None,
) -> float:
    signal = 0.0
    for effect_code in effect_codes:
        contributions = contributions_by_effect.get(effect_code, ())
        contribution_signal = min(
            EFFECT_CAP,
            sum(contribution.effect_component for contribution in contributions),
        ) / EFFECT_CAP
        signal = max(signal, contribution_signal)

    if functional_info is not None and functional_info.status == FUNCTIONAL_CONFIRMED_STATUS:
        claim_effect_codes = {
            effect_code
            for claim in functional_info.claims
            for effect_code in (FUNCTIONAL_CLAIM_EFFECT_CODES.get(claim),)
            if effect_code
        }
        if claim_effect_codes & set(effect_codes):
            signal = max(signal, 0.9)

    return _clamp(DEFAULT_PROFILE_SCORE + signal * 0.5)


def _adjust_skin_test_axis_score(
    score: float,
    strength: str | None,
    *,
    manual_conflict: bool = False,
) -> float:
    strength_multiplier = SKIN_TEST_AXIS_STRENGTH_MULTIPLIERS.get(strength or "", 0.6)
    adjusted = _adjust_score_by_multiplier(score, strength_multiplier)
    if manual_conflict:
        adjusted = _adjust_score_by_multiplier(adjusted, 0.5)
    return adjusted


def _sensitive_safety_score(risk_flags: tuple[RiskFlag, ...]) -> float:
    most_severe = _most_severe_risk(risk_flags)
    if most_severe == "high":
        return 0.3
    if most_severe == "medium":
        return 0.55
    if most_severe == "low":
        return 0.75
    return 0.85


def _resistant_safety_score(risk_flags: tuple[RiskFlag, ...]) -> float:
    most_severe = _most_severe_risk(risk_flags)
    if most_severe == "high":
        return 0.65
    if most_severe == "medium":
        return 0.8
    if most_severe == "low":
        return 0.9
    return 0.95


def _score_relative_affordability(price: int, price_context: _PriceScoreContext) -> float:
    if price <= 0 or price_context.max_price <= price_context.min_price:
        return DEFAULT_PROFILE_SCORE
    ratio = (price - price_context.min_price) / (price_context.max_price - price_context.min_price)
    return _clamp(1.0 - ratio)


def _is_value_oriented(skin_test_context: SkinTestScoringContext | None) -> bool:
    if skin_test_context is None:
        return False
    return (
        _commerce_code(skin_test_context, "buying_criteria") in VALUE_ORIENTED_BUYING_CRITERIA
        or _commerce_code(skin_test_context, "price_investment") in VALUE_ORIENTED_PRICE_INVESTMENTS
    )


def _axis_winner(skin_test_context: SkinTestScoringContext, axis: str) -> str | None:
    axis_score = skin_test_context.axis_scores.get(axis, {})
    if not isinstance(axis_score, dict):
        return None
    winner = axis_score.get("winner")
    return str(winner) if winner else None


def _axis_strength(skin_test_context: SkinTestScoringContext, axis: str) -> str | None:
    axis_score = skin_test_context.axis_scores.get(axis, {})
    if not isinstance(axis_score, dict):
        return None
    strength = axis_score.get("strength")
    return str(strength) if strength else None


def _commerce_code(skin_test_context: SkinTestScoringContext, key: str) -> str | None:
    value = skin_test_context.commerce_profile.get(key)
    if isinstance(value, dict):
        code = value.get("code")
        return str(code) if code else None
    return None


def _category_matches_preference(category_code: str, preferred_code: str) -> bool:
    aliases = {
        "toner_pad": {"toner", "pad", "toner_pad"},
        "ampoule_serum_essence": {"ampoule", "serum", "essence"},
        "lotion_cream": {"lotion", "cream"},
        "suncare": {"suncare", "sun", "sunscreen"},
    }
    return category_code in aliases.get(preferred_code, {preferred_code})


def _has_manual_skin_type_conflict(
    skin_test_context: SkinTestScoringContext,
    manual_skin_type: str | None,
    *,
    manual_skin_type_explicit: bool,
) -> bool:
    if not manual_skin_type_explicit or not manual_skin_type:
        return False
    return (
        _normalize_profile_value(manual_skin_type)
        != _normalize_profile_value(skin_test_context.mapped_skin_type)
    )


def _has_manual_sensitivity_conflict(
    skin_test_context: SkinTestScoringContext,
    manual_sensitivity: str | None,
    *,
    manual_sensitivity_explicit: bool,
) -> bool:
    if not manual_sensitivity_explicit or not manual_sensitivity:
        return False
    return (
        _normalize_profile_value(manual_sensitivity)
        != _normalize_profile_value(skin_test_context.mapped_sensitivity)
    )


def _build_score_evidence(
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
) -> tuple[ScoreEvidence, ...]:
    score_evidence: list[ScoreEvidence] = []
    for contributions in contributions_by_effect.values():
        for contribution in contributions:
            ingredient = contribution.ingredient
            evidence = ingredient.evidence
            contribution_score = _round_component(contribution.effect_component)
            reason = f"{ingredient.ingredient_name} 성분이 {ingredient.effect_name} 효능에 기여"
            score_evidence.append(
                ScoreEvidence(
                    ingredient_id=ingredient.ingredient_id,
                    effect_id=ingredient.effect_id,
                    evidence_id=evidence.evidence_id if evidence else None,
                    ingredient_name=ingredient.ingredient_name,
                    effect_name=ingredient.effect_name,
                    evidence_level=evidence.evidence_level if evidence else None,
                    contribution_score=contribution_score,
                    reason=reason,
                )
            )

    ranked_evidence = sorted(
        score_evidence,
        key=lambda evidence: -evidence.contribution_score,
    )
    return tuple(ranked_evidence[:3])


def _build_reason_summary(score_evidence: tuple[ScoreEvidence, ...]) -> str:
    if not score_evidence:
        return "검색 조건과 상품 정보를 기준으로 추천 후보에 포함됐습니다."

    top = score_evidence[0]
    return f"{top.ingredient_name} 성분이 {top.effect_name} 효능 근거에 가장 크게 기여했습니다."


def _build_evidence_tags(score_evidence: tuple[ScoreEvidence, ...]) -> tuple[str, ...]:
    tags = [
        f"{evidence.effect_name}:{evidence.evidence_level or '근거확인'}"
        for evidence in score_evidence
    ]
    return _dedupe_tuple(tags)


def _build_key_ingredients(score_evidence: tuple[ScoreEvidence, ...]) -> tuple[str, ...]:
    return _dedupe_tuple([evidence.ingredient_name for evidence in score_evidence])


def _weighted_average(values: tuple[tuple[float, float], ...]) -> float:
    total_weight = sum(weight for _, weight in values if weight > 0)
    if total_weight <= 0:
        return 0.0
    return sum(score * weight for score, weight in values if weight > 0) / total_weight


def _adjust_score_by_confidence(score: float, confidence: str | None, *, baseline: float = DEFAULT_PROFILE_SCORE) -> float:
    return _adjust_score_by_multiplier(score, _confidence_multiplier(confidence), baseline=baseline)


def _adjust_score_by_multiplier(score: float, multiplier: float, *, baseline: float = DEFAULT_PROFILE_SCORE) -> float:
    return _clamp(baseline + (_clamp(score) - baseline) * _clamp(multiplier))


def _confidence_multiplier(confidence: str | None) -> float:
    normalized = confidence.strip().casefold() if confidence else None
    return CONFIDENCE_MULTIPLIERS.get(normalized, 0.0)


def _split_tags(raw_tags: str | None) -> tuple[str, ...]:
    if not raw_tags:
        return ()
    normalized = raw_tags.replace(",", ";").replace("/", ";")
    return tuple(
        tag.strip()
        for tag in normalized.split(";")
        if tag.strip()
    )


def _normalize_profile_value(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.strip().casefold().replace(" ", "")
    aliases = {
        "민감성": "민감",
        "예민함": "예민",
        "보통피부": "중성",
        "normal": "중성",
        "dry": "건성",
        "oily": "지성",
        "combination": "복합성",
        "sensitive": "민감",
    }
    return aliases.get(normalized, normalized)


def _dedupe_tuple(values: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return tuple(deduped)


def _decimal_to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _optional_decimal_to_float(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _round_component(value: float) -> float:
    return round(_clamp(value), 4)


def _round_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)
