from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice, ProductSkinProfile
from app.db.models.commerce import Cart, CartItem, Order, OrderItem, ProductPopularityMetric, RecentView, Wishlist
from app.db.models.events import EventLog
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationFeature,
    ProductRecommendationScoringSnapshot,
    UserPreferenceProfile,
)
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
from app.services.recommendation_feature_versions import (
    PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
    RECOMMENDATION_SCORING_SNAPSHOT_VERSION,
    USER_PREFERENCE_PROFILE_VERSION,
)
from app.services.recommendation_scoring_snapshot import (
    RecommendationScoringSnapshotPayload,
    RecommendationScoringSnapshotPayloadError,
)
from app.services.review_rollup import REVIEW_SCORE_VERSION
from app.services.scoring_policy import (
    DEFAULT_INGREDIENT_EFFECT_WEIGHT,
    EFFECT_CAP,
    TOP_INGREDIENT_DECAYS,
)
from app.services.search_matching import SearchMatch


SCORING_VERSION = "v7_review_quality_v3"
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
BEHAVIOR_PERSONALIZATION_LOOKBACK_DAYS = 90
BEHAVIOR_PERSONALIZATION_RECENT_LIMIT = 100
BEHAVIOR_POSITIVE_SOURCE_WEIGHTS = {
    "wishlist": 0.30,
    "cart": 0.22,
    "purchase": 0.20,
    "recent_view": 0.13,
    "click": 0.10,
}
BEHAVIOR_NEGATIVE_GUARD_WEIGHT = 0.05
BEHAVIOR_AFFINITY_COMPONENT_WEIGHTS = {
    "effect": 0.32,
    "ingredient": 0.23,
    "category": 0.20,
    "price_band": 0.15,
    "brand": 0.10,
}
BEHAVIOR_ACTION_WEIGHTS = {
    "wishlist": 1.00,
    "cart": 1.20,
    "purchase": 1.35,
    "recent_view": 0.45,
    "click": 0.55,
    "negative_feedback": 0.60,
}
BEHAVIOR_POSITIVE_EVENT_NAMES = {
    "recommendation_product_click",
    "search_result_click",
    "home_product_click",
}
BEHAVIOR_NEGATIVE_EVENT_NAMES = {
    "wishlist_removed",
    "cart_removed",
}
BEHAVIOR_POSITIVE_ORDER_STATUSES = {
    "PAID",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
}
BEHAVIOR_POSITIVE_ORDER_ITEM_STATUSES = {
    "ORDERED",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
}
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
    "review_quality": (1.00, 1.485),
    "review_profile_affinity": (1.00, 1.84),
}
REVIEW_WEIGHT_SHARE_CAP = 0.18
REVIEW_SEGMENT_MIN_EFFECTIVE_SAMPLE_SIZE = 5.0
# review-scoring-revision 4.3: 올리브영 프로필에 민감도 축이 없어(피부타입 값 '민감성'만 존재)
# SENSITIVITY는 low/medium 세그먼트가 구조적으로 생성 불가(G4). 이진 신호로 격하하고
# 타깃이 없는 사용자는 가중 재정규화에서 차원 자체를 제외한다.
REVIEW_AFFINITY_DIMENSION_WEIGHTS = {
    "SKIN_TYPE": 0.45,
    "SENSITIVITY": 0.15,
    "SKIN_CONCERN": 0.40,
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
    "behavior_personalization",
    "review_quality",
    "review_profile_affinity",
)
VALUE_ORIENTED_BUYING_CRITERIA = {"value"}
VALUE_ORIENTED_PRICE_INVESTMENTS = {"daily_repeat_value", "value_volume"}
PIGMENT_EFFECT_CODES = ("effect_brightening",)
WRINKLE_EFFECT_CODES = ("effect_wrinkle",)


@dataclass(frozen=True)
class ScoreWeights:
    ingredient_effect: float = DEFAULT_INGREDIENT_EFFECT_WEIGHT
    ingredient_evidence: float = 0.18
    skin_profile: float = 0.11
    concentration_fit: float = 0.07
    functional_claim: float = 0.04
    search_match: float = 0.06
    price: float = 0.03
    market_signal: float = 0.02
    skin_test_context: float = 0.04
    behavior_personalization: float = 0.07
    review_quality: float = 0.07
    review_profile_affinity: float = 0.05


DEFAULT_SCORE_WEIGHTS = ScoreWeights()
SEARCH_INTENT_SCORE_WEIGHTS = ScoreWeights(
    ingredient_effect=0.2385046729,
    ingredient_evidence=0.1562616822,
    skin_profile=0.1151401869,
    concentration_fit=0.0657943925,
    functional_claim=0.0411214953,
    search_match=0.1233644860,
    price=0.0328971963,
    market_signal=0.0164485981,
    skin_test_context=0.0411214953,
    behavior_personalization=0.0493457944,
    review_quality=0.07,
    review_profile_affinity=0.05,
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
    behavior_personalization: float = 1.0
    review_quality: float = 1.0
    review_profile_affinity: float = 1.0


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
class BehaviorPersonalizationContext:
    user_id: int
    source_profiles: dict[str, "_BehaviorPreferenceProfile"]
    negative_profile: "_BehaviorPreferenceProfile | None"
    source_event_counts: dict[str, int]


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


@dataclass(frozen=True)
class _ReviewMetricInfo:
    review_quality_score: float
    confidence: float
    effective_sample_size: float
    review_count: int


@dataclass(frozen=True)
class _ReviewSegmentInfo:
    dimension: str
    value_code: str
    total_affinity_score: float
    effective_sample_size: float
    review_count: int


@dataclass(frozen=True)
class _ReviewAffinityTarget:
    dimension: str
    value_code: str
    strength: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class _ReviewMatchedSegment:
    dimension: str
    value_code: str
    strength: float
    segment_score: float
    applied_score: float
    effective_sample_size: float
    review_count: int
    eligible: bool
    sources: tuple[str, ...]


@dataclass(frozen=True)
class _ReviewProfileAffinityScore:
    score: float
    applied: bool
    dimension_scores: dict[str, float]
    matched_segments: tuple[_ReviewMatchedSegment, ...]


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
class _BehaviorPreferenceProfile:
    product_ids: tuple[int, ...]
    category_scores: dict[str, float]
    brand_scores: dict[str, float]
    ingredient_scores: dict[str, float]
    effect_scores: dict[str, float]
    price_band_scores: dict[str, float]
    total_weight: float
    effect_top3_sum: float
    ingredient_top5_sum: float
    category_max: float
    brand_max: float
    price_band_max: float


@dataclass(frozen=True)
class _BehaviorEvent:
    product_db_id: int
    source: str
    occurred_at: datetime | None
    weight: float


@dataclass(frozen=True)
class _BehaviorProductSignals:
    product_db_id: int
    category_code: str
    brand_code: str
    ingredient_codes: tuple[str, ...]
    effect_codes: tuple[str, ...]
    price_band: str | None


@dataclass(frozen=True)
class ProductRecommendationFeatureSource:
    product_db_id: int
    product_ingredient_id: int
    display_order: int | None
    ingredient_code: str | None
    effect_code: str | None
    effect_score: float


@dataclass(frozen=True)
class ProductRecommendationFeatureValues:
    top_ingredient_codes: tuple[str, ...]
    top_effect_codes: tuple[str, ...]


@dataclass(frozen=True)
class _CandidateScoringBundle:
    product_feature: ProductRecommendationFeatureValues | None
    functional_info: _FunctionalInfo
    skin_tags: tuple[str, ...]
    skin_profile: _SkinProfileInfo | None
    market_signal: _MarketSignalInfo | None
    review_metric: _ReviewMetricInfo | None


class _RiskFlagLike(Protocol):
    risk_type: str
    display_text: str
    severity: str
    severity_score: Decimal | float | None
    applies_to: str | None


@dataclass(frozen=True)
class _SnapshotScoringInputs:
    bundles: dict[int, _CandidateScoringBundle]
    effect_features: dict[
        int,
        dict[str, "ProductEffectRecommendationFeatureValues"],
    ]
    risk_flags: dict[int, tuple[_RiskFlagLike, ...]]
    review_segments: dict[int, dict[tuple[str, str], _ReviewSegmentInfo]]
    hit_ids: set[int]
    miss_ids: set[int]
    parse_error_count: int


@dataclass(frozen=True)
class ProductEffectRecommendationFeatureValues:
    effect_code: str
    ingredient_effect_score: float
    ingredient_evidence_score: float
    concentration_score: float
    concentration_context: dict[str, object]
    top_ingredient_ids: tuple[int, ...]
    best_evidence_ids: tuple[int, ...]


@dataclass(frozen=True)
class _BehaviorPersonalizationScore:
    score: float
    source_scores: dict[str, float]
    affinity_components: dict[str, float]
    matched_sources: tuple[str, ...]
    negative_guard_score: float


@dataclass(frozen=True)
class _EffectContribution:
    ingredient: _IngredientEffectInfo
    decay: float
    effect_component: float


@dataclass(frozen=True)
class _EvidenceContribution:
    ingredient: _IngredientEffectInfo
    decay: float
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


def load_behavior_personalization_context(
    session: Session,
    user_id: int | None,
    *,
    diagnostics: dict[str, object] | None = None,
) -> BehaviorPersonalizationContext | None:
    if user_id is None:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "user_profile_load_ms": 0.0,
                    "user_profile_hit": False,
                }
            )
        return None

    profile_load_started_at = current_time()
    profile_rows = session.execute(
        select(UserPreferenceProfile)
        .where(UserPreferenceProfile.user_id == user_id)
        .order_by(UserPreferenceProfile.source.asc())
    ).scalars().all()
    profile_load_ms = round(elapsed_ms(profile_load_started_at), 2)
    profile_hit = bool(profile_rows) and all(
        row.profile_version == USER_PREFERENCE_PROFILE_VERSION
        for row in profile_rows
    )
    if diagnostics is not None:
        diagnostics.update(
            {
                "user_profile_load_ms": profile_load_ms,
                "user_profile_hit": profile_hit,
            }
        )
    if profile_hit:
        return _behavior_context_from_preference_profiles(user_id, profile_rows)

    fallback_started_at = current_time()
    now = datetime.now(UTC)
    positive_events, negative_events = load_behavior_events(session, user_id, now)
    if not positive_events and not negative_events:
        _record_legacy_fallback(
            diagnostics,
            elapsed_ms(fallback_started_at),
            count=1,
        )
        return None

    product_ids = sorted({
        event.product_db_id
        for event in (*positive_events, *negative_events)
    })
    signals_by_product = load_behavior_product_signals(session, product_ids)
    source_profiles: dict[str, _BehaviorPreferenceProfile] = {}
    source_event_counts: dict[str, int] = {}
    for source in BEHAVIOR_POSITIVE_SOURCE_WEIGHTS:
        source_events = [
            event
            for event in positive_events
            if event.source == source and event.product_db_id in signals_by_product
        ]
        if not source_events:
            continue
        source_profiles[source] = build_behavior_preference_profile(source_events, signals_by_product, now)
        source_event_counts[source] = len(source_events)

    negative_profile = None
    valid_negative_events = [
        event
        for event in negative_events
        if event.product_db_id in signals_by_product
    ]
    if valid_negative_events:
        negative_profile = build_behavior_preference_profile(valid_negative_events, signals_by_product, now)
        source_event_counts["negative_feedback"] = len(valid_negative_events)

    if not source_profiles and negative_profile is None:
        _record_legacy_fallback(
            diagnostics,
            elapsed_ms(fallback_started_at),
            count=1,
        )
        return None

    context = BehaviorPersonalizationContext(
        user_id=user_id,
        source_profiles=source_profiles,
        negative_profile=negative_profile,
        source_event_counts=source_event_counts,
    )
    _record_legacy_fallback(
        diagnostics,
        elapsed_ms(fallback_started_at),
        count=1,
    )
    return context


