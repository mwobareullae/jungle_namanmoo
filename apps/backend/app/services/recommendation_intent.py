from dataclasses import dataclass

from app.services.concern_repository import get_default_concern_repository
from app.services.parser import (
    ConcernRepository,
    ParsedConcern,
    ParsedEffect,
    ParsedExcludedConcern,
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
) -> RecommendationIntent:
    concern_repository = repository or get_default_concern_repository()
    parsed_concern = parse_concern_text(concern_text, concern_repository)
    purchase_conditions = parse_purchase_conditions(concern_text)

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
    )


def _dedupe_terms(terms: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if normalized and normalized not in seen:
            deduped.append(term)
            seen.add(normalized)
    return tuple(deduped)
