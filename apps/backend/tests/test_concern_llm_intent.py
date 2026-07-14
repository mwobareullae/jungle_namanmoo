import json
from pathlib import Path

import pytest

from app.services.concern_llm_parser import (
    ConcernLlmParserError,
    ConcernLlmParserOutput,
    LlmExpectedEffect,
    LlmMatchedConcern,
    LlmPriorityEffect,
    OpenAIConcernLlmParser,
)
from app.services.parser import ConcernRepository, ParsedConcernResult, parse_concern_text
from app.services.recommendation_intent import (
    StructuredRecommendationIntent,
    build_recommendation_intent,
)
from tests.repository_cache import cached_repository


def _resolve_data_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if candidate.exists():
            return candidate
    return Path("/data")


DATA_DIR = _resolve_data_dir()
pytestmark = pytest.mark.slow


def test_build_recommendation_intent_merges_llm_parser_output() -> None:
    repository = cached_repository(DATA_DIR)
    diagnostics: dict[str, object] = {}
    llm_parser = _FakeConcernLlmParser(
        ConcernLlmParserOutput(
            matched_concerns=(
                LlmMatchedConcern(
                    tag_id="concern_dull_uneven_tone",
                    matched_text="brighten uneven tone",
                    confidence=0.84,
                ),
            ),
            expected_effects=(
                LlmExpectedEffect(
                    effect_id="effect_brightening",
                    weight=1.0,
                    source="semantic_inference",
                ),
                LlmExpectedEffect(
                    effect_id="effect_exfoliation",
                    weight=0.5,
                    source="concern_to_effect",
                ),
            ),
            excluded_concerns=(),
            priority_effects=(
                LlmPriorityEffect(
                    effect_id="effect_brightening",
                    reason="brightening is the main user intent",
                ),
            ),
            unmatched_terms=(),
            needs_review=False,
            confidence=0.84,
        )
    )

    intent = build_recommendation_intent(
        "brighten uneven tone",
        repository=repository,
        llm_parser=llm_parser,
        diagnostics=diagnostics,
    )

    assert llm_parser.calls == 1
    assert [concern.tag_id for concern in intent.concerns] == ["concern_dull_uneven_tone"]
    assert [effect.effect_id for effect in intent.effects] == [
        "effect_brightening",
        "effect_exfoliation",
    ]
    assert [effect.effect_id for effect in intent.priority_effects] == ["effect_brightening"]
    assert intent.unmatched_terms == ()
    assert intent.needs_llm is False
    assert intent.llm_used is True
    assert intent.needs_review is False
    assert intent.parser_confidence == 0.84
    assert diagnostics["intent_rule_needs_llm"] is True
    assert float(diagnostics["intent_repository_load_ms"]) >= 0
    assert diagnostics["intent_llm_attempted"] is True
    assert diagnostics["intent_llm_outcome"] == "success"
    assert diagnostics["intent_llm_used"] is True
    assert float(diagnostics["intent_llm_call_ms"]) >= 0
    assert float(diagnostics["intent_llm_merge_ms"]) >= 0
    assert float(diagnostics["intent_purchase_parse_ms"]) >= 0
    assert float(diagnostics["intent_purchase_normalize_ms"]) >= 0
    assert float(diagnostics["intent_purchase_price_ms"]) >= 0
    assert float(diagnostics["intent_purchase_category_ms"]) >= 0
    assert float(diagnostics["intent_purchase_brand_alias_load_ms"]) >= 0
    assert float(diagnostics["intent_purchase_brand_match_ms"]) >= 0


def test_build_recommendation_intent_uses_structured_agent_intent_without_llm() -> None:
    repository = cached_repository(DATA_DIR)
    diagnostics: dict[str, object] = {}
    llm_parser = _FailingConcernLlmParser()

    intent = build_recommendation_intent(
        "화장이 들뜨지 않는 3만원 이하 세럼 추천",
        repository=repository,
        llm_parser=llm_parser,
        structured_intent=StructuredRecommendationIntent(
            resolved=True,
            concern_ids=("concern_dry_barrier",),
            effect_ids=("effect_moisture_barrier",),
            priority_effect_ids=("effect_moisture_barrier",),
            category_codes=("serum",),
            price_max=30_000,
        ),
        diagnostics=diagnostics,
    )

    assert llm_parser.calls == 0
    assert [concern.tag_id for concern in intent.concerns] == ["concern_dry_barrier"]
    assert "effect_moisture_barrier" in [effect.effect_id for effect in intent.effects]
    assert [effect.effect_id for effect in intent.priority_effects] == [
        "effect_moisture_barrier"
    ]
    assert [category.category_code for category in intent.purchase_conditions.categories] == [
        "serum"
    ]
    assert intent.purchase_conditions.price_max == 30_000
    assert intent.purchase_conditions.price_text == "30000원 이하"
    assert intent.unmatched_terms == ()
    assert intent.llm_used is False
    assert diagnostics["intent_structured_applied"] is True
    assert diagnostics["intent_llm_attempted"] is False
    assert diagnostics["intent_llm_outcome"] == "structured_agent"


def test_build_recommendation_intent_falls_back_when_llm_parser_fails() -> None:
    repository = cached_repository(DATA_DIR)
    diagnostics: dict[str, object] = {}
    llm_parser = _FailingConcernLlmParser()

    intent = build_recommendation_intent(
        "unknown concern",
        repository=repository,
        llm_parser=llm_parser,
        diagnostics=diagnostics,
    )

    assert llm_parser.calls == 1
    assert intent.concerns == ()
    assert intent.effects == ()
    assert intent.unmatched_terms == ("unknown concern",)
    assert intent.needs_llm is True
    assert intent.llm_used is False
    assert intent.llm_error == "boom"
    assert diagnostics["intent_llm_attempted"] is True
    assert diagnostics["intent_llm_outcome"] == "timeout"
    assert diagnostics["intent_llm_error_code"] == "timeout"
    assert diagnostics["intent_llm_used"] is False


