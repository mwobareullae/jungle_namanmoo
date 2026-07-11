from __future__ import annotations

import re
import unicodedata


CATEGORY_GROUP_BY_CODE: dict[str, str] = {
    "toner": "skincare",
    "serum": "skincare",
    "cream": "skincare",
    "lotion": "skincare",
    "set": "skincare",
    "cleanser": "cleansing",
    "cleansing": "cleansing",
    "exfoliant": "cleansing",
    "bodycare": "bodycare",
    "hair_body": "bodycare",
    "haircare": "haircare",
    "beauty_tool": "beauty_tool",
    "mask": "mask_pack",
    "mask_pack": "mask_pack",
    "suncare": "suncare",
    "sunscreen": "suncare",
    "makeup": "makeup",
    "eye_neck": "makeup",
    "spot": "makeup",
    "nail": "nail",
    "fragrance": "fragrance",
    "men_allinone": "men",
    "unknown": "other",
    "accessory": "other",
}

CATEGORY_GROUP_LABELS: dict[str, str] = {
    "skincare": "스킨케어",
    "cleansing": "클렌징",
    "bodycare": "바디케어",
    "haircare": "헤어케어",
    "beauty_tool": "뷰티소품",
    "mask_pack": "마스크팩",
    "suncare": "선케어",
    "makeup": "메이크업",
    "nail": "네일",
    "fragrance": "향수",
    "men": "남성",
    "other": "기타",
}

_COMPACT_PATTERN = re.compile(r"[^0-9a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_CHOSEONG = (
    "ㄱ",
    "ㄲ",
    "ㄴ",
    "ㄷ",
    "ㄸ",
    "ㄹ",
    "ㅁ",
    "ㅂ",
    "ㅃ",
    "ㅅ",
    "ㅆ",
    "ㅇ",
    "ㅈ",
    "ㅉ",
    "ㅊ",
    "ㅋ",
    "ㅌ",
    "ㅍ",
    "ㅎ",
)


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _WHITESPACE_PATTERN.sub(" ", normalized)


def compact_search_text(value: str) -> str:
    return _COMPACT_PATTERN.sub("", normalize_search_text(value))


def extract_chosung(value: str) -> str:
    result: list[str] = []
    for character in normalize_search_text(value):
        code = ord(character)
        if 0xAC00 <= code <= 0xD7A3:
            result.append(_CHOSEONG[(code - 0xAC00) // 588])
        elif "ㄱ" <= character <= "ㅎ":
            result.append(character)
        elif character.isalnum():
            result.append(character)
    return "".join(result)


def category_group_for_code(category_code: str) -> str:
    return CATEGORY_GROUP_BY_CODE.get(category_code.strip().casefold(), "other")
