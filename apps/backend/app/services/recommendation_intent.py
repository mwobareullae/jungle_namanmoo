from dataclasses import dataclass

from app.core.performance_logging import current_time, elapsed_ms
from app.services.concern_repository import get_default_concern_repository
from app.services.concern_llm_parser import (
    ConcernLlmParser,
    ConcernLlmParserError,
    ConcernLlmParserOutput,
)
from app.services.parser import (
    ConcernRepository,
    ParsedConcern,
    ParsedEffect,
    ParsedExcludedConcern,
    ParsedConcernResult,
    parse_concern_text,
)
from app.services.purchase_conditions import ParsedPurchaseConditions, parse_purchase_conditions


@dataclass(frozen=True)
class RecommendationIntent:
    concern_text: str
    normalized_text: str
    purchase_conditions: ParsedPurchaseConditions
    concerns: tuple[ParsedConcern, ...]
    effects: tuple[ParsedEffect, ...]
    excluded_concerns: tuple[ParsedExcludedConcern, ...]
    priority_effects: tuple[ParsedEffect, ...]
    unmatched_terms: tuple[str, ...]
    needs_llm: bool
    llm_used: bool = False
    needs_review: bool = False
    parser_confidence: float | None = None
    llm_error: str | None = None

    @property
    def matched_concern_names(self) -> tuple[str, ...]:
        return tuple(concern.name for concern in self.concerns)

    @property
    def expected_effect_names(self) -> tuple[str, ...]:
        return tuple(effect.name for effect in self.effects)

    @property
    def search_terms(self) -> tuple[str, ...]:
        terms = [
            *(concern.name for concern in self.concerns),
            *(effect.name for effect in self.effects),
            *(effect.name for effect in self.priority_effects),
        ]
        return _dedupe_terms(terms)

    @property
    def semantic_query_text(self) -> str:
        terms = " ".join(self.search_terms)
        if not terms:
            return self.concern_text
        return f"{self.concern_text} {terms}"


def build_recommendation_intent(
    concern_text: str,
    *,
    repository: ConcernRepository | None = None,
    llm_parser: ConcernLlmParser | None = None,
    diagnostics: dict[str, object] | None = None,
) -> RecommendationIntent:
    intent_diagnostics = diagnostics if diagnostics is not None else {}
    intent_diagnostics.update(
        {
            "intent_input_length": len(concern_text),
            "intent_llm_attempted": False,
            "intent_llm_http_attempted": False,
            "intent_llm_call_ms": 0.0,
            "intent_llm_prompt_load_ms": 0.0,
            "intent_llm_schema_load_ms": 0.0,
            "intent_llm_request_build_ms": 0.0,
            "intent_llm_http_ms": 0.0,
            "intent_llm_response_parse_ms": 0.0,
            "intent_llm_schema_validate_ms": 0.0,
            "intent_llm_merge_ms": 0.0,
            "intent_llm_status_code": None,
            "intent_llm_error_code": None,
        }
    )
    repository_started_at = current_time()
    concern_repository = repository or get_default_concern_repository()
    _record_diagnostic_duration(
        intent_diagnostics,
        "intent_repository_load_ms",
        repository_started_at,
    )
    rule_started_at = current_time()
    parsed_concern = parse_concern_text(concern_text, concern_repository)
    _record_diagnostic_duration(
        intent_diagnostics,
        "intent_rule_parse_ms",
        rule_started_at,
    )
    intent_diagnostics["intent_rule_needs_llm"] = parsed_concern.needs_llm
    intent_diagnostics["intent_rule_matched_concern_count"] = len(
        parsed_concern.concerns
    )
    intent_diagnostics["intent_rule_unmatched_term_count"] = len(
        parsed_concern.unmatched_terms
    )
    llm_used = False
    needs_review = False
    parser_confidence: float | None = None
    llm_error: str | None = None

    if parsed_concern.needs_llm and llm_parser is not None:
        intent_diagnostics["intent_llm_attempted"] = True
        llm_started_at = current_time()
        try:
            llm_result = llm_parser.parse(
                concern_text,
                parsed_concern,
                concern_repository,
                diagnostics=intent_diagnostics,
            )
            merge_started_at = current_time()
            try:
                parsed_concern = _merge_llm_result(
                    parsed_concern,
                    llm_result,
                    concern_repository,
                )
            finally:
                _record_diagnostic_duration(
                    intent_diagnostics,
                    "intent_llm_merge_ms",
                    merge_started_at,
                )
            llm_used = True
            needs_review = llm_result.needs_review
            parser_confidence = llm_result.confidence
            intent_diagnostics["intent_llm_outcome"] = "success"
        except ConcernLlmParserError as exc:
            llm_error = str(exc)
            intent_diagnostics["intent_llm_outcome"] = exc.code
            intent_diagnostics["intent_llm_error_code"] = exc.code
            if exc.status_code is not None:
                intent_diagnostics["intent_llm_status_code"] = exc.status_code
        finally:
            _record_diagnostic_duration(
                intent_diagnostics,
                "intent_llm_call_ms",
                llm_started_at,
            )
    elif parsed_concern.needs_llm:
        intent_diagnostics["intent_llm_outcome"] = "disabled"
    else:
        intent_diagnostics["intent_llm_outcome"] = "not_needed"

    purchase_started_at = current_time()
    purchase_conditions = parse_purchase_conditions(
        concern_text,
        diagnostics=intent_diagnostics,
    )
    _record_diagnostic_duration(
        intent_diagnostics,
        "intent_purchase_parse_ms",
        purchase_started_at,
    )
    intent_diagnostics["intent_llm_used"] = llm_used
    intent_diagnostics["intent_final_needs_llm"] = parsed_concern.needs_llm

    return RecommendationIntent(
        concern_text=concern_text,
        normalized_text=parsed_concern.normalized_text,
        purchase_conditions=purchase_conditions,
        concerns=parsed_concern.concerns,
        effects=parsed_concern.effects,
        excluded_concerns=parsed_concern.excluded_concerns,
        priority_effects=parsed_concern.priority_effects,
        unmatched_terms=parsed_concern.unmatched_terms,
        needs_llm=parsed_concern.needs_llm,
        llm_used=llm_used,
        needs_review=needs_review,
        parser_confidence=parser_confidence,
        llm_error=llm_error,
    )


