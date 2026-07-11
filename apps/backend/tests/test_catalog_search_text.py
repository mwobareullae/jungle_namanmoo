from app.services.catalog_search_text import (
    compact_search_text,
    english_keys_to_hangul,
    extract_chosung,
    hangul_to_english_keys,
    is_all_chosung_query,
    normalize_query_text,
)


def test_query_normalization_handles_unicode_punctuation_and_repeats() -> None:
    assert normalize_query_text("  ＡＮＵＡ!!!aaa  ") == "anua a"
    assert compact_search_text("선 크림") == "선크림"


def test_dubeolsik_keyboard_conversion_is_bidirectional() -> None:
    assert english_keys_to_hangul("xhflems") == "토리든"
    assert hangul_to_english_keys("토리든") == "xhflems"


def test_chosung_detection_requires_all_jamo_input() -> None:
    assert is_all_chosung_query("ㅌㄹㄷ") is True
    assert extract_chosung("토리든") == "ㅌㄹㄷ"
    assert is_all_chosung_query("ㅌㄹ든") is False
    assert is_all_chosung_query("토리든") is False
