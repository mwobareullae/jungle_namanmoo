import os
from pathlib import Path

import pytest

from app.services.recommendation_intent import build_recommendation_intent
from tests.repository_cache import cached_repository


def _resolve_data_dir() -> Path:
    if os.getenv("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if candidate.exists():
            return candidate

    return Path("/data")


DATA_DIR = _resolve_data_dir()
pytestmark = pytest.mark.slow


def test_build_recommendation_intent_combines_parser_outputs() -> None:
    repository = cached_repository(DATA_DIR)

    intent = build_recommendation_intent(
        "난 여드름에는 딱히 상관이 없는데 미백을 좀 집중해서 앰플 2만원 이하로 추천받고 싶어",
        repository=repository,
    )

    assert [category.category_code for category in intent.purchase_conditions.categories] == ["serum"]
    assert intent.purchase_conditions.price_max == 20000
    assert [concern.tag_id for concern in intent.excluded_concerns] == ["concern_acne"]
    assert "concern_brightening_spots" in [concern.tag_id for concern in intent.concerns]
    assert [effect.effect_id for effect in intent.priority_effects] == ["effect_brightening"]
    assert intent.needs_llm is False


def test_build_recommendation_intent_exposes_search_terms_and_semantic_text() -> None:
    repository = cached_repository(DATA_DIR)

    intent = build_recommendation_intent("속건조 보습 세럼 추천", repository=repository)

    assert "속건조" in intent.search_terms
    assert "보습·장벽" in intent.search_terms
    assert intent.semantic_query_text.startswith("속건조 보습 세럼 추천")
    assert "보습·장벽" in intent.semantic_query_text


def test_build_recommendation_intent_matches_sensitive_concern_from_main_data() -> None:
    repository = cached_repository(DATA_DIR)

    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)

    assert [concern.tag_id for concern in intent.concerns] == ["concern_sensitive"]
    assert intent.matched_concern_names == ("민감",)
    assert "진정" in intent.expected_effect_names
    assert "민감" in intent.search_terms
    assert "민감" not in intent.unmatched_terms
    assert intent.needs_llm is False


def test_build_recommendation_intent_marks_llm_fallback_need() -> None:
    repository = cached_repository(DATA_DIR)

    intent = build_recommendation_intent("까무잡잡한데 허예지고 싶어", repository=repository)

    assert intent.concerns == ()
    assert intent.effects == ()
    assert intent.unmatched_terms == ("까무잡잡한데 허예지고 싶어",)
    assert intent.needs_llm is True