def _behavior_context_from_preference_profiles(
    user_id: int,
    rows: list[UserPreferenceProfile],
) -> BehaviorPersonalizationContext:
    source_profiles: dict[str, _BehaviorPreferenceProfile] = {}
    negative_profile = None
    source_event_counts: dict[str, int] = {}
    for row in rows:
        profile = _behavior_preference_profile_from_row(row)
        source_event_counts[row.source] = int(row.event_count)
        if row.source == "negative_feedback":
            negative_profile = profile
        else:
            source_profiles[row.source] = profile
    return BehaviorPersonalizationContext(
        user_id=user_id,
        source_profiles=source_profiles,
        negative_profile=negative_profile,
        source_event_counts=source_event_counts,
    )


def _behavior_preference_profile_from_row(
    row: UserPreferenceProfile,
) -> _BehaviorPreferenceProfile:
    return _BehaviorPreferenceProfile(
        product_ids=tuple(int(product_id) for product_id in row.product_ids or ()),
        category_scores=_float_score_mapping(row.category_scores),
        brand_scores=_float_score_mapping(row.brand_scores),
        ingredient_scores=_float_score_mapping(row.ingredient_scores),
        effect_scores=_float_score_mapping(row.effect_scores),
        price_band_scores=_float_score_mapping(row.price_band_scores),
        total_weight=_decimal_to_float(row.total_weight),
        effect_top3_sum=_decimal_to_float(row.effect_top3_sum),
        ingredient_top5_sum=_decimal_to_float(row.ingredient_top5_sum),
        category_max=_decimal_to_float(row.category_max),
        brand_max=_decimal_to_float(row.brand_max),
        price_band_max=_decimal_to_float(row.price_band_max),
    )


def _float_score_mapping(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _decimal_to_float(score)
        for key, score in value.items()
    }


def _record_legacy_fallback(
    diagnostics: dict[str, object] | None,
    duration_ms: float,
    *,
    count: int,
) -> None:
    if diagnostics is None:
        return
    diagnostics["legacy_fallback_ms"] = round(
        float(diagnostics.get("legacy_fallback_ms", 0.0)) + duration_ms,
        2,
    )
    diagnostics["legacy_fallback_count"] = (
        int(diagnostics.get("legacy_fallback_count", 0)) + count
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
    behavior_personalization_context: BehaviorPersonalizationContext | None = None,
    saved_concerns: tuple[str, ...] = (),
    manual_skin_type_explicit: bool = False,
    manual_sensitivity_explicit: bool = False,
    weights: ScoreWeights = DEFAULT_SCORE_WEIGHTS,
    concentration_policy: ConcentrationScorePolicy = ConcentrationScorePolicy(),
    skin_profile_weights: SkinProfileWeights = SkinProfileWeights(),
    result_limit: int | None = None,
    diagnostics: dict[str, object] | None = None,
) -> list[ScoredProduct]:
    if diagnostics is not None:
        diagnostics.setdefault("user_profile_load_ms", 0.0)
        diagnostics.setdefault("user_profile_hit", False)
        diagnostics.setdefault("legacy_fallback_ms", 0.0)
        diagnostics.setdefault("legacy_fallback_count", 0)
    if not candidates:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "scoring_data_prefetch_ms": 0.0,
                    "score_context_build_ms": 0.0,
                    "score_loop_ms": 0.0,
                    "score_sort_ms": 0.0,
                    "score_detail_materialization_ms": 0.0,
                    "score_detail_count": 0,
                    "candidate_bundle_load_ms": 0.0,
                    "product_feature_load_ms": 0.0,
                    "product_feature_hit_count": 0,
                    "product_feature_miss_count": 0,
                    "effect_feature_load_ms": 0.0,
                    "effect_feature_hit_count": 0,
                    "effect_feature_miss_count": 0,
                    "scoring_snapshot_load_ms": 0.0,
                    "scoring_snapshot_hit_count": 0,
                    "scoring_snapshot_miss_count": 0,
                    "scoring_snapshot_fallback_ms": 0.0,
                    "scoring_snapshot_parse_error_count": 0,
                    "user_profile_load_ms": float(
                        diagnostics.get("user_profile_load_ms", 0.0)
                    ),
                    "user_profile_hit": bool(
                        diagnostics.get("user_profile_hit", False)
                    ),
                    "legacy_fallback_ms": float(
                        diagnostics.get("legacy_fallback_ms", 0.0)
                    ),
                    "legacy_fallback_count": int(
                        diagnostics.get("legacy_fallback_count", 0)
                    ),
                    "scoring_prefetch_breakdown": {},
                    "scoring_prefetch_detail": {},
                    "score_loop_breakdown": {},
                    "score_detail_breakdown": {},
                    "scoring_counts": {
                        "prefetch_product_count": 0,
                        "ingredient_effect_product_count": 0,
                        "functional_info_count": 0,
                        "skin_tag_product_count": 0,
                        "skin_profile_product_count": 0,
                        "risk_flag_product_count": 0,
                        "market_signal_count": 0,
                        "review_metric_count": 0,
                        "review_segment_product_count": 0,
                        "review_segment_count": 0,
                        "behavior_signal_count": 0,
                    },
                }
            )
        return []

    desired_effects = _build_desired_effects(intent)
    priority_effect_codes = tuple(effect.effect_id for effect in intent.priority_effects)
    product_ids = list(
        dict.fromkeys(candidate.db_product_id for candidate in candidates)
    )

    prefetch_started_at = current_time()
    prefetch_breakdown: dict[str, float] = {}

    stage_started_at = current_time()
    snapshot_inputs = _load_recommendation_scoring_snapshots(
        session,
        product_ids,
        desired_effects,
    )
    snapshot_load_ms = round(elapsed_ms(stage_started_at), 2)
    prefetch_breakdown["snapshot_load_ms"] = snapshot_load_ms

    snapshot_fallback_started_at = current_time()
    fallback_candidates = [
        candidate
        for candidate in candidates
        if candidate.db_product_id in snapshot_inputs.miss_ids
    ]
    stage_started_at = current_time()
    fallback_bundles, product_feature_miss_ids = _load_candidate_scoring_bundles(
        session,
        fallback_candidates,
    )
    candidate_bundle_load_ms = round(elapsed_ms(stage_started_at), 2)
    product_feature_load_ms = round(
        snapshot_load_ms + candidate_bundle_load_ms,
        2,
    )
    prefetch_breakdown["candidate_bundle_ms"] = candidate_bundle_load_ms
    candidate_bundles = dict(snapshot_inputs.bundles)
    candidate_bundles.update(fallback_bundles)
    product_features_by_product = {
        product_id: bundle.product_feature
        for product_id, bundle in candidate_bundles.items()
        if bundle.product_feature is not None
    }
    functional_info_by_product = {
        product_id: bundle.functional_info
        for product_id, bundle in candidate_bundles.items()
    }
    skin_tags_by_product = {
        product_id: bundle.skin_tags
        for product_id, bundle in candidate_bundles.items()
    }
    skin_profiles_by_product = {
        product_id: bundle.skin_profile
        for product_id, bundle in candidate_bundles.items()
        if bundle.skin_profile is not None
    }
    market_signals_by_product = {
        product_id: bundle.market_signal
        for product_id, bundle in candidate_bundles.items()
        if bundle.market_signal is not None
    }
    review_metrics_by_product = {
        product_id: bundle.review_metric
        for product_id, bundle in candidate_bundles.items()
        if bundle.review_metric is not None
    }

    stage_started_at = current_time()
    (
        fallback_effect_features,
        effect_feature_miss_ids,
        fallback_effect_feature_hit_count,
    ) = _load_product_effect_recommendation_features(
        session,
        sorted(snapshot_inputs.miss_ids - product_feature_miss_ids),
        desired_effects,
    )
    effect_feature_load_ms = round(elapsed_ms(stage_started_at), 2)
    prefetch_breakdown["effect_features_ms"] = effect_feature_load_ms
    effect_features_by_product = dict(snapshot_inputs.effect_features)
    effect_features_by_product.update(fallback_effect_features)
    effect_feature_hit_count = (
        len(snapshot_inputs.hit_ids) + fallback_effect_feature_hit_count
    )

    legacy_fallback_ids = product_feature_miss_ids | effect_feature_miss_ids
    legacy_started_at = current_time()
    ingredient_effect_detail: dict[str, float | int] = {}
    legacy_ingredients_by_product = _load_ingredient_effects(
        session,
        sorted(legacy_fallback_ids),
        desired_effects,
        diagnostics=ingredient_effect_detail if diagnostics is not None else None,
    )
    legacy_fallback_ms = elapsed_ms(legacy_started_at)
    _record_legacy_fallback(
        diagnostics,
        legacy_fallback_ms,
        count=len(legacy_fallback_ids),
    )

    ingredients_by_product = dict(legacy_ingredients_by_product)
    prefetch_breakdown["ingredient_effects_ms"] = round(legacy_fallback_ms, 2)

    stage_started_at = current_time()
    risk_flags_by_product: dict[int, tuple[_RiskFlagLike, ...]] = dict(
        snapshot_inputs.risk_flags
    )
    if snapshot_inputs.miss_ids:
        risk_flags_by_product.update(
            _load_risk_flags(session, sorted(snapshot_inputs.miss_ids))
        )
    prefetch_breakdown["risk_flags_ms"] = round(elapsed_ms(stage_started_at), 2)

    stage_started_at = current_time()
    review_segments_by_product = dict(snapshot_inputs.review_segments)
    if snapshot_inputs.miss_ids:
        review_segments_by_product.update(
            _load_review_segments(session, sorted(snapshot_inputs.miss_ids))
        )
    prefetch_breakdown["review_segments_ms"] = round(elapsed_ms(stage_started_at), 2)

    stage_started_at = current_time()
    behavior_signal_detail: dict[str, float | int] = {}
    if behavior_personalization_context is not None:
        behavior_signals_by_product = _build_behavior_signals_from_product_features(
            candidates,
            product_features_by_product,
        )
        behavior_fallback_ids = sorted(
            set(product_ids) - set(behavior_signals_by_product)
        )
        behavior_signals_by_product.update(
            load_behavior_product_signals(
                session,
                behavior_fallback_ids,
                diagnostics=(
                    behavior_signal_detail if diagnostics is not None else None
                ),
            )
        )
    else:
        behavior_signals_by_product = {}
    prefetch_breakdown["behavior_signals_ms"] = round(elapsed_ms(stage_started_at), 2)

    snapshot_fallback_ms = (
        round(elapsed_ms(snapshot_fallback_started_at), 2)
        if snapshot_inputs.miss_ids
        else 0.0
    )
    prefetch_breakdown["snapshot_fallback_ms"] = snapshot_fallback_ms

    prefetch_ms = round(elapsed_ms(prefetch_started_at), 2)

    context_started_at = current_time()
    price_context = _build_price_score_context(candidates)
    matches_by_product_code = {match.product_id: match for match in matches}
    weight_resolution = _resolve_score_weights(
        intent,
        weights,
        skin_test_context=skin_test_context,
        behavior_personalization_context=behavior_personalization_context,
    )
    review_affinity_targets = _build_review_affinity_targets(
        intent,
        skin_type=skin_type,
        sensitivity=sensitivity,
        skin_test_context=skin_test_context,
        saved_concerns=saved_concerns,
        manual_skin_type_explicit=manual_skin_type_explicit,
        manual_sensitivity_explicit=manual_sensitivity_explicit,
    )
    context_build_ms = round(elapsed_ms(context_started_at), 2)

    loop_started_at = current_time()
    score_loop_breakdown: dict[str, float] = {}
    scored_products = []
    for candidate in candidates:
        scored_products.append(
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
                review_metrics_by_product.get(candidate.db_product_id),
                review_segments_by_product.get(candidate.db_product_id, {}),
                review_affinity_targets,
                behavior_signals_by_product.get(candidate.db_product_id),
                (
                    effect_features_by_product.get(candidate.db_product_id, {})
                    if candidate.db_product_id not in legacy_fallback_ids
                    else None
                ),
                matches_by_product_code.get(candidate.product_id),
                intent.purchase_conditions,
                skin_type=skin_type,
                sensitivity=sensitivity,
                skin_test_context=skin_test_context,
                behavior_personalization_context=behavior_personalization_context,
                manual_skin_type_explicit=manual_skin_type_explicit,
                manual_sensitivity_explicit=manual_sensitivity_explicit,
                price_context=price_context,
                weight_resolution=weight_resolution,
                concentration_policy=concentration_policy,
                skin_profile_weights=skin_profile_weights,
                include_details=False,
                timing_accumulator=score_loop_breakdown if diagnostics is not None else None,
            )
        )
    score_loop_ms = round(elapsed_ms(loop_started_at), 2)

    sort_started_at = current_time()
    ranked_products = sorted(
        scored_products,
        key=lambda product: (-product.total_score, product.rank),
    )
    score_sort_ms = round(elapsed_ms(sort_started_at), 2)

    detail_started_at = current_time()
    detail_count = (
        len(ranked_products)
        if result_limit is None
        else min(len(ranked_products), max(0, int(result_limit)))
    )
    detail_products = ranked_products[:detail_count]
    detail_product_ids = [product.db_product_id for product in detail_products]
    detail_precomputed_ids = sorted(
        set(detail_product_ids) - legacy_fallback_ids
    )
    detail_ingredients_by_product = _load_ingredient_effects(
        session,
        detail_precomputed_ids,
        desired_effects,
    )
    ingredients_by_product.update(detail_ingredients_by_product)
    candidates_by_product_id = {
        candidate.db_product_id: candidate for candidate in candidates
    }
    detail_loop_breakdown: dict[str, float] = {}
    detailed_products_by_id: dict[int, ScoredProduct] = {}
    for scored_product in detail_products:
        candidate = candidates_by_product_id[scored_product.db_product_id]
        detailed_products_by_id[scored_product.db_product_id] = _score_candidate(
            candidate,
            desired_effects,
            priority_effect_codes,
            ingredients_by_product.get(candidate.db_product_id, ()),
            functional_info_by_product.get(candidate.db_product_id),
            skin_tags_by_product.get(candidate.db_product_id, ()),
            skin_profiles_by_product.get(candidate.db_product_id),
            risk_flags_by_product.get(candidate.db_product_id, ()),
            market_signals_by_product.get(candidate.db_product_id),
            review_metrics_by_product.get(candidate.db_product_id),
            review_segments_by_product.get(candidate.db_product_id, {}),
            review_affinity_targets,
            behavior_signals_by_product.get(candidate.db_product_id),
            (
                effect_features_by_product.get(candidate.db_product_id, {})
                if candidate.db_product_id not in legacy_fallback_ids
                else None
            ),
            matches_by_product_code.get(candidate.product_id),
            intent.purchase_conditions,
            skin_type=skin_type,
            sensitivity=sensitivity,
            skin_test_context=skin_test_context,
            behavior_personalization_context=behavior_personalization_context,
            manual_skin_type_explicit=manual_skin_type_explicit,
            manual_sensitivity_explicit=manual_sensitivity_explicit,
            price_context=price_context,
            weight_resolution=weight_resolution,
            concentration_policy=concentration_policy,
            skin_profile_weights=skin_profile_weights,
            include_details=True,
            timing_accumulator=(
                detail_loop_breakdown if diagnostics is not None else None
            ),
        )
    detail_materialization_ms = round(elapsed_ms(detail_started_at), 2)

    if diagnostics is not None:
        diagnostics.update(
            {
                "scoring_data_prefetch_ms": prefetch_ms,
                "score_context_build_ms": context_build_ms,
                "score_loop_ms": score_loop_ms,
                "score_sort_ms": score_sort_ms,
                "score_detail_materialization_ms": detail_materialization_ms,
                "score_detail_count": detail_count,
                "candidate_bundle_load_ms": candidate_bundle_load_ms,
                "product_feature_load_ms": product_feature_load_ms,
                "product_feature_hit_count": len(product_features_by_product),
                "product_feature_miss_count": len(product_feature_miss_ids),
                "effect_feature_load_ms": effect_feature_load_ms,
                "effect_feature_hit_count": effect_feature_hit_count,
                "effect_feature_miss_count": len(effect_feature_miss_ids),
                "scoring_snapshot_load_ms": snapshot_load_ms,
                "scoring_snapshot_hit_count": len(snapshot_inputs.hit_ids),
                "scoring_snapshot_miss_count": len(snapshot_inputs.miss_ids),
                "scoring_snapshot_fallback_ms": snapshot_fallback_ms,
                "scoring_snapshot_parse_error_count": (
                    snapshot_inputs.parse_error_count
                ),
                "scoring_prefetch_breakdown": prefetch_breakdown,
                "scoring_prefetch_detail": {
                    **{
                        f"ingredient_effects_{key}": value
                        for key, value in ingredient_effect_detail.items()
                    },
                    **{
                        f"behavior_signals_{key}": value
                        for key, value in behavior_signal_detail.items()
                    },
                },
                "score_loop_breakdown": {
                    key: round(value, 2)
                    for key, value in score_loop_breakdown.items()
                },
                "score_detail_breakdown": {
                    key: round(value, 2)
                    for key, value in detail_loop_breakdown.items()
                },
                "scoring_counts": {
                    "prefetch_product_count": len(product_ids),
                    "ingredient_effect_product_count": len(ingredients_by_product),
                    "functional_info_count": len(functional_info_by_product),
                    "skin_tag_product_count": len(skin_tags_by_product),
                    "skin_profile_product_count": len(skin_profiles_by_product),
                    "risk_flag_product_count": len(risk_flags_by_product),
                    "market_signal_count": len(market_signals_by_product),
                    "review_metric_count": len(review_metrics_by_product),
                    "review_segment_product_count": len(review_segments_by_product),
                    "review_segment_count": sum(len(segments) for segments in review_segments_by_product.values()),
                    "behavior_signal_count": len(behavior_signals_by_product),
                },
            }
        )

    results: list[ScoredProduct] = []
    for rank, product in enumerate(ranked_products, start=1):
        materialized = detailed_products_by_id.get(product.db_product_id, product)
        results.append(
            ScoredProduct(
                product_id=materialized.product_id,
                db_product_id=materialized.db_product_id,
                rank=rank,
                total_score=product.total_score,
                reason_summary=materialized.reason_summary,
                evidence_tags=materialized.evidence_tags,
                key_ingredients=materialized.key_ingredients,
                score_breakdown=materialized.score_breakdown,
                score_evidence=materialized.score_evidence,
            )
        )
    return results


