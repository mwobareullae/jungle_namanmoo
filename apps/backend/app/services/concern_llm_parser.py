import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.ai_logging import extract_chat_completion_usage_from_body, log_ai_call
from app.core.config import settings
from app.core.performance_logging import current_time, elapsed_ms
from app.services.parser import ConcernRepository, ParsedConcernResult


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
PROMPT_PATH = Path("prompts") / "concern_parser_system_prompt.md"
OPENAI_SCHEMA_PATH = Path("schemas") / "concern_parser_output_schema.openai.json"
REQUEST_TIMEOUT_SECONDS = 20


class ConcernLlmParserError(RuntimeError):
    pass


class ConcernLlmParser(Protocol):
    def parse(
        self,
        concern_text: str,
        rule_result: ParsedConcernResult,
        repository: ConcernRepository,
    ) -> "ConcernLlmParserOutput":
        ...


@dataclass(frozen=True)
class LlmMatchedConcern:
    tag_id: str
    matched_text: str
    confidence: float


@dataclass(frozen=True)
class LlmExpectedEffect:
    effect_id: str
    weight: float
    source: str


@dataclass(frozen=True)
class LlmPriorityEffect:
    effect_id: str
    reason: str


@dataclass(frozen=True)
class ConcernLlmParserOutput:
    matched_concerns: tuple[LlmMatchedConcern, ...]
    expected_effects: tuple[LlmExpectedEffect, ...]
    excluded_concerns: tuple[str, ...]
    priority_effects: tuple[LlmPriorityEffect, ...]
    unmatched_terms: tuple[str, ...]
    needs_review: bool
    confidence: float

    @classmethod
    def from_payload(
        cls,
        payload: object,
        repository: ConcernRepository,
    ) -> "ConcernLlmParserOutput":
        try:
            parsed = _ConcernParserPayload.model_validate(payload)
        except ValidationError as exc:
            raise ConcernLlmParserError("LLM concern parser output schema validation failed.") from exc

        _validate_known_ids(parsed, repository)
        return cls(
            matched_concerns=tuple(
                LlmMatchedConcern(
                    tag_id=item.tag_id,
                    matched_text=item.matched_text,
                    confidence=item.confidence,
                )
                for item in parsed.matched_concerns
            ),
            expected_effects=tuple(
                LlmExpectedEffect(
                    effect_id=item.effect_id,
                    weight=item.weight,
                    source=item.source,
                )
                for item in parsed.expected_effects
            ),
            excluded_concerns=tuple(parsed.excluded_concerns),
            priority_effects=tuple(
                LlmPriorityEffect(effect_id=item.effect_id, reason=item.reason)
                for item in parsed.priority_effects
            ),
            unmatched_terms=tuple(
                term.strip()
                for term in parsed.unmatched_terms
                if term and term.strip()
            ),
            needs_review=parsed.needs_review,
            confidence=parsed.confidence,
        )


class _MatchedConcernPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: str
    matched_text: str
    confidence: float = Field(ge=0, le=1)


class _ExpectedEffectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: str
    weight: float = Field(ge=0, le=1)
    source: str


class _PriorityEffectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: str
    reason: str


