import re
from dataclasses import dataclass
from typing import Protocol

from app.models.data_contract import ConcernEffect, ConcernTag


class ConcernRepository(Protocol):
    def list_concern_tags(self) -> list[ConcernTag]:
        pass

    def get_effects_for_concern(self, tag_id: str) -> list[ConcernEffect]:
        pass


@dataclass(frozen=True)
class ParsedConcern:
    tag_id: str
    name: str
    matched_text: str
    confidence: float


@dataclass(frozen=True)
class ParsedEffect:
    effect_id: str
    name: str
    weight: float


@dataclass(frozen=True)
class ParsedConcernResult:
    normalized_text: str
    concerns: tuple[ParsedConcern, ...]
    effects: tuple[ParsedEffect, ...]
    unmatched_terms: tuple[str, ...]


def parse_concern_text(
    concern_text: str,
    repository: ConcernRepository,
) -> ParsedConcernResult:
    normalized_text = _normalize_text(concern_text)
    if not normalized_text:
        return ParsedConcernResult(
            normalized_text="",
            concerns=(),
            effects=(),
            unmatched_terms=(),
        )

    concerns = _match_concerns(normalized_text, repository.list_concern_tags())
    effects = _build_effects(concerns, repository)
    unmatched_terms = _build_unmatched_terms(normalized_text, concerns)

    return ParsedConcernResult(
        normalized_text=normalized_text,
        concerns=tuple(concerns),
        effects=tuple(effects),
        unmatched_terms=tuple(unmatched_terms),
    )


def _match_concerns(
    normalized_text: str,
    concern_tags: list[ConcernTag],
) -> list[ParsedConcern]:
    matched_concerns: list[ParsedConcern] = []
    for tag in concern_tags:
        matched_text = _find_best_match(normalized_text, _tag_match_terms(tag))
        if matched_text is None:
            continue

        matched_concerns.append(
            ParsedConcern(
                tag_id=tag.tag_id,
                name=tag.name,
                matched_text=matched_text,
                confidence=1.0,
            )
        )
    return matched_concerns


def _build_effects(
    concerns: list[ParsedConcern],
    repository: ConcernRepository,
) -> list[ParsedEffect]:
    effects_by_id: dict[str, ParsedEffect] = {}
    for concern in concerns:
        for effect in repository.get_effects_for_concern(concern.tag_id):
            existing_effect = effects_by_id.get(effect.effect_id)
            if existing_effect is None or effect.weight > existing_effect.weight:
                effects_by_id[effect.effect_id] = ParsedEffect(
                    effect_id=effect.effect_id,
                    name=effect.effect_name,
                    weight=effect.weight,
                )

    return list(effects_by_id.values())


def _build_unmatched_terms(
    normalized_text: str,
    concerns: list[ParsedConcern],
) -> list[str]:
    if not concerns:
        return [normalized_text]

    matched_terms = [concern.matched_text for concern in concerns]
    unmatched_terms: list[str] = []
    for phrase in _split_phrases(normalized_text):
        if any(_matches_text(phrase, term) for term in matched_terms):
            continue
        unmatched_terms.append(phrase)
    return unmatched_terms


def _find_best_match(normalized_text: str, terms: list[str]) -> str | None:
    matched_terms = [term for term in terms if _matches_text(normalized_text, term)]
    if not matched_terms:
        return None
    return max(matched_terms, key=len)


def _matches_text(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    return normalized_term in normalized_text or _compact(normalized_term) in _compact(normalized_text)


def _tag_match_terms(tag: ConcernTag) -> list[str]:
    return [tag.name, *tag.synonyms]


def _split_phrases(normalized_text: str) -> list[str]:
    phrases = re.split(r"\s*(?:,|/|;|&|그리고|및|하고|랑|와|과)\s*", normalized_text)
    return [phrase.strip() for phrase in phrases if phrase.strip()]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)