def _record_diagnostic_duration(
    diagnostics: dict[str, object],
    key: str,
    started_at: float,
) -> None:
    diagnostics[key] = round(elapsed_ms(started_at), 2)


def _dedupe_terms(terms: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if normalized and normalized not in seen:
            deduped.append(term)
            seen.add(normalized)
    return tuple(deduped)


def _merge_llm_result(
    rule_result: ParsedConcernResult,
    llm_result: ConcernLlmParserOutput,
    repository: ConcernRepository,
) -> ParsedConcernResult:
    tags_by_id = {tag.tag_id: tag for tag in repository.list_concern_tags()}
    effects_by_id = _effects_by_id(repository)
    excluded_ids = set(llm_result.excluded_concerns)

    concerns = tuple(
        ParsedConcern(
            tag_id=item.tag_id,
            name=tags_by_id[item.tag_id].name,
            matched_text=item.matched_text,
            confidence=item.confidence,
        )
        for item in llm_result.matched_concerns
        if item.tag_id not in excluded_ids
    )
    effects = tuple(
        ParsedEffect(
            effect_id=item.effect_id,
            name=effects_by_id.get(item.effect_id, item.effect_id),
            weight=item.weight,
        )
        for item in llm_result.expected_effects
    ) or _effects_from_concerns(concerns, repository)
    excluded_concerns = _merge_excluded_concerns(
        rule_result.excluded_concerns,
        llm_result.excluded_concerns,
        tags_by_id,
    )
    priority_effects = tuple(
        ParsedEffect(
            effect_id=item.effect_id,
            name=effects_by_id.get(item.effect_id, item.effect_id),
            weight=_effect_weight(effects, item.effect_id),
        )
        for item in llm_result.priority_effects
    )

    return ParsedConcernResult(
        normalized_text=rule_result.normalized_text,
        concerns=concerns,
        effects=effects,
        excluded_concerns=excluded_concerns,
        priority_effects=priority_effects,
        unmatched_terms=llm_result.unmatched_terms,
        needs_llm=False,
    )


def _effects_by_id(repository: ConcernRepository) -> dict[str, str]:
    effects: dict[str, str] = {}
    for tag in repository.list_concern_tags():
        for effect in repository.get_effects_for_concern(tag.tag_id):
            effects.setdefault(effect.effect_id, effect.effect_name)
    return effects


def _effects_from_concerns(
    concerns: tuple[ParsedConcern, ...],
    repository: ConcernRepository,
) -> tuple[ParsedEffect, ...]:
    effects_by_id: dict[str, ParsedEffect] = {}
    for concern in concerns:
        for effect in repository.get_effects_for_concern(concern.tag_id):
            existing = effects_by_id.get(effect.effect_id)
            if existing is None or effect.weight > existing.weight:
                effects_by_id[effect.effect_id] = ParsedEffect(
                    effect_id=effect.effect_id,
                    name=effect.effect_name,
                    weight=effect.weight,
                )
    return tuple(effects_by_id.values())


def _merge_excluded_concerns(
    rule_excluded: tuple[ParsedExcludedConcern, ...],
    llm_excluded_ids: tuple[str, ...],
    tags_by_id: dict,
) -> tuple[ParsedExcludedConcern, ...]:
    excluded_by_id = {concern.tag_id: concern for concern in rule_excluded}
    for tag_id in llm_excluded_ids:
        if tag_id in excluded_by_id:
            continue
        tag = tags_by_id.get(tag_id)
        if tag is None:
            continue
        excluded_by_id[tag_id] = ParsedExcludedConcern(
            tag_id=tag_id,
            name=tag.name,
            matched_text=tag.name,
            reason="llm_excluded",
        )
    return tuple(excluded_by_id.values())


def _effect_weight(effects: tuple[ParsedEffect, ...], effect_id: str) -> float:
    for effect in effects:
        if effect.effect_id == effect_id:
            return effect.weight
    return 1.0
