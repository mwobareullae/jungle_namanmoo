from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotProductFeature:
    top_ingredient_codes: tuple[str, ...]
    top_effect_codes: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotEffectFeature:
    ingredient_effect_score: float
    ingredient_evidence_score: float
    concentration_score: float
    concentration_context: dict[str, object]
    top_ingredient_ids: tuple[int, ...]
    best_evidence_ids: tuple[int, ...]


@dataclass(frozen=True)
class SnapshotFunctionalInfo:
    status: str | None
    claims: tuple[str, ...]
    claim_confidence: str | None
    basis: str | None


@dataclass(frozen=True)
class SnapshotSkinProfile:
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
class SnapshotRiskFlag:
    risk_type: str
    display_text: str
    severity: str
    severity_score: float | None
    applies_to: str | None


@dataclass(frozen=True)
class SnapshotMarketSignal:
    popularity_score: float


@dataclass(frozen=True)
class SnapshotReviewMetric:
    review_quality_score: float
    confidence: float
    effective_sample_size: float
    review_count: int


@dataclass(frozen=True)
class SnapshotReviewSegment:
    dimension: str
    value_code: str
    total_affinity_score: float
    effective_sample_size: float
    review_count: int


@dataclass(frozen=True)
class RecommendationScoringSnapshotPayload:
    product_feature: SnapshotProductFeature | None
    effect_features: dict[str, SnapshotEffectFeature]
    functional_info: SnapshotFunctionalInfo
    skin_tags: tuple[str, ...]
    skin_profile: SnapshotSkinProfile | None
    risk_flags: tuple[SnapshotRiskFlag, ...]
    market_signal: SnapshotMarketSignal | None
    review_metric: SnapshotReviewMetric | None
    review_segments: tuple[SnapshotReviewSegment, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "product_feature": _serialize_product_feature(self.product_feature),
            "effect_features": {
                effect_code: _serialize_effect_feature(feature)
                for effect_code, feature in self.effect_features.items()
            },
            "functional_info": {
                "status": self.functional_info.status,
                "claims": list(self.functional_info.claims),
                "claim_confidence": self.functional_info.claim_confidence,
                "basis": self.functional_info.basis,
            },
            "skin_tags": list(self.skin_tags),
            "skin_profile": _serialize_skin_profile(self.skin_profile),
            "risk_flags": [
                {
                    "risk_type": flag.risk_type,
                    "display_text": flag.display_text,
                    "severity": flag.severity,
                    "severity_score": flag.severity_score,
                    "applies_to": flag.applies_to,
                }
                for flag in self.risk_flags
            ],
            "market_signal": (
                {"popularity_score": self.market_signal.popularity_score}
                if self.market_signal is not None
                else None
            ),
            "review_metric": (
                {
                    "review_quality_score": self.review_metric.review_quality_score,
                    "confidence": self.review_metric.confidence,
                    "effective_sample_size": self.review_metric.effective_sample_size,
                    "review_count": self.review_metric.review_count,
                }
                if self.review_metric is not None
                else None
            ),
            "review_segments": [
                {
                    "dimension": segment.dimension,
                    "value_code": segment.value_code,
                    "total_affinity_score": segment.total_affinity_score,
                    "effective_sample_size": segment.effective_sample_size,
                    "review_count": segment.review_count,
                }
                for segment in self.review_segments
            ],
        }


def _serialize_product_feature(
    feature: SnapshotProductFeature | None,
) -> dict[str, object] | None:
    if feature is None:
        return None
    return {
        "top_ingredient_codes": list(feature.top_ingredient_codes),
        "top_effect_codes": list(feature.top_effect_codes),
    }


def _serialize_effect_feature(feature: SnapshotEffectFeature) -> dict[str, object]:
    return {
        "ingredient_effect_score": feature.ingredient_effect_score,
        "ingredient_evidence_score": feature.ingredient_evidence_score,
        "concentration_score": feature.concentration_score,
        "concentration_context": dict(feature.concentration_context),
        "top_ingredient_ids": list(feature.top_ingredient_ids),
        "best_evidence_ids": list(feature.best_evidence_ids),
    }


def _serialize_skin_profile(
    profile: SnapshotSkinProfile | None,
) -> dict[str, object] | None:
    if profile is None:
        return None
    return {
        "dry_fit": profile.dry_fit,
        "oily_fit": profile.oily_fit,
        "combination_fit": profile.combination_fit,
        "normal_fit": profile.normal_fit,
        "dehydrated_oily_fit": profile.dehydrated_oily_fit,
        "sensitive_fit": profile.sensitive_fit,
        "sensitivity_tag": profile.sensitivity_tag,
        "confidence": profile.confidence,
        "reason": profile.reason,
    }
