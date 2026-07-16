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

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> "RecommendationScoringSnapshotPayload":
        payload = _require_mapping(value, "scoring_payload")
        return cls(
            product_feature=_parse_product_feature(payload.get("product_feature")),
            effect_features=_parse_effect_features(payload.get("effect_features")),
            functional_info=_parse_functional_info(payload.get("functional_info")),
            skin_tags=_require_string_tuple(payload.get("skin_tags"), "skin_tags"),
            skin_profile=_parse_skin_profile(payload.get("skin_profile")),
            risk_flags=_parse_risk_flags(payload.get("risk_flags")),
            market_signal=_parse_market_signal(payload.get("market_signal")),
            review_metric=_parse_review_metric(payload.get("review_metric")),
            review_segments=_parse_review_segments(payload.get("review_segments")),
        )

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


class RecommendationScoringSnapshotPayloadError(ValueError):
    pass


def _parse_product_feature(value: object) -> SnapshotProductFeature | None:
    if value is None:
        return None
    data = _require_mapping(value, "product_feature")
    return SnapshotProductFeature(
        top_ingredient_codes=_require_string_tuple(
            data.get("top_ingredient_codes"),
            "product_feature.top_ingredient_codes",
        ),
        top_effect_codes=_require_string_tuple(
            data.get("top_effect_codes"),
            "product_feature.top_effect_codes",
        ),
    )


def _parse_effect_features(value: object) -> dict[str, SnapshotEffectFeature]:
    data = _require_mapping(value, "effect_features")
    parsed: dict[str, SnapshotEffectFeature] = {}
    for raw_effect_code, raw_feature in data.items():
        if not isinstance(raw_effect_code, str) or not raw_effect_code:
            raise RecommendationScoringSnapshotPayloadError(
                "effect_features keys must be non-empty strings"
            )
        feature = _require_mapping(
            raw_feature,
            f"effect_features.{raw_effect_code}",
        )
        parsed[raw_effect_code] = SnapshotEffectFeature(
            ingredient_effect_score=_require_number(
                feature.get("ingredient_effect_score"),
                f"effect_features.{raw_effect_code}.ingredient_effect_score",
            ),
            ingredient_evidence_score=_require_number(
                feature.get("ingredient_evidence_score"),
                f"effect_features.{raw_effect_code}.ingredient_evidence_score",
            ),
            concentration_score=_require_number(
                feature.get("concentration_score"),
                f"effect_features.{raw_effect_code}.concentration_score",
            ),
            concentration_context=dict(
                _require_mapping(
                    feature.get("concentration_context"),
                    f"effect_features.{raw_effect_code}.concentration_context",
                )
            ),
            top_ingredient_ids=_require_int_tuple(
                feature.get("top_ingredient_ids"),
                f"effect_features.{raw_effect_code}.top_ingredient_ids",
            ),
            best_evidence_ids=_require_int_tuple(
                feature.get("best_evidence_ids"),
                f"effect_features.{raw_effect_code}.best_evidence_ids",
            ),
        )
    return parsed


def _parse_functional_info(value: object) -> SnapshotFunctionalInfo:
    data = _require_mapping(value, "functional_info")
    return SnapshotFunctionalInfo(
        status=_optional_string(data.get("status"), "functional_info.status"),
        claims=_require_string_tuple(data.get("claims"), "functional_info.claims"),
        claim_confidence=_optional_string(
            data.get("claim_confidence"),
            "functional_info.claim_confidence",
        ),
        basis=_optional_string(data.get("basis"), "functional_info.basis"),
    )


def _parse_skin_profile(value: object) -> SnapshotSkinProfile | None:
    if value is None:
        return None
    data = _require_mapping(value, "skin_profile")
    return SnapshotSkinProfile(
        dry_fit=_require_number(data.get("dry_fit"), "skin_profile.dry_fit"),
        oily_fit=_require_number(data.get("oily_fit"), "skin_profile.oily_fit"),
        combination_fit=_require_number(
            data.get("combination_fit"),
            "skin_profile.combination_fit",
        ),
        normal_fit=_require_number(data.get("normal_fit"), "skin_profile.normal_fit"),
        dehydrated_oily_fit=_require_number(
            data.get("dehydrated_oily_fit"),
            "skin_profile.dehydrated_oily_fit",
        ),
        sensitive_fit=_require_number(
            data.get("sensitive_fit"),
            "skin_profile.sensitive_fit",
        ),
        sensitivity_tag=_optional_string(
            data.get("sensitivity_tag"),
            "skin_profile.sensitivity_tag",
        ),
        confidence=_optional_string(
            data.get("confidence"),
            "skin_profile.confidence",
        ),
        reason=_optional_string(data.get("reason"), "skin_profile.reason"),
    )


