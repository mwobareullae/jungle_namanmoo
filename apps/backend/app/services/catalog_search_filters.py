from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogSearchFilterOption:
    value: str
    label: str
    source_values: tuple[str, ...]


# 화면에는 고객이 이해하기 쉬운 표현만 노출하고, 실제 판정은 정규화된 효능 코드로 한다.
# 같은 그룹에서 여러 효능이 연결된 경우 하나라도 충족하면 해당 특징으로 분류한다.
CATALOG_FEATURE_FILTER_OPTIONS: tuple[CatalogSearchFilterOption, ...] = (
    CatalogSearchFilterOption(
        "moisturizing_calming",
        "보습·진정",
        ("effect_moisturizing", "effect_calming", "effect_barrier"),
    ),
    CatalogSearchFilterOption(
        "pore_care",
        "모공 케어",
        ("effect_sebum_control", "effect_texture", "effect_pore_care"),
    ),
    CatalogSearchFilterOption(
        "trouble_care",
        "트러블 케어",
        ("effect_calming", "effect_sebum_control", "effect_acne_care"),
    ),
    CatalogSearchFilterOption(
        "wrinkle_elasticity",
        "주름·탄력",
        ("effect_wrinkle", "effect_elasticity", "effect_anti_aging"),
    ),
    CatalogSearchFilterOption(
        "brightening",
        "브라이트닝",
        ("effect_brightening", "effect_whitening", "effect_tone_up"),
    ),
)

CATALOG_SKIN_TYPE_FILTER_OPTIONS: tuple[CatalogSearchFilterOption, ...] = (
    CatalogSearchFilterOption("dry", "건성", ("건성",)),
    CatalogSearchFilterOption("oily", "지성", ("지성",)),
    CatalogSearchFilterOption("combination", "복합성", ("복합성",)),
    CatalogSearchFilterOption("dehydrated_oily", "수부지", ("수부지",)),
    CatalogSearchFilterOption("normal", "중성", ("중성",)),
)

_FEATURE_OPTIONS_BY_VALUE = {option.value: option for option in CATALOG_FEATURE_FILTER_OPTIONS}
_SKIN_TYPE_OPTIONS_BY_VALUE = {option.value: option for option in CATALOG_SKIN_TYPE_FILTER_OPTIONS}


def feature_effect_codes(values: Iterable[str]) -> tuple[str, ...]:
    return _source_values(values, _FEATURE_OPTIONS_BY_VALUE)


def feature_codes_for_effect_codes(effect_codes: Iterable[str]) -> tuple[str, ...]:
    known_effect_codes = set(effect_codes)
    return tuple(
        option.value
        for option in CATALOG_FEATURE_FILTER_OPTIONS
        if known_effect_codes.intersection(option.source_values)
    )


def skin_type_tag_values(values: Iterable[str]) -> tuple[str, ...]:
    return _source_values(values, _SKIN_TYPE_OPTIONS_BY_VALUE)


def skin_type_codes_for_tags(tags: Iterable[str]) -> tuple[str, ...]:
    normalized_tags = {tag.strip() for tag in tags if tag.strip()}
    return tuple(
        option.value
        for option in CATALOG_SKIN_TYPE_FILTER_OPTIONS
        if normalized_tags.intersection(option.source_values)
    )


def feature_filter_label(value: str) -> str:
    option = _FEATURE_OPTIONS_BY_VALUE.get(value)
    return option.label if option is not None else value


def skin_type_filter_label(value: str) -> str:
    option = _SKIN_TYPE_OPTIONS_BY_VALUE.get(value)
    return option.label if option is not None else value


def _source_values(
    values: Iterable[str],
    options_by_value: dict[str, CatalogSearchFilterOption],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for value in values:
        option = options_by_value.get(value)
        if option is not None:
            resolved.extend(option.source_values)
    return tuple(dict.fromkeys(resolved))