def _score_candidate(
    candidate: ProductCandidate,
    desired_effects: tuple[_DesiredEffect, ...],
    priority_effect_codes: tuple[str, ...],
    ingredients: tuple[_IngredientEffectInfo, ...],
    functional_info: _FunctionalInfo | None,
    skin_tags: tuple[str, ...],
    skin_profile: _SkinProfileInfo | None,
    risk_flags: tuple[_RiskFlagLike, ...],
    market_signal: _MarketSignalInfo | None,
    review_metric: _ReviewMetricInfo | None,
    review_segments: dict[tuple[str, str], _ReviewSegmentInfo],
    review_affinity_targets: tuple[_ReviewAffinityTarget, ...],
    behavior_signal: _BehaviorProductSignals | None,
    precomputed_effect_features: dict[
        str,
        ProductEffectRecommendationFeatureValues,
    ]
    | None,
    match: SearchMatch | None,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    skin_type: str | None,
    sensitivity: str | None,
    skin_test_context: SkinTestScoringContext | None,
    behavior_personalization_context: BehaviorPersonalizationContext | None,
    manual_skin_type_explicit: bool,
    manual_sensitivity_explicit: bool,
    price_context: _PriceScoreContext | None,
    weight_resolution: ScoreWeightResolution,
    concentration_policy: ConcentrationScorePolicy,
    skin_profile_weights: SkinProfileWeights,
    include_details: bool,
    timing_accumulator: dict[str, float] | None = None,
) -> ScoredProduct:
    stage_started_at = current_time()
    contributions_by_effect = _build_contributions_by_effect(ingredients)
    evidence_contributions_by_effect = _build_evidence_contributions_by_effect(
        ingredients
    )
    _add_elapsed_timing(timing_accumulator, "contribution_build_ms", stage_started_at)

    stage_started_at = current_time()
    if precomputed_effect_features is None:
        ingredient_effect_score = _score_ingredient_effects(
            desired_effects,
            contributions_by_effect,
        )
        ingredient_evidence_score = _score_ingredient_evidence(
            desired_effects,
            evidence_contributions_by_effect,
        )
        concentration_result = _score_concentration_fit(
            desired_effects,
            contributions_by_effect,
            concentration_policy,
        )
    else:
        ingredient_effect_score = _score_precomputed_effect_axis(
            desired_effects,
            precomputed_effect_features,
            field="ingredient_effect_score",
            missing_score=0.0,
        )
        ingredient_evidence_score = _score_precomputed_effect_axis(
            desired_effects,
            precomputed_effect_features,
            field="ingredient_evidence_score",
            missing_score=0.0,
        )
        concentration_result = _score_precomputed_concentration_fit(
            desired_effects,
            precomputed_effect_features,
            concentration_policy,
        )
    _add_elapsed_timing(timing_accumulator, "ingredient_axis_ms", stage_started_at)

    stage_started_at = current_time()
    functional_claim_score, functional_claim_context = _score_functional_claim(
        functional_info,
        desired_effects,
        priority_effect_codes,
    )
    _add_elapsed_timing(timing_accumulator, "functional_axis_ms", stage_started_at)

    stage_started_at = current_time()
    skin_type_score = _score_skin_type(skin_type, skin_tags, skin_profile)
    sensitivity_score = _score_sensitivity(sensitivity, skin_tags, risk_flags, skin_profile)
    skin_profile_score = _weighted_average(
        (
            (skin_type_score, skin_profile_weights.skin_type),
            (sensitivity_score, skin_profile_weights.sensitivity),
        )
    )
    risk_penalty = _score_risk_penalty(sensitivity, risk_flags)
    _add_elapsed_timing(timing_accumulator, "skin_profile_axis_ms", stage_started_at)

    stage_started_at = current_time()
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
    _add_elapsed_timing(timing_accumulator, "search_price_market_axis_ms", stage_started_at)

    stage_started_at = current_time()
    review_quality_applied = (
        review_metric is not None and review_metric.effective_sample_size > 0.0
    )
    review_quality_score = (
        _clamp(review_metric.review_quality_score)
        if review_quality_applied
        else 0.5
    )
    review_profile_affinity = _score_review_profile_affinity(
        review_segments,
        review_affinity_targets,
    )
    _add_elapsed_timing(timing_accumulator, "review_axis_ms", stage_started_at)

    stage_started_at = current_time()
    skin_test_score = _score_skin_test_context(
        skin_test_context,
        intent_purchase_conditions=purchase_conditions,
        candidate=candidate,
        skin_profile=skin_profile,
        risk_flags=risk_flags,
        contributions_by_effect=contributions_by_effect,
        precomputed_effect_features=precomputed_effect_features,
        functional_info=functional_info,
        manual_skin_type=skin_type,
        manual_sensitivity=sensitivity,
        manual_skin_type_explicit=manual_skin_type_explicit,
        manual_sensitivity_explicit=manual_sensitivity_explicit,
    )
    _add_elapsed_timing(timing_accumulator, "skin_test_axis_ms", stage_started_at)

    stage_started_at = current_time()
    behavior_score = _score_behavior_personalization(
        behavior_personalization_context,
        behavior_signal,
    )
    _add_elapsed_timing(timing_accumulator, "behavior_axis_ms", stage_started_at)

    weights = weight_resolution.weights

    stage_started_at = current_time()
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
        + behavior_score.score * weights.behavior_personalization
        + review_quality_score * weights.review_quality
        + review_profile_affinity.score * weights.review_profile_affinity
    )
    total_score = _round_score(_clamp(raw_score) * 100 - risk_penalty)
    _add_elapsed_timing(timing_accumulator, "final_score_ms", stage_started_at)

    if not include_details:
        return ScoredProduct(
            product_id=candidate.product_id,
            db_product_id=candidate.db_product_id,
            rank=0,
            total_score=total_score,
            reason_summary="",
            evidence_tags=(),
            key_ingredients=(),
            score_breakdown={},
            score_evidence=(),
        )

    stage_started_at = current_time()
    score_evidence = _build_score_evidence(contributions_by_effect)
    _add_elapsed_timing(timing_accumulator, "evidence_build_ms", stage_started_at)

    stage_started_at = current_time()
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
        "review_quality_score": _round_component(review_quality_score),
        "review_quality_applied": review_quality_applied,
        "review_quality_confidence": _round_component(
            review_metric.confidence if review_metric is not None else 0.0
        ),
        "review_count": review_metric.review_count if review_metric is not None else 0,
        "review_profile_affinity_score": _round_component(
            review_profile_affinity.score
        ),
        "review_profile_affinity_applied": review_profile_affinity.applied,
        "review_profile_affinity_dimensions": {
            dimension: _round_component(score)
            for dimension, score in review_profile_affinity.dimension_scores.items()
        },
        "review_profile_matched_segments": [
            {
                "dimension": segment.dimension,
                "value_code": segment.value_code,
                "strength": _round_component(segment.strength),
                "segment_score": _round_component(segment.segment_score),
                "applied_score": _round_component(segment.applied_score),
                "effective_sample_size": round(segment.effective_sample_size, 6),
                "review_count": segment.review_count,
                "eligible": segment.eligible,
                "sources": list(segment.sources),
            }
            for segment in review_profile_affinity.matched_segments
        ],
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
        "behavior_personalization_score": _round_component(behavior_score.score),
        "behavior_personalization_applied": behavior_personalization_context is not None,
        "behavior_personalization_sources": list(behavior_score.matched_sources),
        "behavior_personalization_source_scores": {
            source: _round_component(score)
            for source, score in behavior_score.source_scores.items()
        },
        "behavior_personalization_affinity_components": {
            component: _round_component(score)
            for component, score in behavior_score.affinity_components.items()
        },
        "behavior_personalization_negative_guard_score": _round_component(
            behavior_score.negative_guard_score
        ),
        "behavior_personalization_event_counts": (
            dict(behavior_personalization_context.source_event_counts)
            if behavior_personalization_context is not None
            else {}
        ),
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
            "behavior_personalization": weights.behavior_personalization,
            "review_quality": weights.review_quality,
            "review_profile_affinity": weights.review_profile_affinity,
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
        "ingredient_effect_selection_policy": "top3_effect_score",
        "ingredient_evidence_selection_policy": (
            "independent_top3_effective_evidence_score"
        ),
        "total_score": total_score,
    }
    _add_elapsed_timing(timing_accumulator, "breakdown_build_ms", stage_started_at)

    stage_started_at = current_time()
    reason_summary = _build_reason_summary(score_evidence)
    evidence_tags = _build_evidence_tags(score_evidence)
    key_ingredients = _build_key_ingredients(score_evidence)
    _add_elapsed_timing(timing_accumulator, "summary_build_ms", stage_started_at)

    return ScoredProduct(
        product_id=candidate.product_id,
        db_product_id=candidate.db_product_id,
        rank=0,
        total_score=total_score,
        reason_summary=reason_summary,
        evidence_tags=evidence_tags,
        key_ingredients=key_ingredients,
        score_breakdown=score_breakdown,
        score_evidence=score_evidence,
    )


