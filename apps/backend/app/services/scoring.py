from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductIngredient
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect, IngredientEvidence, RiskFlag
from app.services.product_candidates import ProductCandidate
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent
from app.services.search_matching import SearchMatch


SCORING_VERSION = "v0"
EFFECT_CAP = 1.2
TOP_INGREDIENT_DECAYS = (1.0, 0.5, 0.25)
PRIORITY_EFFECT_MULTIPLIER = 1.25
DEFAULT_PROFILE_SCORE = 0.5


@dataclass(frozen=True)
class ScoreWeights:
    ingredient_effect: float = 0.45
    ingredient_evidence: float = 0.35
    skin_profile: float = 0.10
    search_match: float = 0.05
    price: float = 0.05


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


@dataclass(frozen=True)
class _EffectContribution:
    ingredient: _IngredientEffectInfo
    decay: float
    effect_component: float
    evidence_component: float


def score_candidates(
    session: Session,
    intent: RecommendationIntent,
    candidates: list[ProductCandidate],
    matches: list[SearchMatch],
    *,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    weights: ScoreWeights = ScoreWeights(),
    skin_profile_weights: SkinProfileWeights = SkinProfileWeights(),
) -> list[ScoredProduct]:
    if not candidates:
        return []

    desired_effects = _build_desired_effects(intent)
    product_ids = [candidate.db_product_id for candidate in candidates]
    ingredients_by_product = _load_ingredient_effects(session, product_ids, desired_effects)
    skin_tags_by_product = _load_skin_tags(session, product_ids)
    risk_flags_by_product = _load_risk_flags(session, product_ids)
    matches_by_product_code = {match.product_id: match for match in matches}

    scored_products = [
        _score_candidate(
            candidate,
            desired_effects,
            ingredients_by_product.get(candidate.db_product_id, ()),
            skin_tags_by_product.get(candidate.db_product_id, ()),
            risk_flags_by_product.get(candidate.db_product_id, ()),
            matches_by_product_code.get(candidate.product_id),
            intent.purchase_conditions,
            skin_type=skin_type,
            sensitivity=sensitivity,
            weights=weights,
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
    ingredients: tuple[_IngredientEffectInfo, ...],
    skin_tags: tuple[str, ...],
    risk_flags: tuple[RiskFlag, ...],
    match: SearchMatch | None,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    skin_type: str | None,
    sensitivity: str | None,
    weights: ScoreWeights,
    skin_profile_weights: SkinProfileWeights,
) -> ScoredProduct:
    contributions_by_effect = _build_contributions_by_effect(ingredients)
    ingredient_effect_score = _score_ingredient_effects(desired_effects, contributions_by_effect)
    ingredient_evidence_score = _score_ingredient_evidence(desired_effects, contributions_by_effect)
    skin_type_score = _score_skin_type(skin_type, skin_tags)
    sensitivity_score = _score_sensitivity(sensitivity, skin_tags, risk_flags)
    skin_profile_score = _weighted_average(
        (
            (skin_type_score, skin_profile_weights.skin_type),
            (sensitivity_score, skin_profile_weights.sensitivity),
        )
    )
    search_match_score = match.search_match_score if match else 0.0
    price_score = _score_price(candidate.lowest_price, purchase_conditions)
    risk_penalty = 0.0

    raw_score = (
        ingredient_effect_score * weights.ingredient_effect
        + ingredient_evidence_score * weights.ingredient_evidence
        + skin_profile_score * weights.skin_profile
        + search_match_score * weights.search_match
        + price_score * weights.price
    )
    total_score = _round_score(_clamp(raw_score) * 100 - risk_penalty)
    score_evidence = _build_score_evidence(contributions_by_effect)
    score_breakdown = {
        "scoring_version": SCORING_VERSION,
        "ingredient_effect_score": _round_component(ingredient_effect_score),
        "ingredient_evidence_score": _round_component(ingredient_evidence_score),
        "skin_profile_score": _round_component(skin_profile_score),
        "skin_type_score": _round_component(skin_type_score),
        "sensitivity_score": _round_component(sensitivity_score),
        "search_match_score": _round_component(search_match_score),
        "price_score": _round_component(price_score),
        "risk_penalty": risk_penalty,
        "risk_policy": "display_only",
        "risk_flag_count": len(risk_flags),
        "weights": {
            "ingredient_effect": weights.ingredient_effect,
            "ingredient_evidence": weights.ingredient_evidence,
            "skin_profile": weights.skin_profile,
            "search_match": weights.search_match,
            "price": weights.price,
        },
        "skin_profile_weights": {
            "skin_type": skin_profile_weights.skin_type,
            "sensitivity": skin_profile_weights.sensitivity,
        },
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
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .join(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .join(Effect, IngredientEffect.effect_id == Effect.id)
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
            )

    ingredients_by_product: dict[int, list[_IngredientEffectInfo]] = {}
    for info in grouped.values():
        ingredients_by_product.setdefault(info.product_db_id, []).append(info)

    return {
        product_id: tuple(ingredients)
        for product_id, ingredients in ingredients_by_product.items()
    }


def _row_to_evidence(row) -> _EvidenceInfo | None:
    if row.evidence_id is None:
        return None
    return _EvidenceInfo(
        evidence_id=int(row.evidence_id),
        evidence_score=_decimal_to_float(row.evidence_score),
        evidence_level=row.evidence_level,
        summary=row.summary,
    )


def _is_better_evidence(candidate: _EvidenceInfo | None, existing: _EvidenceInfo | None) -> bool:
    if candidate is None:
        return False
    if existing is None:
        return True
    return candidate.evidence_score > existing.evidence_score


def _load_skin_tags(session: Session, product_ids: list[int]) -> dict[int, tuple[str, ...]]:
    rows = session.execute(
        select(Product.id, Product.skin_type_tags).where(Product.id.in_(product_ids))
    ).all()
    return {
        int(row.id): _split_tags(row.skin_type_tags)
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
    return (evidence.evidence_score / 100) * decay


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


def _score_skin_type(skin_type: str | None, skin_tags: tuple[str, ...]) -> float:
    normalized_skin_type = _normalize_profile_value(skin_type) or "중성"
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
) -> float:
    normalized_sensitivity = _normalize_profile_value(sensitivity) or "보통"
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


def _most_severe_risk(risk_flags: tuple[RiskFlag, ...]) -> str | None:
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    severities = [flag.severity for flag in risk_flags if flag.severity in severity_rank]
    if not severities:
        return None
    return max(severities, key=lambda severity: severity_rank[severity])


def _score_price(price: int, purchase_conditions: ParsedPurchaseConditions) -> float:
    has_price_condition = (
        purchase_conditions.price_min is not None
        or purchase_conditions.price_max is not None
    )
    if not has_price_condition:
        return DEFAULT_PROFILE_SCORE
    if purchase_conditions.price_min is not None and price < purchase_conditions.price_min:
        return 0.0
    if purchase_conditions.price_max is not None and price > purchase_conditions.price_max:
        return 0.0
    return 1.0


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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _round_component(value: float) -> float:
    return round(_clamp(value), 4)


def _round_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)
