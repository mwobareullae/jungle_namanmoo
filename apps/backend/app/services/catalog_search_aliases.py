from __future__ import annotations

from app.services.catalog_search_text import compact_search_text, normalize_query_text


BRAND_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("모로칸오일", "moroccanoil"),
    ("맥", "mac"),
    ("나스", "nars"),
    ("라로슈포제", "la roche-posay", "la roche posay"),
    ("아누아", "anua"),
    ("메디큐브", "medicube"),
    ("바이오던스", "biodance"),
    ("조선미녀", "beauty of joseon"),
    ("코스알엑스", "cosrx"),
    ("라네즈", "laneige"),
    ("이니스프리", "innisfree"),
    ("닥터자르트", "dr. jart+", "dr jart"),
    ("세라비", "cerave", "cera ve"),
    ("디오디너리", "the ordinary"),
    ("폴라초이스", "paula's choice", "paulas choice"),
    ("키엘", "kiehl's since 1851", "kiehls"),
    ("아벤느", "avene", "avène"),
    ("후다뷰티", "huda beauty"),
    ("샬롯틸버리", "charlotte tilbury"),
)

KNOWN_QUERY_CORRECTIONS: dict[str, str] = {
    "토리덴": "토리든",
    "라로슈포재": "라로슈포제",
    "히알루론싼": "히알루론산",
    "나이아신아마드": "나이아신아마이드",
    "히알루론사": "히알루론산",
    "레티놀ㄹ": "레티놀",
    "판테놀ㄹ": "판테놀",
    "스쿠알란느": "스쿠알란",
    "세라마이드드": "세라마이드",
    "글루타치온ㄴ": "글루타치온",
    "콜라겐ㄴ": "콜라겐",
    "토너어": "토너",
    "세럼어": "세럼",
    "크리임": "크림",
    "클랜징폼": "클렌징폼",
    "바디워시이": "바디워시",
    "샴푸우": "샴푸",
    "향수우": "향수",
    "네일르": "네일",
    "선크림므": "선크림",
    "마스크펙": "마스크팩",
    "스킨푸두": "스킨푸드",
    "클렌징 폼": "클렌징폼",
    "선 크림": "선크림",
    "모로칸 오일": "모로칸오일",
}


def equivalent_brand_values(value: str) -> tuple[str, ...]:
    compact_value = compact_search_text(value)
    for group in BRAND_ALIAS_GROUPS:
        if any(compact_search_text(alias) == compact_value for alias in group):
            return group
    return (value,)


def matching_brand_equivalent_values(query: str) -> tuple[str, ...]:
    normalized_query = normalize_query_text(query)
    query_phrases = _compact_query_phrases(normalized_query)
    matches: list[str] = []
    for group in BRAND_ALIAS_GROUPS:
        matched = False
        for alias in group:
            compact_alias = compact_search_text(alias)
            normalized_alias = normalize_query_text(alias)
            matched = compact_alias in query_phrases or normalized_alias == normalized_query
            if matched:
                break
        if matched:
            matches.extend(group)
    return tuple(dict.fromkeys(matches))


def brand_query_variants(query: str) -> tuple[str, ...]:
    normalized_query = normalize_query_text(query)
    compact_query = compact_search_text(query)
    variants: list[str] = []
    for group in BRAND_ALIAS_GROUPS:
        matched_aliases = [
            alias
            for alias in group
            if compact_search_text(alias) and compact_search_text(alias) in compact_query
        ]
        if not matched_aliases:
            continue
        matched_alias = max(matched_aliases, key=lambda alias: len(compact_search_text(alias)))
        normalized_alias = normalize_query_text(matched_alias)
        for replacement in group:
            if compact_search_text(replacement) == compact_search_text(matched_alias):
                continue
            if normalized_alias in normalized_query:
                variant = normalized_query.replace(normalized_alias, normalize_query_text(replacement), 1)
            elif compact_query == compact_search_text(matched_alias):
                variant = normalize_query_text(replacement)
            else:
                continue
            if variant and variant != normalized_query and variant not in variants:
                variants.append(variant)
    return tuple(variants)


def known_query_correction(query: str) -> str | None:
    normalized_query = normalize_query_text(query)
    compact_query = compact_search_text(query)
    for incorrect, corrected in KNOWN_QUERY_CORRECTIONS.items():
        normalized_incorrect = normalize_query_text(incorrect)
        if normalized_incorrect in normalized_query:
            candidate = normalized_query.replace(normalized_incorrect, corrected, 1)
            if candidate != normalized_query:
                return candidate
        if compact_query == compact_search_text(incorrect):
            candidate = normalize_query_text(corrected)
            if candidate != normalized_query:
                return candidate
    return None


def _compact_query_phrases(value: str) -> set[str]:
    tokens = [compact_search_text(token) for token in normalize_query_text(value).split()]
    tokens = [token for token in tokens if token]
    phrases: set[str] = set(tokens)
    for start in range(len(tokens)):
        combined = ""
        for token in tokens[start:]:
            combined += token
            phrases.add(combined)
    return phrases