def test_build_recommendation_intent_marks_disabled_llm() -> None:
    repository = cached_repository(DATA_DIR)
    diagnostics: dict[str, object] = {}

    intent = build_recommendation_intent(
        "unknown concern",
        repository=repository,
        diagnostics=diagnostics,
    )

    assert intent.needs_llm is True
    assert diagnostics["intent_rule_needs_llm"] is True
    assert diagnostics["intent_llm_attempted"] is False
    assert diagnostics["intent_llm_http_attempted"] is False
    assert diagnostics["intent_llm_outcome"] == "disabled"


def test_concern_llm_parser_output_rejects_unknown_ids() -> None:
    repository = cached_repository(DATA_DIR)

    try:
        ConcernLlmParserOutput.from_payload(
            {
                "matched_concerns": [
                    {
                        "tag_id": "concern_unknown",
                        "matched_text": "unknown",
                        "confidence": 0.7,
                    }
                ],
                "expected_effects": [],
                "excluded_concerns": [],
                "priority_effects": [],
                "unmatched_terms": [],
                "needs_review": True,
                "confidence": 0.7,
            },
            repository,
        )
    except ConcernLlmParserError as exc:
        assert "unknown concern ids" in str(exc)
    else:
        raise AssertionError("unknown concern id should fail validation")


def test_openai_concern_llm_parser_sends_deterministic_seed(monkeypatch) -> None:
    repository = cached_repository(DATA_DIR)
    rule_result = parse_concern_text("까무잡잡한데 밝아지고 싶어", repository)
    captured_payload: dict = {}

    def fake_urlopen(request, timeout):
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "matched_concerns": [],
                                    "expected_effects": [],
                                    "excluded_concerns": [],
                                    "priority_effects": [],
                                    "unmatched_terms": [],
                                    "needs_review": False,
                                    "confidence": 0,
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    parser = OpenAIConcernLlmParser(api_key="test-key", model="gpt-test")
    parser._request_structured_output(
        prompt="system prompt",
        schema={"name": "concern_parser_output", "schema": {"type": "object"}},
        concern_text="까무잡잡한데 밝아지고 싶어",
        rule_result=rule_result,
    )

    assert captured_payload["temperature"] == 0
    assert captured_payload["seed"] == 42


def test_openai_concern_llm_parser_classifies_timeout(monkeypatch) -> None:
    repository = cached_repository(DATA_DIR)
    rule_result = parse_concern_text("까무잡잡한데 밝아지고 싶어", repository)
    diagnostics: dict[str, object] = {}

    def fake_urlopen(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    parser = OpenAIConcernLlmParser(api_key="test-key", model="gpt-test")

    with pytest.raises(ConcernLlmParserError) as exc_info:
        parser._request_structured_output(
            prompt="system prompt",
            schema={"name": "concern_parser_output", "schema": {"type": "object"}},
            concern_text="까무잡잡한데 밝아지고 싶어",
            rule_result=rule_result,
            diagnostics=diagnostics,
        )

    assert exc_info.value.code == "timeout"
    assert diagnostics["intent_llm_http_attempted"] is True
    assert float(diagnostics["intent_llm_http_ms"]) >= 0


def test_openai_concern_llm_parser_records_success_diagnostics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repository = cached_repository(DATA_DIR)
    rule_result = parse_concern_text("까무잡잡한데 밝아지고 싶어", repository)
    prompt_path = tmp_path / "prompt.md"
    schema_path = tmp_path / "schema.json"
    prompt_path.write_text("system prompt", encoding="utf-8")
    schema_path.write_text(
        json.dumps({"name": "concern_parser_output", "schema": {"type": "object"}}),
        encoding="utf-8",
    )

    def fake_urlopen(*_args, **_kwargs):
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "matched_concerns": [],
                                    "expected_effects": [],
                                    "excluded_concerns": [],
                                    "priority_effects": [],
                                    "unmatched_terms": [],
                                    "needs_review": False,
                                    "confidence": 0,
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    parser = OpenAIConcernLlmParser(
        api_key="test-key",
        model="gpt-test",
        prompt_path=prompt_path,
        schema_path=schema_path,
    )
    diagnostics: dict[str, object] = {}

    output = parser.parse(
        "까무잡잡한데 밝아지고 싶어",
        rule_result,
        repository,
        diagnostics=diagnostics,
    )

    assert output.confidence == 0
    assert diagnostics["intent_llm_outcome"] == "success"
    assert diagnostics["intent_llm_http_attempted"] is True
    assert diagnostics["intent_llm_status_code"] == 200
    assert float(diagnostics["intent_llm_response_parse_ms"]) >= 0
    assert float(diagnostics["intent_llm_schema_validate_ms"]) >= 0


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _FakeConcernLlmParser:
    def __init__(self, output: ConcernLlmParserOutput) -> None:
        self.output = output
        self.calls = 0

    def parse(
        self,
        concern_text: str,
        rule_result: ParsedConcernResult,
        repository: ConcernRepository,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> ConcernLlmParserOutput:
        self.calls += 1
        assert concern_text
        assert rule_result.needs_llm is True
        assert repository.list_concern_tags()
        return self.output


class _FailingConcernLlmParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(
        self,
        concern_text: str,
        rule_result: ParsedConcernResult,
        repository: ConcernRepository,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> ConcernLlmParserOutput:
        self.calls += 1
        raise ConcernLlmParserError("boom", code="timeout")
