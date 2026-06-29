import os
from pathlib import Path

from app.services.parser import parse_concern_text
from app.services.repository import load_repository


def _resolve_examples_dir() -> Path:
    if os.getenv("DATA_EXAMPLES_DIR"):
        return Path(os.environ["DATA_EXAMPLES_DIR"])

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "examples"
        if candidate.exists():
            return candidate

    return Path("/data/examples")


EXAMPLES_DIR = _resolve_examples_dir()


def _resolve_data_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if candidate.exists():
            return candidate

    return Path("/data")


DATA_DIR = _resolve_data_dir()


def test_parse_concern_text_matches_tags_and_effects() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("모공이랑 속건조가 고민이에요", repository)

    assert [concern.tag_id for concern in result.concerns] == [
        "concern_pore",
        "concern_dryness",
    ]
    assert [effect.effect_id for effect in result.effects] == [
        "effect_sebum_control",
        "effect_texture",
        "effect_moisturizing",
        "effect_barrier",
    ]
    assert result.unmatched_terms == ()


def test_parse_concern_text_matches_compact_synonym() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("수분부족이 있고 당김도 있어요", repository)

    assert [concern.tag_id for concern in result.concerns] == ["concern_dryness"]
    assert result.effects[0].effect_id == "effect_moisturizing"


def test_parse_concern_text_deduplicates_effects_by_highest_weight() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("민감하고 트러블이 고민이에요", repository)

    assert [concern.tag_id for concern in result.concerns] == [
        "concern_sensitive",
        "concern_trouble",
    ]
    assert [effect.effect_id for effect in result.effects] == ["effect_calming"]
    assert result.effects[0].weight == 1.0


def test_parse_concern_text_returns_unmatched_when_no_tag_matches() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("주름 탄력 고민", repository)

    assert result.concerns == ()
    assert result.effects == ()
    assert result.unmatched_terms == ("주름 탄력 고민",)


def test_parse_concern_text_keeps_partial_unmatched_phrase() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("모공이랑 주름", repository)

    assert [concern.tag_id for concern in result.concerns] == ["concern_pore"]
    assert result.unmatched_terms == ("주름",)


def test_parse_concern_text_excludes_negated_concern_and_prioritizes_effect() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text(
        "난 여드름에는 딱히 상관이 없는데 미백을 좀 집중해서 앰플 추천받고 싶어",
        repository,
    )

    assert "concern_acne" not in [concern.tag_id for concern in result.concerns]
    assert [concern.tag_id for concern in result.excluded_concerns] == ["concern_acne"]
    assert "concern_brightening_spots" in [concern.tag_id for concern in result.concerns]
    assert "effect_brightening" in [effect.effect_id for effect in result.effects]
    assert [effect.effect_id for effect in result.priority_effects] == ["effect_brightening"]
    assert result.unmatched_terms == ()
    assert result.needs_llm is False


def test_parse_concern_text_excludes_added_negation_trigger() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text("여드름은 안 중요해, 미백 추천", repository)

    assert "concern_acne" not in [concern.tag_id for concern in result.concerns]
    assert [concern.tag_id for concern in result.excluded_concerns] == ["concern_acne"]
    assert "concern_brightening_spots" in [concern.tag_id for concern in result.concerns]
    assert "effect_brightening" in [effect.effect_id for effect in result.effects]


def test_parse_concern_text_prioritizes_added_priority_trigger() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text("미백을 특히 신경 쓰고 싶은 건데 앰플 추천", repository)

    assert "concern_brightening_spots" in [concern.tag_id for concern in result.concerns]
    assert "effect_brightening" in [effect.effect_id for effect in result.effects]
    assert [effect.effect_id for effect in result.priority_effects] == ["effect_brightening"]


def test_parse_concern_text_marks_temporal_shift_for_llm() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text(
        "예전엔 여드름 때문에 힘들었는데 지금은 칙칙함이 고민이에요",
        repository,
    )

    assert "concern_acne" in [concern.tag_id for concern in result.concerns]
    assert "concern_dull_uneven_tone" in [concern.tag_id for concern in result.concerns]
    assert result.needs_llm is True


def test_parse_concern_text_keeps_dislike_as_prevention_need() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text("여드름 생기기 싫어", repository)

    assert "concern_acne" in [concern.tag_id for concern in result.concerns]
    assert result.excluded_concerns == ()


def test_parse_concern_text_keeps_prevention_need_with_negative_word() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text("여드름 안 나게 진정 크림 추천", repository)

    assert "concern_acne" in [concern.tag_id for concern in result.concerns]
    assert result.excluded_concerns == ()
    assert "effect_calming" in [effect.effect_id for effect in result.effects]


def test_parse_concern_text_marks_ambiguous_language_for_llm() -> None:
    repository = load_repository(DATA_DIR)

    result = parse_concern_text("까무잡잡한데 허예지고 싶어", repository)

    assert result.concerns == ()
    assert result.effects == ()
    assert result.unmatched_terms == ("까무잡잡한데 허예지고 싶어",)
    assert result.needs_llm is True


def test_parse_concern_text_matches_direct_effect_and_priority_without_concern() -> None:
    repository = load_repository(EXAMPLES_DIR)

    result = parse_concern_text("보습 위주 세럼 추천", repository)

    assert result.concerns == ()
    assert [effect.effect_id for effect in result.effects] == ["effect_moisturizing"]
    assert [effect.effect_id for effect in result.priority_effects] == ["effect_moisturizing"]
    assert result.unmatched_terms == ()
    assert result.needs_llm is False