def _add_elapsed_timing(
    timings: dict[str, float] | None,
    key: str,
    started_at: float,
) -> None:
    if timings is None:
        return
    timings[key] = timings.get(key, 0.0) + elapsed_ms(started_at)


def _resolve_score_weights(
    intent: RecommendationIntent,
    weights: ScoreWeights,
    *,
    skin_test_context: SkinTestScoringContext | None,
    behavior_personalization_context: BehaviorPersonalizationContext | None,
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

    active_base_weights = base_weights
    if skin_test_context is None:
        active_base_weights = replace(active_base_weights, skin_test_context=0.0)
    if behavior_personalization_context is None:
        active_base_weights = replace(active_base_weights, behavior_personalization=0.0)
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
        values["review_quality"] *= 1.35
        values["review_profile_affinity"] *= 1.15
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
        values["review_quality"] *= 1.10
        values["review_profile_affinity"] *= 1.60

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
    normalized = ScoreWeights(
        **{
            field: weighted_values[field] / total
            for field in SCORE_WEIGHT_FIELDS
        }
    )
    return _cap_review_weight_share(normalized)


def _cap_review_weight_share(weights: ScoreWeights) -> ScoreWeights:
    review_total = weights.review_quality + weights.review_profile_affinity
    if review_total <= REVIEW_WEIGHT_SHARE_CAP:
        return weights
    non_review_fields = tuple(
        field
        for field in SCORE_WEIGHT_FIELDS
        if field not in {"review_quality", "review_profile_affinity"}
    )
    non_review_total = sum(getattr(weights, field) for field in non_review_fields)
    if review_total <= 0.0 or non_review_total <= 0.0:
        return weights
    review_scale = REVIEW_WEIGHT_SHARE_CAP / review_total
    non_review_scale = (1.0 - REVIEW_WEIGHT_SHARE_CAP) / non_review_total
    return replace(
        weights,
        **{
            field: (
                getattr(weights, field) * review_scale
                if field in {"review_quality", "review_profile_affinity"}
                else getattr(weights, field) * non_review_scale
            )
            for field in SCORE_WEIGHT_FIELDS
        },
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
    *,
    diagnostics: dict[str, float | int] | None = None,
) -> dict[int, tuple[_IngredientEffectInfo, ...]]:
    if not product_ids or not desired_effects:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "query_ms": 0.0,
                    "build_ms": 0.0,
                    "row_count": 0,
                    "grouped_count": 0,
                    "product_count": 0,
                }
            )
        return {}

    desired_effect_codes = [effect.effect_code for effect in desired_effects]
    query_started_at = current_time()
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
    if diagnostics is not None:
        diagnostics["query_ms"] = round(elapsed_ms(query_started_at), 2)
        diagnostics["row_count"] = len(rows)

    build_started_at = current_time()
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

    result = {
        product_id: tuple(ingredients)
        for product_id, ingredients in ingredients_by_product.items()
    }
    if diagnostics is not None:
        diagnostics["build_ms"] = round(elapsed_ms(build_started_at), 2)
        diagnostics["grouped_count"] = len(grouped)
        diagnostics["product_count"] = len(result)
    return result


def load_all_product_ingredient_effects(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[_IngredientEffectInfo, ...]]:
    if not product_ids:
        return {}
    effect_rows = session.execute(
        select(Effect.effect_code, Effect.name).order_by(Effect.id.asc())
    ).all()
    desired_effects = tuple(
        _DesiredEffect(effect_code=str(effect_code), name=str(name), weight=1.0)
        for effect_code, name in effect_rows
    )
    return _load_ingredient_effects(session, product_ids, desired_effects)


def _load_candidate_scoring_bundles(
    session: Session,
    candidates: list[ProductCandidate],
) -> tuple[dict[int, _CandidateScoringBundle], set[int]]:
    product_ids = list(
        dict.fromkeys(candidate.db_product_id for candidate in candidates)
    )
    if not product_ids:
        return {}, set()

    rows = session.execute(
        select(
            Product.id.label("product_id"),
            Product.updated_at.label("product_updated_at"),
            Product.functional_cosmetic_status,
            Product.functional_cosmetic_claims,
            Product.functional_claim_confidence,
            Product.functional_claim_basis,
            Product.skin_type_tags,
            ProductRecommendationFeature.product_id.label("feature_product_id"),
            ProductRecommendationFeature.top_ingredient_codes,
            ProductRecommendationFeature.top_effect_codes,
            ProductRecommendationFeature.feature_version,
            ProductRecommendationFeature.source_updated_at,
            ProductSkinProfile.product_id.label("skin_profile_product_id"),
            ProductSkinProfile.dry_fit,
            ProductSkinProfile.oily_fit,
            ProductSkinProfile.combination_fit,
            ProductSkinProfile.normal_fit,
            ProductSkinProfile.dehydrated_oily_fit,
            ProductSkinProfile.sensitive_fit,
            ProductSkinProfile.sensitivity_tag,
            ProductSkinProfile.confidence.label("skin_profile_confidence"),
            ProductSkinProfile.reason,
            ProductPopularityMetric.product_id.label("popularity_product_id"),
            ProductPopularityMetric.popularity_score,
            ProductReviewMetric.product_id.label("review_metric_product_id"),
            ProductReviewMetric.review_quality_score,
            ProductReviewMetric.confidence.label("review_metric_confidence"),
            ProductReviewMetric.effective_sample_size.label(
                "review_metric_effective_sample_size"
            ),
            ProductReviewMetric.review_count,
        )
        .outerjoin(
            ProductRecommendationFeature,
            ProductRecommendationFeature.product_id == Product.id,
        )
        .outerjoin(
            ProductSkinProfile,
            ProductSkinProfile.product_id == Product.id,
        )
        .outerjoin(
            ProductPopularityMetric,
            and_(
                ProductPopularityMetric.product_id == Product.id,
                ProductPopularityMetric.window_days == MARKET_SIGNAL_WINDOW_DAYS,
            ),
        )
        .outerjoin(
            ProductReviewMetric,
            and_(
                ProductReviewMetric.product_id == Product.id,
                ProductReviewMetric.score_version == REVIEW_SCORE_VERSION,
            ),
        )
        .where(Product.id.in_(product_ids))
    ).all()

    bundles: dict[int, _CandidateScoringBundle] = {}
    feature_product_ids: set[int] = set()
    for row in rows:
        product_id = int(row.product_id)
        product_feature = None
        if (
            row.feature_product_id is not None
            and row.feature_version == PRODUCT_RECOMMENDATION_FEATURE_VERSION
            and _feature_source_is_current(
                row.source_updated_at,
                row.product_updated_at,
            )
        ):
            product_feature = ProductRecommendationFeatureValues(
                top_ingredient_codes=tuple(
                    str(code) for code in row.top_ingredient_codes or ()
                ),
                top_effect_codes=tuple(
                    str(code) for code in row.top_effect_codes or ()
                ),
            )
            feature_product_ids.add(product_id)

        skin_profile = None
        if row.skin_profile_product_id is not None:
            skin_profile = _SkinProfileInfo(
                dry_fit=_decimal_to_float(row.dry_fit),
                oily_fit=_decimal_to_float(row.oily_fit),
                combination_fit=_decimal_to_float(row.combination_fit),
                normal_fit=_decimal_to_float(row.normal_fit),
                dehydrated_oily_fit=_decimal_to_float(row.dehydrated_oily_fit),
                sensitive_fit=_decimal_to_float(row.sensitive_fit),
                sensitivity_tag=row.sensitivity_tag,
                confidence=row.skin_profile_confidence,
                reason=row.reason,
            )

        market_signal = None
        if row.popularity_product_id is not None:
            market_signal = _MarketSignalInfo(
                popularity_score=_decimal_to_float(row.popularity_score),
            )

        review_metric = None
        if row.review_metric_product_id is not None:
            review_metric = _ReviewMetricInfo(
                review_quality_score=_decimal_to_float(
                    row.review_quality_score
                ),
                confidence=_decimal_to_float(row.review_metric_confidence),
                effective_sample_size=_decimal_to_float(
                    row.review_metric_effective_sample_size
                ),
                review_count=int(row.review_count),
            )

        bundles[product_id] = _CandidateScoringBundle(
            product_feature=product_feature,
            functional_info=_FunctionalInfo(
                status=row.functional_cosmetic_status,
                claims=_split_tags(row.functional_cosmetic_claims),
                claim_confidence=row.functional_claim_confidence,
                basis=row.functional_claim_basis,
            ),
            skin_tags=_split_tags(row.skin_type_tags),
            skin_profile=skin_profile,
            market_signal=market_signal,
            review_metric=review_metric,
        )

    return bundles, set(product_ids) - feature_product_ids