class _ConcernParserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched_concerns: list[_MatchedConcernPayload]
    expected_effects: list[_ExpectedEffectPayload]
    excluded_concerns: list[str]
    priority_effects: list[_PriorityEffectPayload]
    unmatched_terms: list[str]
    needs_review: bool
    confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class OpenAIConcernLlmParser:
    api_key: str = settings.openai_api_key
    model: str = settings.openai_model
    prompt_path: Path = Path(settings.data_dir) / PROMPT_PATH
    schema_path: Path = Path(settings.data_dir) / OPENAI_SCHEMA_PATH
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS

    def parse(
        self,
        concern_text: str,
        rule_result: ParsedConcernResult,
        repository: ConcernRepository,
    ) -> ConcernLlmParserOutput:
        if not self.api_key:
            raise ConcernLlmParserError("OPENAI_API_KEY is required for LLM concern parsing.")
        if not self.model:
            raise ConcernLlmParserError("OPENAI_MODEL is required for LLM concern parsing.")

        prompt = _read_text(self.prompt_path)
        schema = _read_json(self.schema_path)
        response_payload = self._request_structured_output(
            prompt=prompt,
            schema=schema,
            concern_text=concern_text,
            rule_result=rule_result,
        )
        return ConcernLlmParserOutput.from_payload(response_payload, repository)

    def _request_structured_output(
        self,
        *,
        prompt: str,
        schema: dict,
        concern_text: str,
        rule_result: ParsedConcernResult,
    ) -> object:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "concern_text": concern_text,
                                "rule_parser_partial": _rule_result_to_partial(rule_result),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "temperature": 0,
                "seed": 42,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": schema,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            OPENAI_CHAT_COMPLETIONS_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        started_at = current_time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            log_ai_call(
                "concern_parser",
                model=self.model,
                duration_ms=elapsed_ms(started_at),
                success=False,
                error="HTTPError",
                metadata={"status_code": exc.code},
            )
            raise ConcernLlmParserError(
                f"OpenAI concern parser request failed with status {exc.code}: "
                f"{_shorten(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            log_ai_call(
                "concern_parser",
                model=self.model,
                duration_ms=elapsed_ms(started_at),
                success=False,
                error=type(exc.reason).__name__ if getattr(exc, "reason", None) is not None else "URLError",
            )
            raise ConcernLlmParserError(f"OpenAI concern parser request failed: {exc}") from exc

        log_ai_call(
            "concern_parser",
            model=self.model,
            duration_ms=elapsed_ms(started_at),
            usage=extract_chat_completion_usage_from_body(body),
            metadata={"schema": "concern_parser_output"},
        )
        return _extract_chat_completion_json(body)


@lru_cache(maxsize=1)
def get_default_concern_llm_parser() -> OpenAIConcernLlmParser:
    return OpenAIConcernLlmParser()


def _extract_chat_completion_json(body: str) -> object:
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ConcernLlmParserError("OpenAI concern parser response was not valid JSON.") from exc

    choices = decoded.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ConcernLlmParserError("OpenAI concern parser response did not include choices.")

    message = choices[0].get("message", {})
    if isinstance(message, dict) and message.get("refusal"):
        raise ConcernLlmParserError("OpenAI concern parser refused the request.")

    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ConcernLlmParserError("OpenAI concern parser response did not include content.")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConcernLlmParserError("OpenAI concern parser content was not valid JSON.") from exc


def _rule_result_to_partial(rule_result: ParsedConcernResult) -> dict:
    return {
        "matched_concerns": [
            {
                "tag_id": concern.tag_id,
                "matched_text": concern.matched_text,
                "confidence": concern.confidence,
            }
            for concern in rule_result.concerns
        ],
        "expected_effects": [
            {
                "effect_id": effect.effect_id,
                "weight": effect.weight,
            }
            for effect in rule_result.effects
        ],
        "excluded_concerns": [
            {
                "tag_id": concern.tag_id,
                "matched_text": concern.matched_text,
                "reason": concern.reason,
            }
            for concern in rule_result.excluded_concerns
        ],
        "priority_effects": [
            {
                "effect_id": effect.effect_id,
                "weight": effect.weight,
            }
            for effect in rule_result.priority_effects
        ],
        "unmatched_terms": list(rule_result.unmatched_terms),
        "needs_llm": rule_result.needs_llm,
    }


def _validate_known_ids(parsed: _ConcernParserPayload, repository: ConcernRepository) -> None:
    concern_ids = {tag.tag_id for tag in repository.list_concern_tags()}
    effect_ids = {
        effect.effect_id
        for tag in repository.list_concern_tags()
        for effect in repository.get_effects_for_concern(tag.tag_id)
    }

    unknown_concerns = [
        item.tag_id
        for item in parsed.matched_concerns
        if item.tag_id not in concern_ids
    ]
    unknown_concerns.extend(
        concern_id
        for concern_id in parsed.excluded_concerns
        if concern_id not in concern_ids
    )
    if unknown_concerns:
        raise ConcernLlmParserError(
            f"LLM concern parser returned unknown concern ids: {sorted(set(unknown_concerns))}"
        )

    unknown_effects = [
        item.effect_id
        for item in [*parsed.expected_effects, *parsed.priority_effects]
        if item.effect_id not in effect_ids
    ]
    if unknown_effects:
        raise ConcernLlmParserError(
            f"LLM concern parser returned unknown effect ids: {sorted(set(unknown_effects))}"
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConcernLlmParserError(f"LLM parser prompt file is not readable: {path}") from exc


def _read_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConcernLlmParserError(f"LLM parser schema file is not readable: {path}") from exc
    if not isinstance(value, dict):
        raise ConcernLlmParserError(f"LLM parser schema file must contain an object: {path}")
    return value


def _shorten(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."