def _parse_risk_flags(value: object) -> tuple[SnapshotRiskFlag, ...]:
    items = _require_list(value, "risk_flags")
    parsed: list[SnapshotRiskFlag] = []
    for index, raw_flag in enumerate(items):
        path = f"risk_flags[{index}]"
        flag = _require_mapping(raw_flag, path)
        parsed.append(
            SnapshotRiskFlag(
                risk_type=_require_string(flag.get("risk_type"), f"{path}.risk_type"),
                display_text=_require_string(
                    flag.get("display_text"),
                    f"{path}.display_text",
                ),
                severity=_require_string(flag.get("severity"), f"{path}.severity"),
                severity_score=_optional_number(
                    flag.get("severity_score"),
                    f"{path}.severity_score",
                ),
                applies_to=_optional_string(
                    flag.get("applies_to"),
                    f"{path}.applies_to",
                ),
            )
        )
    return tuple(parsed)


def _parse_market_signal(value: object) -> SnapshotMarketSignal | None:
    if value is None:
        return None
    data = _require_mapping(value, "market_signal")
    return SnapshotMarketSignal(
        popularity_score=_require_number(
            data.get("popularity_score"),
            "market_signal.popularity_score",
        )
    )


def _parse_review_metric(value: object) -> SnapshotReviewMetric | None:
    if value is None:
        return None
    data = _require_mapping(value, "review_metric")
    return SnapshotReviewMetric(
        review_quality_score=_require_number(
            data.get("review_quality_score"),
            "review_metric.review_quality_score",
        ),
        confidence=_require_number(
            data.get("confidence"),
            "review_metric.confidence",
        ),
        effective_sample_size=_require_number(
            data.get("effective_sample_size"),
            "review_metric.effective_sample_size",
        ),
        review_count=_require_int(
            data.get("review_count"),
            "review_metric.review_count",
        ),
    )


def _parse_review_segments(value: object) -> tuple[SnapshotReviewSegment, ...]:
    items = _require_list(value, "review_segments")
    parsed: list[SnapshotReviewSegment] = []
    for index, raw_segment in enumerate(items):
        path = f"review_segments[{index}]"
        segment = _require_mapping(raw_segment, path)
        parsed.append(
            SnapshotReviewSegment(
                dimension=_require_string(
                    segment.get("dimension"),
                    f"{path}.dimension",
                ),
                value_code=_require_string(
                    segment.get("value_code"),
                    f"{path}.value_code",
                ),
                total_affinity_score=_require_number(
                    segment.get("total_affinity_score"),
                    f"{path}.total_affinity_score",
                ),
                effective_sample_size=_require_number(
                    segment.get("effective_sample_size"),
                    f"{path}.effective_sample_size",
                ),
                review_count=_require_int(
                    segment.get("review_count"),
                    f"{path}.review_count",
                ),
            )
        )
    return tuple(parsed)


def _require_mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise RecommendationScoringSnapshotPayloadError(f"{path} must be an object")
    return value


def _require_list(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise RecommendationScoringSnapshotPayloadError(f"{path} must be an array")
    return value


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise RecommendationScoringSnapshotPayloadError(f"{path} must be a string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, path)


def _require_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecommendationScoringSnapshotPayloadError(f"{path} must be a number")
    return float(value)


def _optional_number(value: object, path: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, path)


def _require_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecommendationScoringSnapshotPayloadError(f"{path} must be an integer")
    return int(value)


def _require_string_tuple(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _require_string(item, f"{path}[{index}]")
        for index, item in enumerate(_require_list(value, path))
    )


def _require_int_tuple(value: object, path: str) -> tuple[int, ...]:
    return tuple(
        _require_int(item, f"{path}[{index}]")
        for index, item in enumerate(_require_list(value, path))
    )
