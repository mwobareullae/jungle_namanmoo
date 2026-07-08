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
from app.services.recommendation_intent import build_recommendation_intent
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


def test_build_recommendation_intent_falls_back_when_llm_parser_fails() -> None:
    repository = cached_repository(DATA_DIR)
    llm_parser = _FailingConcernLlmParser()

    intent = build_recommendation_intent(
        "unknown concern",
        repository=repository,
        llm_parser=llm_parser,
    )

    assert llm_parser.calls == 1
    assert intent.concerns == ()
    assert intent.effects == ()
    assert intent.unmatched_terms == ("unknown concern",)
    assert intent.needs_llm is True
    assert intent.llm_used is False
    assert intent.llm_error == "boom"


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


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

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
    ) -> ConcernLlmParserOutput:
        self.calls += 1
        raise ConcernLlmParserError("boom")