def _load_recommendation_scoring_snapshots(
    session: Session,
    product_ids: list[int],
    desired_effects: tuple[_DesiredEffect, ...],
) -> _SnapshotScoringInputs:
    unique_product_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if not unique_product_ids:
        return _SnapshotScoringInputs({}, {}, {}, {}, set(), set(), 0)

    rows = session.execute(
        select(ProductRecommendationScoringSnapshot).where(
            ProductRecommendationScoringSnapshot.product_id.in_(unique_product_ids)
        )
    ).scalars()
    snapshots_by_product = {int(row.product_id): row for row in rows}
    desired_effect_codes = {
        effect.effect_code for effect in desired_effects
    }
    bundles: dict[int, _CandidateScoringBundle] = {}
    effect_features: dict[
        int,
        dict[str, ProductEffectRecommendationFeatureValues],
    ] = {}
    risk_flags: dict[int, tuple[_RiskFlagLike, ...]] = {}
    review_segments: dict[
        int,
        dict[tuple[str, str], _ReviewSegmentInfo],
    ] = {}
    hit_ids: set[int] = set()
    miss_ids: set[int] = set()
    parse_error_count = 0

    for product_id in unique_product_ids:
        row = snapshots_by_product.get(product_id)
        if (
            row is None
            or row.snapshot_version != RECOMMENDATION_SCORING_SNAPSHOT_VERSION
        ):
            miss_ids.add(product_id)
            continue
        try:
            payload = RecommendationScoringSnapshotPayload.from_dict(
                row.scoring_payload
            )
            source_versions = _validate_snapshot_source_versions(
                row.source_versions,
                payload,
            )
        except (RecommendationScoringSnapshotPayloadError, TypeError, ValueError):
            parse_error_count += 1
            miss_ids.add(product_id)
            continue

        product_feature_source = source_versions["product_feature"]
        if (
            payload.product_feature is None
            or product_feature_source["feature_version"]
            != PRODUCT_RECOMMENDATION_FEATURE_VERSION
            or product_feature_source["source_current"] is not True
        ):
            miss_ids.add(product_id)
            continue

        effect_versions = source_versions["effect_features"]
        if any(
            effect_code in effect_versions
            and effect_versions[effect_code]
            != PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION
            for effect_code in desired_effect_codes
        ):
            miss_ids.add(product_id)
            continue

        bundles[product_id] = _snapshot_bundle(payload)
        effect_features[product_id] = {
            effect_code: ProductEffectRecommendationFeatureValues(
                effect_code=effect_code,
                ingredient_effect_score=feature.ingredient_effect_score,
                ingredient_evidence_score=feature.ingredient_evidence_score,
                concentration_score=feature.concentration_score,
                concentration_context=dict(feature.concentration_context),
                top_ingredient_ids=feature.top_ingredient_ids,
                best_evidence_ids=feature.best_evidence_ids,
            )
            for effect_code, feature in payload.effect_features.items()
        }
        if payload.risk_flags:
            risk_flags[product_id] = tuple(payload.risk_flags)
        if payload.review_segments:
            review_segments[product_id] = {
                (segment.dimension, segment.value_code): _ReviewSegmentInfo(
                    dimension=segment.dimension,
                    value_code=segment.value_code,
                    total_affinity_score=segment.total_affinity_score,
                    effective_sample_size=segment.effective_sample_size,
                    review_count=segment.review_count,
                )
                for segment in payload.review_segments
            }
        hit_ids.add(product_id)

    return _SnapshotScoringInputs(
        bundles=bundles,
        effect_features=effect_features,
        risk_flags=risk_flags,
        review_segments=review_segments,
        hit_ids=hit_ids,
        miss_ids=miss_ids,
        parse_error_count=parse_error_count,
    )


def _snapshot_bundle(
    payload: RecommendationScoringSnapshotPayload,
) -> _CandidateScoringBundle:
    product_feature = payload.product_feature
    if product_feature is None:
        raise RecommendationScoringSnapshotPayloadError(
            "product_feature is required for a snapshot hit"
        )
    skin_profile = payload.skin_profile
    market_signal = payload.market_signal
    review_metric = payload.review_metric
    return _CandidateScoringBundle(
        product_feature=ProductRecommendationFeatureValues(
            top_ingredient_codes=product_feature.top_ingredient_codes,
            top_effect_codes=product_feature.top_effect_codes,
        ),
        functional_info=_FunctionalInfo(
            status=payload.functional_info.status,
            claims=payload.functional_info.claims,
            claim_confidence=payload.functional_info.claim_confidence,
            basis=payload.functional_info.basis,
        ),
        skin_tags=payload.skin_tags,
        skin_profile=(
            _SkinProfileInfo(
                dry_fit=skin_profile.dry_fit,
                oily_fit=skin_profile.oily_fit,
                combination_fit=skin_profile.combination_fit,
                normal_fit=skin_profile.normal_fit,
                dehydrated_oily_fit=skin_profile.dehydrated_oily_fit,
                sensitive_fit=skin_profile.sensitive_fit,
                sensitivity_tag=skin_profile.sensitivity_tag,
                confidence=skin_profile.confidence,
                reason=skin_profile.reason,
            )
            if skin_profile is not None
            else None
        ),
        market_signal=(
            _MarketSignalInfo(popularity_score=market_signal.popularity_score)
            if market_signal is not None
            else None
        ),
        review_metric=(
            _ReviewMetricInfo(
                review_quality_score=review_metric.review_quality_score,
                confidence=review_metric.confidence,
                effective_sample_size=review_metric.effective_sample_size,
                review_count=review_metric.review_count,
            )
            if review_metric is not None
            else None
        ),
    )


