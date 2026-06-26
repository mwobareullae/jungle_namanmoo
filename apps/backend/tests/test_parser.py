from pathlib import Path

from app.services.parser import parse_concern_text
from app.services.repository import load_repository


EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "data" / "examples"


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
