from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


PROFILE_MAPPING_VERSION = "review_profile_v1"
COMBINED_FALLBACK_MULTIPLIER = Decimal("0.8000")


@dataclass(frozen=True)
class ReviewProfileMapping:
    dimension: str
    value_code: str
    source_label: str
    mapping_source: str
    mapping_confidence: Decimal


@dataclass(frozen=True)
class ReviewProfileMappingResult:
    labels: tuple[ReviewProfileMapping, ...]
    unknown_labels: tuple[str, ...]
    has_source_profile: bool


@dataclass(frozen=True)
class _MappingRule:
    dimension: str
    value_code: str
    confidence: Decimal = Decimal("1.0000")


_SKIN_TYPE_RULES = {
    "건성": _MappingRule("SKIN_TYPE", "dry"),
    "약건성": _MappingRule("SKIN_TYPE", "dry", Decimal("0.7000")),
    "지성": _MappingRule("SKIN_TYPE", "oily"),
    "복합성": _MappingRule("SKIN_TYPE", "combination"),
    "중성": _MappingRule("SKIN_TYPE", "normal"),
    "민감성": _MappingRule("SENSITIVITY", "high"),
    "트러블성": _MappingRule("SKIN_CONCERN", "concern_acne", Decimal("0.8000")),
}

_SKIN_TONE_RULES = {
    "쿨톤": _MappingRule("SKIN_TONE", "cool"),
    "웜톤": _MappingRule("SKIN_TONE", "warm"),
    "봄웜톤": _MappingRule("SKIN_TONE", "spring_warm"),
    "여름쿨톤": _MappingRule("SKIN_TONE", "summer_cool"),
    "가을웜톤": _MappingRule("SKIN_TONE", "autumn_warm"),
    "겨울쿨톤": _MappingRule("SKIN_TONE", "winter_cool"),
}

_SKIN_CONCERN_RULES = {
    "가려움": _MappingRule("SKIN_CONCERN", "concern_dry_barrier"),
    "각질": _MappingRule("SKIN_CONCERN", "concern_dead_skin_texture"),
    "다크서클": _MappingRule("SKIN_CONCERN", "concern_dark_circle"),
    "모공": _MappingRule("SKIN_CONCERN", "concern_pore"),
    "미백": _MappingRule("SKIN_CONCERN", "concern_brightening_spots"),
    "민감성": _MappingRule("SKIN_CONCERN", "concern_sensitive"),
    "붉은기": _MappingRule("SKIN_CONCERN", "concern_redness_irritation"),
    "블랙헤드": _MappingRule("SKIN_CONCERN", "concern_pore"),
    "잡티": _MappingRule("SKIN_CONCERN", "concern_brightening_spots"),
    "주름": _MappingRule("SKIN_CONCERN", "concern_wrinkle_elasticity"),
    "탄력": _MappingRule("SKIN_CONCERN", "concern_wrinkle_elasticity"),
    "트러블": _MappingRule("SKIN_CONCERN", "concern_acne"),
    "피지과다": _MappingRule("SKIN_CONCERN", "concern_pore"),
}

_COMBINED_RULES = {
    **_SKIN_TYPE_RULES,
    **_SKIN_TONE_RULES,
    **{key: value for key, value in _SKIN_CONCERN_RULES.items() if key not in _SKIN_TYPE_RULES},
}


def map_review_profile_labels(
    *,
    skin_type_label: str | None,
    skin_tone_label: str | None,
    skin_concern_labels: str | None,
    combined_profile_labels: str | None,
) -> ReviewProfileMappingResult:
    source_values = [
        skin_type_label,
        skin_tone_label,
        skin_concern_labels,
        combined_profile_labels,
    ]
    has_source_profile = any(_split_labels(value) for value in source_values)
    mapped: dict[tuple[str, str], ReviewProfileMapping] = {}
    unknown: list[str] = []
    dedicated_dimensions: set[str] = set()
    dedicated_source_labels = {
        *(_split_labels(skin_type_label)),
        *(_split_labels(skin_tone_label)),
        *(_split_labels(skin_concern_labels)),
    }

    _map_values(
        _split_labels(skin_type_label),
        _SKIN_TYPE_RULES,
        mapping_source="skin_type",
        output=mapped,
        unknown=unknown,
        dedicated_dimensions=dedicated_dimensions,
    )
    _map_values(
        _split_labels(skin_tone_label),
        _SKIN_TONE_RULES,
        mapping_source="skin_tone",
        output=mapped,
        unknown=unknown,
        dedicated_dimensions=dedicated_dimensions,
    )
    _map_values(
        _split_labels(skin_concern_labels),
        _SKIN_CONCERN_RULES,
        mapping_source="skin_concern",
        output=mapped,
        unknown=unknown,
        dedicated_dimensions=dedicated_dimensions,
    )

    for source_label in _split_labels(combined_profile_labels):
        if source_label in dedicated_source_labels:
            continue
        rule = _COMBINED_RULES.get(source_label)
        if rule is None:
            unknown.append(source_label)
            continue
        if rule.dimension in dedicated_dimensions:
            continue
        _store_mapping(
            mapped,
            rule,
            source_label=source_label,
            mapping_source="combined_fallback",
            confidence_multiplier=COMBINED_FALLBACK_MULTIPLIER,
        )

    return ReviewProfileMappingResult(
        labels=tuple(
            sorted(
                mapped.values(),
                key=lambda item: (item.dimension, item.value_code, item.source_label),
            )
        ),
        unknown_labels=tuple(_dedupe(unknown)),
        has_source_profile=has_source_profile,
    )


def _map_values(
    values: tuple[str, ...],
    rules: dict[str, _MappingRule],
    *,
    mapping_source: str,
    output: dict[tuple[str, str], ReviewProfileMapping],
    unknown: list[str],
    dedicated_dimensions: set[str],
) -> None:
    for source_label in values:
        rule = rules.get(source_label)
        if rule is None:
            unknown.append(source_label)
            continue
        dedicated_dimensions.add(rule.dimension)
        _store_mapping(
            output,
            rule,
            source_label=source_label,
            mapping_source=mapping_source,
        )


def _store_mapping(
    output: dict[tuple[str, str], ReviewProfileMapping],
    rule: _MappingRule,
    *,
    source_label: str,
    mapping_source: str,
    confidence_multiplier: Decimal = Decimal("1.0000"),
) -> None:
    mapping = ReviewProfileMapping(
        dimension=rule.dimension,
        value_code=rule.value_code,
        source_label=source_label,
        mapping_source=mapping_source,
        mapping_confidence=(rule.confidence * confidence_multiplier).quantize(Decimal("0.0001")),
    )
    key = (mapping.dimension, mapping.value_code)
    previous = output.get(key)
    if previous is None or mapping.mapping_confidence > previous.mapping_confidence:
        output[key] = mapping


def _split_labels(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(";") if item.strip())


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