def _validate_snapshot_source_versions(
    value: object,
    payload: RecommendationScoringSnapshotPayload,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RecommendationScoringSnapshotPayloadError(
            "source_versions must be an object"
        )
    product_feature = value.get("product_feature")
    effect_features = value.get("effect_features")
    if not isinstance(product_feature, dict):
        raise RecommendationScoringSnapshotPayloadError(
            "source_versions.product_feature must be an object"
        )
    if not isinstance(effect_features, dict):
        raise RecommendationScoringSnapshotPayloadError(
            "source_versions.effect_features must be an object"
        )
    feature_version = product_feature.get("feature_version")
    source_current = product_feature.get("source_current")
    if feature_version is not None and not isinstance(feature_version, str):
        raise RecommendationScoringSnapshotPayloadError(
            "source_versions.product_feature.feature_version must be a string or null"
        )
    if not isinstance(source_current, bool):
        raise RecommendationScoringSnapshotPayloadError(
            "source_versions.product_feature.source_current must be a boolean"
        )
    normalized_effect_versions: dict[str, str] = {}
    for effect_code, version in effect_features.items():
        if (
            not isinstance(effect_code, str)
            or not effect_code
            or not isinstance(version, str)
        ):
            raise RecommendationScoringSnapshotPayloadError(
                "source_versions.effect_features must map effect codes to versions"
            )
        normalized_effect_versions[effect_code] = version
    for effect_code in payload.effect_features:
        if (
            normalized_effect_versions.get(effect_code)
            != PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION
        ):
            raise RecommendationScoringSnapshotPayloadError(
                "current effect payload must have a current source version"
            )
    return {
        **value,
        "product_feature": {
            "feature_version": feature_version,
            "source_current": source_current,
        },
        "effect_features": normalized_effect_versions,
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


def _load_risk_flags(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[_RiskFlagLike, ...]]:
    if not product_ids:
        return {}
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

def _load_review_segments(
    session: Session,
    product_ids: list[int],
) -> dict[int, dict[tuple[str, str], _ReviewSegmentInfo]]:
    if not product_ids:
        return {}
    rows = session.execute(
        select(ProductReviewSegmentMetric).where(
            ProductReviewSegmentMetric.product_id.in_(product_ids),
            ProductReviewSegmentMetric.score_version == REVIEW_SCORE_VERSION,
            ProductReviewSegmentMetric.dimension.in_(
                REVIEW_AFFINITY_DIMENSION_WEIGHTS
            ),
        )
    ).scalars()
    by_product: dict[int, dict[tuple[str, str], _ReviewSegmentInfo]] = {}
    for row in rows:
        product_segments = by_product.setdefault(int(row.product_id), {})
        key = str(row.dimension), str(row.value_code)
        product_segments[key] = _ReviewSegmentInfo(
            dimension=key[0],
            value_code=key[1],
            total_affinity_score=_decimal_to_float(row.total_affinity_score),
            effective_sample_size=_decimal_to_float(row.effective_sample_size),
            review_count=int(row.review_count),
        )
    return by_product


def load_behavior_events(
    session: Session,
    user_id: int,
    now: datetime,
) -> tuple[list[_BehaviorEvent], list[_BehaviorEvent]]:
    cutoff = now - timedelta(days=BEHAVIOR_PERSONALIZATION_LOOKBACK_DAYS)
    positive_events: list[_BehaviorEvent] = []
    negative_events: list[_BehaviorEvent] = []

    wishlist_rows = session.execute(
        select(Wishlist.product_id, Wishlist.added_at)
        .where(Wishlist.user_id == user_id)
        .order_by(Wishlist.added_at.desc(), Wishlist.id.desc())
        .limit(BEHAVIOR_PERSONALIZATION_RECENT_LIMIT)
    ).all()
    for product_id, occurred_at in wishlist_rows:
        positive_events.append(
            _BehaviorEvent(
                product_db_id=int(product_id),
                source="wishlist",
                occurred_at=occurred_at,
                weight=BEHAVIOR_ACTION_WEIGHTS["wishlist"],
            )
        )

    cart_rows = session.execute(
        select(CartItem.product_id, CartItem.updated_at)
        .join(Cart, CartItem.cart_id == Cart.id)
        .where(Cart.user_id == user_id, Cart.status == "ACTIVE")
        .order_by(CartItem.updated_at.desc(), CartItem.id.desc())
        .limit(BEHAVIOR_PERSONALIZATION_RECENT_LIMIT)
    ).all()
    for product_id, occurred_at in cart_rows:
        positive_events.append(
            _BehaviorEvent(
                product_db_id=int(product_id),
                source="cart",
                occurred_at=occurred_at,
                weight=BEHAVIOR_ACTION_WEIGHTS["cart"],
            )
        )

    purchase_rows = session.execute(
        select(OrderItem.product_id, Order.ordered_at)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            Order.user_id == user_id,
            Order.status.in_(BEHAVIOR_POSITIVE_ORDER_STATUSES),
            OrderItem.status.in_(BEHAVIOR_POSITIVE_ORDER_ITEM_STATUSES),
        )
        .order_by(Order.ordered_at.desc(), OrderItem.id.desc())
        .limit(BEHAVIOR_PERSONALIZATION_RECENT_LIMIT)
    ).all()
    for product_id, occurred_at in purchase_rows:
        positive_events.append(
            _BehaviorEvent(
                product_db_id=int(product_id),
                source="purchase",
                occurred_at=occurred_at,
                weight=BEHAVIOR_ACTION_WEIGHTS["purchase"],
            )
        )

    recent_view_rows = session.execute(
        select(RecentView.product_id, RecentView.viewed_at)
        .where(RecentView.user_id == user_id, RecentView.viewed_at >= cutoff)
        .order_by(RecentView.viewed_at.desc(), RecentView.id.desc())
        .limit(BEHAVIOR_PERSONALIZATION_RECENT_LIMIT)
    ).all()
    for product_id, occurred_at in recent_view_rows:
        positive_events.append(
            _BehaviorEvent(
                product_db_id=int(product_id),
                source="recent_view",
                occurred_at=occurred_at,
                weight=BEHAVIOR_ACTION_WEIGHTS["recent_view"],
            )
        )

    event_rows = session.execute(
        select(Product.id, EventLog.event_name, EventLog.occurred_at)
        .select_from(EventLog)
        .join(Product, Product.product_code == EventLog.product_id)
        .where(
            EventLog.user_id == user_id,
            EventLog.product_id.is_not(None),
            EventLog.occurred_at >= cutoff,
            EventLog.event_name.in_(BEHAVIOR_POSITIVE_EVENT_NAMES | BEHAVIOR_NEGATIVE_EVENT_NAMES),
        )
        .order_by(EventLog.occurred_at.desc(), EventLog.id.desc())
        .limit(BEHAVIOR_PERSONALIZATION_RECENT_LIMIT)
    ).all()
    for product_id, event_name, occurred_at in event_rows:
        normalized_event_name = str(event_name)
        if normalized_event_name in BEHAVIOR_POSITIVE_EVENT_NAMES:
            positive_events.append(
                _BehaviorEvent(
                    product_db_id=int(product_id),
                    source="click",
                    occurred_at=occurred_at,
                    weight=BEHAVIOR_ACTION_WEIGHTS["click"],
                )
            )
            continue
        negative_events.append(
            _BehaviorEvent(
                product_db_id=int(product_id),
                source="negative_feedback",
                occurred_at=occurred_at,
                weight=BEHAVIOR_ACTION_WEIGHTS["negative_feedback"],
            )
        )

    return positive_events, negative_events


def load_behavior_product_signals(
    session: Session,
    product_ids: list[int],
    *,
    diagnostics: dict[str, float | int] | None = None,
) -> dict[int, _BehaviorProductSignals]:
    normalized_product_ids = sorted({int(product_id) for product_id in product_ids})
    if not normalized_product_ids:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "base_query_ms": 0.0,
                    "price_load_ms": 0.0,
                    "ingredient_query_ms": 0.0,
                    "build_ms": 0.0,
                    "base_row_count": 0,
                    "ingredient_row_count": 0,
                    "price_count": 0,
                    "product_count": 0,
                }
            )
        return {}

    base_query_started_at = current_time()
    base_rows = session.execute(
        select(Product.id, Brand.brand_code, ProductCategory.category_code)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .where(Product.id.in_(normalized_product_ids))
    ).all()
    if diagnostics is not None:
        diagnostics["base_query_ms"] = round(elapsed_ms(base_query_started_at), 2)
        diagnostics["base_row_count"] = len(base_rows)

    price_started_at = current_time()
    prices_by_product = _load_lowest_prices(session, normalized_product_ids)
    if diagnostics is not None:
        diagnostics["price_load_ms"] = round(elapsed_ms(price_started_at), 2)
        diagnostics["price_count"] = len(prices_by_product)

    ingredient_query_started_at = current_time()
    rows = session.execute(
        select(
            ProductIngredient.product_id,
            ProductIngredient.id,
            ProductIngredient.display_order,
            Ingredient.ingredient_code,
            Effect.effect_code,
            IngredientEffect.effect_score,
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .outerjoin(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .outerjoin(Effect, IngredientEffect.effect_id == Effect.id)
        .where(ProductIngredient.product_id.in_(normalized_product_ids))
        .order_by(ProductIngredient.product_id.asc(), ProductIngredient.display_order.asc(), ProductIngredient.id.asc())
    ).all()
    if diagnostics is not None:
        diagnostics["ingredient_query_ms"] = round(elapsed_ms(ingredient_query_started_at), 2)
        diagnostics["ingredient_row_count"] = len(rows)

    build_started_at = current_time()
    feature_values_by_product = build_product_recommendation_feature_values(
        tuple(
            ProductRecommendationFeatureSource(
                product_db_id=int(product_id),
                product_ingredient_id=int(product_ingredient_id),
                display_order=display_order,
                ingredient_code=str(ingredient_code) if ingredient_code else None,
                effect_code=str(effect_code) if effect_code else None,
                effect_score=_decimal_to_float(effect_score),
            )
            for (
                product_id,
                product_ingredient_id,
                display_order,
                ingredient_code,
                effect_code,
                effect_score,
            ) in rows
        )
    )

    signals: dict[int, _BehaviorProductSignals] = {}
    for product_id, brand_code, category_code in base_rows:
        normalized_product_id = int(product_id)
        feature_values = feature_values_by_product.get(
            normalized_product_id,
            ProductRecommendationFeatureValues(
                top_ingredient_codes=(),
                top_effect_codes=(),
            ),
        )
        signals[normalized_product_id] = _BehaviorProductSignals(
            product_db_id=normalized_product_id,
            category_code=str(category_code or ""),
            brand_code=str(brand_code or ""),
            ingredient_codes=feature_values.top_ingredient_codes,
            effect_codes=feature_values.top_effect_codes,
            price_band=_price_band(prices_by_product.get(normalized_product_id)),
        )
    if diagnostics is not None:
        diagnostics["build_ms"] = round(elapsed_ms(build_started_at), 2)
        diagnostics["product_count"] = len(signals)
    return signals


def _load_lowest_prices(session: Session, product_ids: list[int]) -> dict[int, int]:
    rows = session.execute(
        select(ProductPrice.product_id, ProductPrice.price)
        .where(ProductPrice.product_id.in_(product_ids))
        .order_by(ProductPrice.product_id.asc(), ProductPrice.is_lowest.desc(), ProductPrice.price.asc())
    ).all()
    prices: dict[int, int] = {}
    for product_id, price in rows:
        prices.setdefault(int(product_id), int(price or 0))
    return prices


def build_product_recommendation_feature_values(
    sources: tuple[ProductRecommendationFeatureSource, ...],
) -> dict[int, ProductRecommendationFeatureValues]:
    ingredient_codes_by_product: dict[int, list[str]] = {}
    effect_scores_by_product: dict[int, dict[str, float]] = {}
    ordered_sources = sorted(
        sources,
        key=lambda source: (
            source.product_db_id,
            source.display_order if source.display_order is not None else 999,
            source.product_ingredient_id,
            source.effect_code or "",
        ),
    )
    for source in ordered_sources:
        if source.ingredient_code:
            _append_unique_limited(
                ingredient_codes_by_product.setdefault(source.product_db_id, []),
                source.ingredient_code,
                limit=8,
            )
        if source.effect_code:
            effect_scores = effect_scores_by_product.setdefault(source.product_db_id, {})
            effect_scores[source.effect_code] = max(
                effect_scores.get(source.effect_code, 0.0),
                source.effect_score,
            )

    product_ids = set(ingredient_codes_by_product) | set(effect_scores_by_product)
    return {
        product_id: ProductRecommendationFeatureValues(
            top_ingredient_codes=tuple(ingredient_codes_by_product.get(product_id, [])),
            top_effect_codes=tuple(
                effect_code
                for effect_code, _score in sorted(
                    effect_scores_by_product.get(product_id, {}).items(),
                    key=lambda item: (-item[1], item[0]),
                )[:8]
            ),
        )
        for product_id in product_ids
    }


def _load_product_effect_recommendation_features(
    session: Session,
    product_ids: list[int],
    desired_effects: tuple[_DesiredEffect, ...],
) -> tuple[
    dict[int, dict[str, ProductEffectRecommendationFeatureValues]],
    set[int],
    int,
]:
    desired_effect_codes = [effect.effect_code for effect in desired_effects]
    if not product_ids or not desired_effect_codes:
        return {}, set(), len(product_ids)
    rows = session.execute(
        select(ProductEffectRecommendationFeature, Effect.effect_code)
        .join(Effect, ProductEffectRecommendationFeature.effect_id == Effect.id)
        .where(
            ProductEffectRecommendationFeature.product_id.in_(product_ids),
            Effect.effect_code.in_(desired_effect_codes),
        )
    ).all()
    stale_product_ids = {
        int(row.product_id)
        for row, _effect_code in rows
        if row.feature_version != PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION
    }
    features_by_product: dict[
        int,
        dict[str, ProductEffectRecommendationFeatureValues],
    ] = {}
    for row, effect_code in rows:
        product_id = int(row.product_id)
        if product_id in stale_product_ids:
            continue
        features_by_product.setdefault(product_id, {})[str(effect_code)] = (
            ProductEffectRecommendationFeatureValues(
                effect_code=str(effect_code),
                ingredient_effect_score=_decimal_to_float(
                    row.ingredient_effect_score
                ),
                ingredient_evidence_score=_decimal_to_float(
                    row.ingredient_evidence_score
                ),
                concentration_score=_decimal_to_float(row.concentration_score),
                concentration_context=dict(row.concentration_context or {}),
                top_ingredient_ids=tuple(
                    int(ingredient_id)
                    for ingredient_id in row.top_ingredient_ids or ()
                ),
                best_evidence_ids=tuple(
                    int(evidence_id)
                    for evidence_id in row.best_evidence_ids or ()
                ),
            )
        )
    return (
        features_by_product,
        stale_product_ids,
        len(product_ids) - len(stale_product_ids),
    )


def _feature_source_is_current(
    source_updated_at: datetime,
    product_updated_at: datetime,
) -> bool:
    return _normalized_datetime(source_updated_at) >= _normalized_datetime(
        product_updated_at
    )


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _build_behavior_signals_from_product_features(
    candidates: list[ProductCandidate],
    features_by_product: dict[int, ProductRecommendationFeatureValues],
) -> dict[int, _BehaviorProductSignals]:
    return {
        candidate.db_product_id: _BehaviorProductSignals(
            product_db_id=candidate.db_product_id,
            category_code=candidate.category_code,
            brand_code=candidate.brand_code,
            ingredient_codes=features_by_product[
                candidate.db_product_id
            ].top_ingredient_codes,
            effect_codes=features_by_product[
                candidate.db_product_id
            ].top_effect_codes,
            price_band=_price_band(candidate.lowest_price),
        )
        for candidate in candidates
        if candidate.db_product_id in features_by_product
    }


def build_behavior_preference_profile(
    events: list[_BehaviorEvent],
    signals_by_product: dict[int, _BehaviorProductSignals],
    now: datetime,
) -> _BehaviorPreferenceProfile:
    category_scores: dict[str, float] = {}
    brand_scores: dict[str, float] = {}
    ingredient_scores: dict[str, float] = {}
    effect_scores: dict[str, float] = {}
    price_band_scores: dict[str, float] = {}
    product_scores: dict[int, float] = {}
    total_weight = 0.0

    for event in events:
        signals = signals_by_product.get(event.product_db_id)
        if signals is None:
            continue
        event_weight = max(0.0, event.weight) * _behavior_recency_weight(event.occurred_at, now)
        if event_weight <= 0:
            continue
        total_weight += event_weight
        product_scores[event.product_db_id] = product_scores.get(event.product_db_id, 0.0) + event_weight
        _add_behavior_score(category_scores, signals.category_code, event_weight)
        _add_behavior_score(brand_scores, signals.brand_code, event_weight)
        if signals.price_band:
            _add_behavior_score(price_band_scores, signals.price_band, event_weight)
        for index, ingredient_code in enumerate(signals.ingredient_codes):
            _add_behavior_score(ingredient_scores, ingredient_code, event_weight * _behavior_rank_decay(index))
        for effect_code in signals.effect_codes:
            _add_behavior_score(effect_scores, effect_code, event_weight)

    return _BehaviorPreferenceProfile(
        product_ids=tuple(product_id for product_id, _score in sorted(product_scores.items())),
        category_scores=category_scores,
        brand_scores=brand_scores,
        ingredient_scores=ingredient_scores,
        effect_scores=effect_scores,
        price_band_scores=price_band_scores,
        total_weight=total_weight,
        effect_top3_sum=_top_score_sum(effect_scores, 3),
        ingredient_top5_sum=_top_score_sum(ingredient_scores, 5),
        category_max=max(category_scores.values(), default=0.0),
        brand_max=max(brand_scores.values(), default=0.0),
        price_band_max=max(price_band_scores.values(), default=0.0),
    )


def _score_behavior_personalization(
    context: BehaviorPersonalizationContext | None,
    signals: _BehaviorProductSignals | None,
) -> _BehaviorPersonalizationScore:
    if context is None or signals is None:
        return _BehaviorPersonalizationScore(
            score=0.0,
            source_scores={},
            affinity_components={},
            matched_sources=(),
            negative_guard_score=1.0,
        )

    source_scores: dict[str, float] = {}
    component_values: dict[str, list[tuple[float, float]]] = {}
    for source, source_weight in BEHAVIOR_POSITIVE_SOURCE_WEIGHTS.items():
        profile = context.source_profiles.get(source)
        if profile is None or profile.total_weight <= 0:
            continue
        source_score, components = _score_behavior_affinity(signals, profile)
        source_scores[source] = source_score
        for component, component_score in components.items():
            component_values.setdefault(component, []).append((component_score, source_weight))

    source_score_items = tuple(
        (source_scores[source], BEHAVIOR_POSITIVE_SOURCE_WEIGHTS[source])
        for source in BEHAVIOR_POSITIVE_SOURCE_WEIGHTS
        if source in source_scores
    )
    if source_score_items:
        positive_score = _weighted_average(source_score_items)
    elif context.negative_profile is not None:
        positive_score = 0.5
    else:
        positive_score = 0.0

    negative_guard_score = _score_behavior_negative_guard(signals, context.negative_profile)
    final_score = _clamp(
        positive_score * (1.0 - BEHAVIOR_NEGATIVE_GUARD_WEIGHT)
        + negative_guard_score * BEHAVIOR_NEGATIVE_GUARD_WEIGHT
    )
    affinity_components = {
        component: _weighted_average(tuple(scores))
        for component, scores in component_values.items()
    }
    return _BehaviorPersonalizationScore(
        score=final_score,
        source_scores=source_scores,
        affinity_components=affinity_components,
        matched_sources=tuple(source for source, score in source_scores.items() if score > 0),
        negative_guard_score=negative_guard_score,
    )


def _score_behavior_affinity(
    signals: _BehaviorProductSignals,
    profile: _BehaviorPreferenceProfile,
) -> tuple[float, dict[str, float]]:
    components = {
        "effect": _profile_set_score(
            signals.effect_codes,
            profile.effect_scores,
            normalizer=profile.effect_top3_sum,
        ),
        "ingredient": _profile_set_score(
            signals.ingredient_codes,
            profile.ingredient_scores,
            normalizer=profile.ingredient_top5_sum,
        ),
        "category": _profile_value_score(
            signals.category_code,
            profile.category_scores,
            normalizer=profile.category_max,
        ),
        "price_band": _profile_value_score(
            signals.price_band,
            profile.price_band_scores,
            normalizer=profile.price_band_max,
        ),
        "brand": _profile_value_score(
            signals.brand_code,
            profile.brand_scores,
            normalizer=profile.brand_max,
        ),
    }
    return (
        _weighted_average(
            tuple(
                (components[component], weight)
                for component, weight in BEHAVIOR_AFFINITY_COMPONENT_WEIGHTS.items()
            )
        ),
        components,
    )


def _score_behavior_negative_guard(
    signals: _BehaviorProductSignals,
    negative_profile: _BehaviorPreferenceProfile | None,
) -> float:
    if negative_profile is None or negative_profile.total_weight <= 0:
        return 1.0
    if signals.product_db_id in set(negative_profile.product_ids):
        return 0.0
    negative_affinity, _components = _score_behavior_affinity(signals, negative_profile)
    return _clamp(1.0 - negative_affinity * 0.70)


def _profile_set_score(
    candidate_values: tuple[str, ...],
    profile_scores: dict[str, float],
    *,
    normalizer: float,
) -> float:
    if not candidate_values or not profile_scores:
        return 0.0
    values = tuple(dict.fromkeys(value for value in candidate_values if value))
    matched_score = sum(profile_scores.get(value, 0.0) for value in values)
    if normalizer <= 0:
        return 0.0
    return _clamp(matched_score / normalizer)


def _profile_value_score(
    candidate_value: str | None,
    profile_scores: dict[str, float],
    *,
    normalizer: float,
) -> float:
    if not candidate_value or not profile_scores:
        return 0.0
    if normalizer <= 0:
        return 0.0
    return _clamp(profile_scores.get(candidate_value, 0.0) / normalizer)


def _top_score_sum(scores: dict[str, float], limit: int) -> float:
    return sum(sorted(scores.values(), reverse=True)[:max(1, limit)])


def _add_behavior_score(scores: dict[str, float], key: str | None, value: float) -> None:
    normalized_key = (key or "").strip()
    if not normalized_key:
        return
    scores[normalized_key] = scores.get(normalized_key, 0.0) + value


def _append_unique_limited(values: list[str], value: str, *, limit: int) -> None:
    normalized_value = value.strip()
    if not normalized_value or normalized_value in values or len(values) >= limit:
        return
    values.append(normalized_value)


def _behavior_recency_weight(occurred_at: datetime | None, now: datetime) -> float:
    if occurred_at is None:
        return 0.15
    normalized_occurred_at = occurred_at
    if normalized_occurred_at.tzinfo is None:
        normalized_occurred_at = normalized_occurred_at.replace(tzinfo=UTC)
    days = max(0, (now - normalized_occurred_at).days)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.70
    if days <= 90:
        return 0.40
    return 0.15


def _behavior_rank_decay(index: int) -> float:
    return max(0.25, 1.0 - index * 0.10)


def _price_band(price: int | None) -> str | None:
    if price is None or price <= 0:
        return None
    if price <= 15_000:
        return "under_15000"
    if price <= 30_000:
        return "15000_30000"
    if price <= 50_000:
        return "30000_50000"
    if price <= 80_000:
        return "50000_80000"
    return "over_80000"


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
            )
            for ingredient, decay in zip(ranked_ingredients, TOP_INGREDIENT_DECAYS, strict=False)
        ]
        contributions_by_effect[effect_code] = tuple(contributions)

    return contributions_by_effect


