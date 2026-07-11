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
_QUERY_PUNCTUATION_PATTERN = re.compile(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ.%+'-]+", re.UNICODE)
_REPEATED_CHARACTER_PATTERN = re.compile(r"(.)\1{2,}")
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

_KEY_TO_JAMO = {
    "r": "ㄱ",
    "R": "ㄲ",
    "s": "ㄴ",
    "e": "ㄷ",
    "E": "ㄸ",
    "f": "ㄹ",
    "a": "ㅁ",
    "q": "ㅂ",
    "Q": "ㅃ",
    "t": "ㅅ",
    "T": "ㅆ",
    "d": "ㅇ",
    "w": "ㅈ",
    "W": "ㅉ",
    "c": "ㅊ",
    "z": "ㅋ",
    "x": "ㅌ",
    "v": "ㅍ",
    "g": "ㅎ",
    "k": "ㅏ",
    "o": "ㅐ",
    "i": "ㅑ",
    "O": "ㅒ",
    "j": "ㅓ",
    "p": "ㅔ",
    "u": "ㅕ",
    "P": "ㅖ",
    "h": "ㅗ",
    "y": "ㅛ",
    "n": "ㅜ",
    "b": "ㅠ",
    "m": "ㅡ",
    "l": "ㅣ",
}
_CHOSEONG_VALUES = (
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
_JUNGSEONG_VALUES = (
    "ㅏ",
    "ㅐ",
    "ㅑ",
    "ㅒ",
    "ㅓ",
    "ㅔ",
    "ㅕ",
    "ㅖ",
    "ㅗ",
    "ㅘ",
    "ㅙ",
    "ㅚ",
    "ㅛ",
    "ㅜ",
    "ㅝ",
    "ㅞ",
    "ㅟ",
    "ㅠ",
    "ㅡ",
    "ㅢ",
    "ㅣ",
)
_JONGSEONG_VALUES = (
    "",
    "ㄱ",
    "ㄲ",
    "ㄳ",
    "ㄴ",
    "ㄵ",
    "ㄶ",
    "ㄷ",
    "ㄹ",
    "ㄺ",
    "ㄻ",
    "ㄼ",
    "ㄽ",
    "ㄾ",
    "ㄿ",
    "ㅀ",
    "ㅁ",
    "ㅂ",
    "ㅄ",
    "ㅅ",
    "ㅆ",
    "ㅇ",
    "ㅈ",
    "ㅊ",
    "ㅋ",
    "ㅌ",
    "ㅍ",
    "ㅎ",
)
_COMPOUND_VOWELS = {
    ("ㅗ", "ㅏ"): "ㅘ",
    ("ㅗ", "ㅐ"): "ㅙ",
    ("ㅗ", "ㅣ"): "ㅚ",
    ("ㅜ", "ㅓ"): "ㅝ",
    ("ㅜ", "ㅔ"): "ㅞ",
    ("ㅜ", "ㅣ"): "ㅟ",
    ("ㅡ", "ㅣ"): "ㅢ",
}
_COMPOUND_FINALS = {
    ("ㄱ", "ㅅ"): "ㄳ",
    ("ㄴ", "ㅈ"): "ㄵ",
    ("ㄴ", "ㅎ"): "ㄶ",
    ("ㄹ", "ㄱ"): "ㄺ",
    ("ㄹ", "ㅁ"): "ㄻ",
    ("ㄹ", "ㅂ"): "ㄼ",
    ("ㄹ", "ㅅ"): "ㄽ",
    ("ㄹ", "ㅌ"): "ㄾ",
    ("ㄹ", "ㅍ"): "ㄿ",
    ("ㄹ", "ㅎ"): "ㅀ",
    ("ㅂ", "ㅅ"): "ㅄ",
}
_SPLIT_FINALS = {value: key for key, value in _COMPOUND_FINALS.items()}
_CHOSEONG_KEYS = (
    "r",
    "R",
    "s",
    "e",
    "E",
    "f",
    "a",
    "q",
    "Q",
    "t",
    "T",
    "d",
    "w",
    "W",
    "c",
    "z",
    "x",
    "v",
    "g",
)
_JUNGSEONG_KEYS = (
    "k",
    "o",
    "i",
    "O",
    "j",
    "p",
    "u",
    "P",
    "h",
    "hk",
    "ho",
    "hl",
    "y",
    "n",
    "nj",
    "np",
    "nl",
    "b",
    "m",
    "ml",
    "l",
)
_JONGSEONG_KEYS = (
    "",
    "r",
    "R",
    "rt",
    "s",
    "sw",
    "sg",
    "e",
    "f",
    "fr",
    "fa",
    "fq",
    "ft",
    "fx",
    "fv",
    "fg",
    "a",
    "q",
    "qt",
    "t",
    "T",
    "d",
    "w",
    "c",
    "z",
    "x",
    "v",
    "g",
)
_JAMO_TO_KEY = {value: key for key, value in _KEY_TO_JAMO.items()}
_CANONICAL_CHOSEONG_TO_COMPAT = {
    chr(0x1100 + index): value
    for index, value in enumerate(_CHOSEONG_VALUES)
}


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = "".join(_CANONICAL_CHOSEONG_TO_COMPAT.get(character, character) for character in normalized)
    return _WHITESPACE_PATTERN.sub(" ", normalized)


def normalize_query_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = "".join(_CANONICAL_CHOSEONG_TO_COMPAT.get(character, character) for character in normalized)
    normalized = _REPEATED_CHARACTER_PATTERN.sub(r"\1", normalized)
    normalized = _QUERY_PUNCTUATION_PATTERN.sub(" ", normalized)
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()


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


def is_all_chosung_query(value: str) -> bool:
    compact = "".join(character for character in normalize_search_text(value) if not character.isspace())
    return bool(compact) and all("ㄱ" <= character <= "ㅎ" for character in compact)


def english_keys_to_hangul(value: str) -> str:
    result: list[str] = []
    jamo_buffer: list[str] = []
    for character in value:
        jamo = _KEY_TO_JAMO.get(character)
        if jamo is None:
            if jamo_buffer:
                result.append(_compose_jamo(jamo_buffer))
                jamo_buffer = []
            result.append(character)
        else:
            jamo_buffer.append(jamo)
    if jamo_buffer:
        result.append(_compose_jamo(jamo_buffer))
    return "".join(result)


def hangul_to_english_keys(value: str) -> str:
    result: list[str] = []
    for character in value:
        code = ord(character)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            choseong_index = offset // 588
            jungseong_index = (offset % 588) // 28
            jongseong_index = offset % 28
            result.append(_CHOSEONG_KEYS[choseong_index])
            result.append(_JUNGSEONG_KEYS[jungseong_index])
            result.append(_JONGSEONG_KEYS[jongseong_index])
        else:
            result.append(_JAMO_TO_KEY.get(character, character))
    return "".join(result)


def _compose_jamo(jamo_values: list[str]) -> str:
    result: list[str] = []
    choseong: str | None = None
    jungseong: str | None = None
    jongseong: str | None = None

    def flush() -> None:
        nonlocal choseong, jungseong, jongseong
        if choseong is not None and jungseong is not None:
            result.append(_compose_syllable(choseong, jungseong, jongseong))
        elif choseong is not None:
            result.append(choseong)
        elif jungseong is not None:
            result.append(jungseong)
        choseong = None
        jungseong = None
        jongseong = None

    for jamo in jamo_values:
        is_vowel = jamo in _JUNGSEONG_VALUES
        if is_vowel:
            if choseong is None:
                if jungseong is None:
                    jungseong = jamo
                else:
                    compound = _COMPOUND_VOWELS.get((jungseong, jamo))
                    if compound is not None:
                        jungseong = compound
                    else:
                        flush()
                        jungseong = jamo
                continue
            if jungseong is None:
                jungseong = jamo
                continue
            if jongseong is None:
                compound = _COMPOUND_VOWELS.get((jungseong, jamo))
                if compound is not None:
                    jungseong = compound
                else:
                    flush()
                    jungseong = jamo
                continue

            previous_final = jongseong
            next_initial = previous_final
            if previous_final in _SPLIT_FINALS:
                retained_final, next_initial = _SPLIT_FINALS[previous_final]
                jongseong = retained_final
            else:
                jongseong = None
            flush()
            choseong = next_initial if next_initial in _CHOSEONG_VALUES else None
            if choseong is None and next_initial:
                result.append(next_initial)
            jungseong = jamo
            continue

        if choseong is None:
            if jungseong is not None:
                flush()
            choseong = jamo
            continue
        if jungseong is None:
            flush()
            choseong = jamo
            continue
        if jongseong is None:
            if jamo in _JONGSEONG_VALUES:
                jongseong = jamo
            else:
                flush()
                choseong = jamo
            continue
        compound_final = _COMPOUND_FINALS.get((jongseong, jamo))
        if compound_final is not None:
            jongseong = compound_final
        else:
            flush()
            choseong = jamo

    flush()
    return "".join(result)


def _compose_syllable(choseong: str, jungseong: str, jongseong: str | None) -> str:
    try:
        choseong_index = _CHOSEONG_VALUES.index(choseong)
        jungseong_index = _JUNGSEONG_VALUES.index(jungseong)
        jongseong_index = _JONGSEONG_VALUES.index(jongseong or "")
    except ValueError:
        return f"{choseong}{jungseong}{jongseong or ''}"
    return chr(0xAC00 + (choseong_index * 21 + jungseong_index) * 28 + jongseong_index)


def category_group_for_code(category_code: str) -> str:
    return CATEGORY_GROUP_BY_CODE.get(category_code.strip().casefold(), "other")