def _build_evidence_contributions_by_effect(
    ingredients: tuple[_IngredientEffectInfo, ...],
) -> dict[str, tuple[_EvidenceContribution, ...]]:
    ingredients_by_effect: dict[str, list[_IngredientEffectInfo]] = {}
    for ingredient in ingredients:
        if ingredient.evidence is None:
            continue
        ingredients_by_effect.setdefault(ingredient.effect_code, []).append(ingredient)

    contributions_by_effect: dict[str, tuple[_EvidenceContribution, ...]] = {}
    for effect_code, effect_ingredients in ingredients_by_effect.items():
        ranked_ingredients = sorted(
            effect_ingredients,
            key=lambda ingredient: (
                -_effective_evidence_score(ingredient.evidence),
                ingredient.display_order,
                ingredient.ingredient_id,
            ),
        )
        contributions_by_effect[effect_code] = tuple(
            _EvidenceContribution(
                ingredient=ingredient,
                decay=decay,
                evidence_component=_evidence_component(ingredient.evidence, decay),
            )
            for ingredient, decay in zip(
                ranked_ingredients,
                TOP_INGREDIENT_DECAYS,
                strict=False,
            )
        )

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
    contributions_by_effect: dict[str, tuple[_EvidenceContribution, ...]],
) -> float:
    weighted_scores: list[tuple[float, float]] = []
    for desired_effect in desired_effects:
        contributions = contributions_by_effect.get(desired_effect.effect_code, ())
        raw_effect_score = sum(
            contribution.evidence_component for contribution in contributions
        )
        weighted_scores.append(
            (min(raw_effect_score, EFFECT_CAP), desired_effect.weight)
        )

    return _clamp(_weighted_average(tuple(weighted_scores)))


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


def _score_precomputed_effect_axis(
    desired_effects: tuple[_DesiredEffect, ...],
    features_by_effect: dict[str, ProductEffectRecommendationFeatureValues],
    *,
    field: str,
    missing_score: float,
) -> float:
    weighted_scores = tuple(
        (
            float(getattr(features_by_effect[effect.effect_code], field))
            if effect.effect_code in features_by_effect
            else missing_score,
            effect.weight,
        )
        for effect in desired_effects
    )
    return _clamp(_weighted_average(weighted_scores))


def _score_precomputed_concentration_fit(
    desired_effects: tuple[_DesiredEffect, ...],
    features_by_effect: dict[str, ProductEffectRecommendationFeatureValues],
    policy: ConcentrationScorePolicy,
) -> _ConcentrationResult:
    if not desired_effects:
        return _ConcentrationResult(bucket="unknown", score=policy.unknown)

    weighted_scores: list[tuple[float, float]] = []
    context_results: list[_ConcentrationResult] = []
    for desired_effect in desired_effects:
        feature = features_by_effect.get(desired_effect.effect_code)
        if feature is None:
            weighted_scores.append((policy.unknown, desired_effect.weight))
            continue
        weighted_scores.append((feature.concentration_score, desired_effect.weight))
        context = feature.concentration_context
        context_results.append(
            _ConcentrationResult(
                bucket=str(context.get("bucket") or "unknown"),
                score=feature.concentration_score,
                ingredient_name=_optional_string(context.get("ingredient_name")),
                effect_name=_optional_string(context.get("effect_name")),
                concentration_text=_optional_string(
                    context.get("concentration_text")
                ),
                warning=_optional_string(context.get("warning")),
            )
        )

    aggregate_score = _clamp(_weighted_average(tuple(weighted_scores)))
    display_result = _select_display_concentration_result(context_results, policy)
    warning_result = next(
        (result for result in context_results if result.warning),
        None,
    )
    return _ConcentrationResult(
        bucket=display_result.bucket,
        score=aggregate_score,
        ingredient_name=display_result.ingredient_name,
        effect_name=display_result.effect_name,
        concentration_text=display_result.concentration_text,
        warning=warning_result.warning if warning_result else None,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def build_product_effect_recommendation_feature_values(
    ingredients: tuple[_IngredientEffectInfo, ...],
    policy: ConcentrationScorePolicy = ConcentrationScorePolicy(),
) -> dict[str, ProductEffectRecommendationFeatureValues]:
    contributions_by_effect = _build_contributions_by_effect(ingredients)
    evidence_contributions_by_effect = _build_evidence_contributions_by_effect(
        ingredients
    )
    effect_names = {
        ingredient.effect_code: ingredient.effect_name
        for ingredient in ingredients
    }
    feature_values: dict[str, ProductEffectRecommendationFeatureValues] = {}
    for effect_code in sorted(set(contributions_by_effect) | set(evidence_contributions_by_effect)):
        desired_effect = (
            _DesiredEffect(
                effect_code=effect_code,
                name=effect_names.get(effect_code, effect_code),
                weight=1.0,
            ),
        )
        effect_contributions = contributions_by_effect.get(effect_code, ())
        evidence_contributions = evidence_contributions_by_effect.get(effect_code, ())
        concentration_result = _score_concentration_fit(
            desired_effect,
            contributions_by_effect,
            policy,
        )
        feature_values[effect_code] = ProductEffectRecommendationFeatureValues(
            effect_code=effect_code,
            ingredient_effect_score=min(
                sum(
                    contribution.effect_component
                    for contribution in effect_contributions
                ),
                EFFECT_CAP,
            ),
            ingredient_evidence_score=min(
                sum(
                    contribution.evidence_component
                    for contribution in evidence_contributions
                ),
                EFFECT_CAP,
            ),
            concentration_score=concentration_result.score,
            concentration_context={
                "bucket": concentration_result.bucket,
                "ingredient_name": concentration_result.ingredient_name,
                "effect_name": concentration_result.effect_name,
                "concentration_text": concentration_result.concentration_text,
                "warning": concentration_result.warning,
            },
            top_ingredient_ids=tuple(
                contribution.ingredient.ingredient_id
                for contribution in effect_contributions
            ),
            best_evidence_ids=tuple(
                contribution.ingredient.evidence.evidence_id
                for contribution in evidence_contributions
                if contribution.ingredient.evidence is not None
            ),
        )

    return feature_values


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
    risk_flags: tuple[_RiskFlagLike, ...],
    skin_profile: _SkinProfileInfo | None,
) -> float:
    normalized_sensitivity = _normalize_sensitivity_value(sensitivity) or "보통"
    if skin_profile is not None:
        return _adjust_score_by_confidence(
            _sensitivity_profile_score(normalized_sensitivity, skin_profile),
            skin_profile.confidence,
        )

    normalized_tags = {_normalize_profile_value(tag) for tag in skin_tags}
    normalized_tags.discard("")
    most_severe = _most_severe_risk(risk_flags)

    if normalized_sensitivity == "높음":
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


def _score_risk_penalty(
    sensitivity: str | None,
    risk_flags: tuple[_RiskFlagLike, ...],
) -> float:
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


def _risk_warning_texts(
    risk_flags: tuple[_RiskFlagLike, ...],
    *,
    limit: int = 3,
) -> list[str]:
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
    normalized_sensitivity = _normalize_sensitivity_value(sensitivity) or "보통"
    return normalized_sensitivity == "높음"


def _risk_applies_to_sensitive(flag: _RiskFlagLike) -> bool:
    applies_to = {value.casefold() for value in _split_tags(flag.applies_to)}
    return "sensitive" in applies_to


def _risk_penalty_value(flag: _RiskFlagLike) -> float:
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
    sensitivity = _normalize_sensitivity_value(sensitivity) or "보통"
    sensitive_score = _clamp(skin_profile.sensitive_fit)
    if sensitivity == "높음":
        return sensitive_score
    if sensitivity == "낮음":
        return max(sensitive_score, 0.85)
    return max(sensitive_score, 0.6)


def _most_severe_risk(
    risk_flags: tuple[_RiskFlagLike, ...],
) -> str | None:
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


def _build_review_affinity_targets(
    intent: RecommendationIntent,
    *,
    skin_type: str | None,
    sensitivity: str | None,
    skin_test_context: SkinTestScoringContext | None,
    saved_concerns: tuple[str, ...],
    manual_skin_type_explicit: bool,
    manual_sensitivity_explicit: bool,
) -> tuple[_ReviewAffinityTarget, ...]:
    target_values: dict[tuple[str, str], dict[str, object]] = {}
    if manual_skin_type_explicit:
        _add_review_affinity_target(
            target_values,
            "SKIN_TYPE",
            _review_skin_type_code(skin_type),
            strength=1.0,
            source="manual_skin_type",
        )
    if manual_sensitivity_explicit:
        _add_review_affinity_target(
            target_values,
            "SENSITIVITY",
            _review_sensitivity_code(sensitivity),
            strength=1.0,
            source="manual_sensitivity",
        )
    for concern in intent.concerns:
        _add_review_affinity_target(
            target_values,
            "SKIN_CONCERN",
            concern.tag_id,
            strength=1.0,
            source="query_concern",
        )
    for concern_code in saved_concerns:
        _add_review_affinity_target(
            target_values,
            "SKIN_CONCERN",
            concern_code,
            strength=0.75,
            source="saved_concern",
        )
    if skin_test_context is not None:
        _add_review_affinity_target(
            target_values,
            "SKIN_TYPE",
            _review_skin_type_code(skin_test_context.mapped_skin_type),
            strength=0.25,
            source="skin_test",
        )
        _add_review_affinity_target(
            target_values,
            "SENSITIVITY",
            _review_sensitivity_code(skin_test_context.mapped_sensitivity),
            strength=0.25,
            source="skin_test",
        )
        if _axis_winner(skin_test_context, "SR") == "S":
            _add_review_affinity_target(
                target_values,
                "SKIN_CONCERN",
                "concern_sensitive",
                strength=0.25,
                source="skin_test",
            )
        if _axis_winner(skin_test_context, "PN") == "P":
            _add_review_affinity_target(
                target_values,
                "SKIN_CONCERN",
                "concern_brightening_spots",
                strength=0.25,
                source="skin_test",
            )
        if _axis_winner(skin_test_context, "WT") == "W":
            _add_review_affinity_target(
                target_values,
                "SKIN_CONCERN",
                "concern_wrinkle_elasticity",
                strength=0.25,
                source="skin_test",
            )

    return tuple(
        _ReviewAffinityTarget(
            dimension=dimension,
            value_code=value_code,
            strength=float(payload["strength"]),
            sources=tuple(sorted(payload["sources"])),
        )
        for (dimension, value_code), payload in sorted(target_values.items())
    )


def _add_review_affinity_target(
    target_values: dict[tuple[str, str], dict[str, object]],
    dimension: str,
    value_code: str | None,
    *,
    strength: float,
    source: str,
) -> None:
    normalized_value = (value_code or "").strip()
    if not normalized_value:
        return
    key = dimension, normalized_value
    existing = target_values.get(key)
    if existing is None:
        target_values[key] = {
            "strength": _clamp(strength),
            "sources": {source},
        }
        return
    existing["strength"] = max(float(existing["strength"]), _clamp(strength))
    sources = existing["sources"]
    if isinstance(sources, set):
        sources.add(source)


def _score_review_profile_affinity(
    segments: dict[tuple[str, str], _ReviewSegmentInfo],
    targets: tuple[_ReviewAffinityTarget, ...],
) -> _ReviewProfileAffinityScore:
    targets_by_dimension: dict[str, list[_ReviewAffinityTarget]] = {
        dimension: [] for dimension in REVIEW_AFFINITY_DIMENSION_WEIGHTS
    }
    for target in targets:
        if target.dimension in targets_by_dimension:
            targets_by_dimension[target.dimension].append(target)

    dimension_scores: dict[str, float] = {}
    matched_segments: list[_ReviewMatchedSegment] = []
    applied = False
    for dimension in REVIEW_AFFINITY_DIMENSION_WEIGHTS:
        target_scores: list[float] = []
        for target in targets_by_dimension[dimension]:
            segment = segments.get((target.dimension, target.value_code))
            if segment is None:
                target_scores.append(0.5)
                continue
            eligible = (
                segment.effective_sample_size
                >= REVIEW_SEGMENT_MIN_EFFECTIVE_SAMPLE_SIZE
            )
            segment_score = _clamp(segment.total_affinity_score)
            contribution_score = segment_score if eligible else 0.5
            applied_score = _clamp(
                0.5 + (target.strength * (contribution_score - 0.5))
            )
            target_scores.append(applied_score)
            applied = applied or eligible
            matched_segments.append(
                _ReviewMatchedSegment(
                    dimension=target.dimension,
                    value_code=target.value_code,
                    strength=target.strength,
                    segment_score=segment_score,
                    applied_score=applied_score,
                    effective_sample_size=segment.effective_sample_size,
                    review_count=segment.review_count,
                    eligible=eligible,
                    sources=target.sources,
                )
            )
        if target_scores:
            dimension_scores[dimension] = sum(target_scores) / len(target_scores)

    # review-scoring-revision 4.3: 타깃이 존재하는 차원만으로 가중 재정규화한다.
    # 비민감 사용자는 SENSITIVITY 타깃이 만들어지지 않으므로 이 차원이 자동 제외되어
    # 중립 0.5 고정으로 인한 구조적 희석이 사라진다. 전 차원 무타깃이면 중립 0.5.
    weighted_components = tuple(
        (dimension_scores[dimension], weight)
        for dimension, weight in REVIEW_AFFINITY_DIMENSION_WEIGHTS.items()
        if dimension in dimension_scores
    )
    score = (
        _weighted_average(weighted_components) if weighted_components else 0.5
    )
    for dimension in REVIEW_AFFINITY_DIMENSION_WEIGHTS:
        dimension_scores.setdefault(dimension, 0.5)
    return _ReviewProfileAffinityScore(
        score=_clamp(score),
        applied=applied,
        dimension_scores=dimension_scores,
        matched_segments=tuple(matched_segments),
    )


def _review_skin_type_code(value: str | None) -> str | None:
    normalized = _normalize_profile_value(value)
    return {
        "건성": "dry",
        "지성": "oily",
        "복합성": "combination",
        "중성": "normal",
        "수부지": "combination",
    }.get(normalized)


def _review_sensitivity_code(value: str | None) -> str | None:
    # review-scoring-revision 4.3(G4): 리뷰 프로필 원천(올리브영)에는 민감도 축이 없고
    # 피부타입 값 '민감성'만 존재하므로 세그먼트는 SENSITIVITY:high만 생성 가능하다.
    # 민감(높음)일 때만 타깃을 만들고, 그 외는 None → 타깃 미생성 → 차원 재정규화 제외.
    normalized = _normalize_sensitivity_value(value)
    if normalized == "높음":
        return "high"
    return None


def _score_skin_test_context(
    skin_test_context: SkinTestScoringContext | None,
    *,
    intent_purchase_conditions: ParsedPurchaseConditions,
    candidate: ProductCandidate,
    skin_profile: _SkinProfileInfo | None,
    risk_flags: tuple[_RiskFlagLike, ...],
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    precomputed_effect_features: dict[
        str,
        ProductEffectRecommendationFeatureValues,
    ]
    | None,
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
        precomputed_effect_features,
        functional_info,
    )
    axis_scores["PN"] = pn_score
    components.append((pn_score, SKIN_TEST_CONTEXT_COMPONENT_WEIGHTS["PN"]))

    wt_score = _score_wt_effect_fit(
        skin_test_context,
        contributions_by_effect,
        precomputed_effect_features,
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
    risk_flags: tuple[_RiskFlagLike, ...],
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
    precomputed_effect_features: dict[
        str,
        ProductEffectRecommendationFeatureValues,
    ]
    | None,
    functional_info: _FunctionalInfo | None,
) -> float:
    winner = _axis_winner(skin_test_context, "PN")
    if winner != "P":
        return DEFAULT_PROFILE_SCORE
    raw_score = _score_effect_signal(
        PIGMENT_EFFECT_CODES,
        contributions_by_effect,
        precomputed_effect_features,
        functional_info,
    )
    return _adjust_skin_test_axis_score(raw_score, _axis_strength(skin_test_context, "PN"))


def _score_wt_effect_fit(
    skin_test_context: SkinTestScoringContext,
    contributions_by_effect: dict[str, tuple[_EffectContribution, ...]],
    precomputed_effect_features: dict[
        str,
        ProductEffectRecommendationFeatureValues,
    ]
    | None,
    functional_info: _FunctionalInfo | None,
) -> float:
    winner = _axis_winner(skin_test_context, "WT")
    if winner != "W":
        return DEFAULT_PROFILE_SCORE
    raw_score = _score_effect_signal(
        WRINKLE_EFFECT_CODES,
        contributions_by_effect,
        precomputed_effect_features,
        functional_info,
    )
    return _adjust_skin_test_axis_score(raw_score, _axis_strength(skin_test_context, "WT"))


def _score_sensitive_safety_fit(
    skin_test_context: SkinTestScoringContext,
    risk_flags: tuple[_RiskFlagLike, ...],
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
    precomputed_effect_features: dict[
        str,
        ProductEffectRecommendationFeatureValues,
    ]
    | None,
    functional_info: _FunctionalInfo | None,
) -> float:
    signal = 0.0
    for effect_code in effect_codes:
        if precomputed_effect_features is not None:
            feature = precomputed_effect_features.get(effect_code)
            contribution_signal = (
                min(EFFECT_CAP, feature.ingredient_effect_score) / EFFECT_CAP
                if feature is not None
                else 0.0
            )
        else:
            contributions = contributions_by_effect.get(effect_code, ())
            contribution_signal = min(
                EFFECT_CAP,
                sum(
                    contribution.effect_component
                    for contribution in contributions
                ),
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


def _sensitive_safety_score(risk_flags: tuple[_RiskFlagLike, ...]) -> float:
    most_severe = _most_severe_risk(risk_flags)
    if most_severe == "high":
        return 0.3
    if most_severe == "medium":
        return 0.55
    if most_severe == "low":
        return 0.75
    return 0.85


def _resistant_safety_score(risk_flags: tuple[_RiskFlagLike, ...]) -> float:
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
        _normalize_sensitivity_value(manual_sensitivity)
        != _normalize_sensitivity_value(skin_test_context.mapped_sensitivity)
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
            if evidence is None:
                reason = (
                    f"{ingredient.ingredient_name} 성분이 공식 성분 기능 분류 기반 "
                    f"{ingredient.effect_name} 점수에 기여"
                )
            else:
                reason = f"{ingredient.ingredient_name} 성분이 {ingredient.effect_name} 효능 근거에 기여"
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
    if top.evidence_id is None:
        return (
            f"{top.ingredient_name} 성분이 공식 성분 기능 분류 기반 "
            f"{top.effect_name} 점수에 가장 크게 기여했습니다."
        )
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


def _normalize_sensitivity_value(value: str | None) -> str:
    normalized = _normalize_profile_value(value)
    aliases = {
        "민감": "높음",
        "민감성": "높음",
        "예민": "높음",
        "예민함": "높음",
        "sensitive": "높음",
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
