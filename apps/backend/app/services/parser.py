import re
from dataclasses import dataclass
from typing import Protocol

from app.models.data_contract import ConcernEffect, ConcernTag


NEGATION_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"상관\s*(?:이\s*)?없",
        r"딱히\s*(?:없|상관\s*없)",
        r"필요\s*없",
        r"관심\s*없",
        r"고민\s*(?:은\s*)?아니",
        r"아니(?:고|라|야|에요|예요|다|라는)",
        r"신경\s*안\s*써도\s*돼",
        r"안\s*그래도\s*돼",
        r"굳이",
        r"그닥",
        r"패스",
        r"넘어가고",
        r"안\s*중요",
        r"싫고",
        r"말고",
        r"제외",
        r"빼고",
        r"괜찮",
        r"없(?:어|고|는데|지만|다|음)",
    )
)

PRIORITY_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"집중",
        r"위주",
        r"우선",
        r"중요",
        r"제일",
        r"먼저",
        r"가장",
        r"특히",
        r"중점적",
        r"핵심은",
        r"무엇보다",
        r"신경\s*쓰고\s*싶은\s*건",
        r"focus",
        r"main",
    )
)

AMBIGUOUS_NATURAL_LANGUAGE_TERMS = (
    "허예",
    "하얘",
    "하예",
    "밝아",
    "환해",
    "까무잡잡",
    "어두워",
    "피곤해 보",
    "힘없",
    "빤딱",
    "번쩍",
    "광나",
)

TEMPORAL_SHIFT_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:예전|예전엔|예전에는|전엔|전에는|과거|이전|옛날)(?:.{0,40})(?:지금|요즘|현재|이제)",
        r"(?:전에|예전에)(?:.{0,40})(?:지금은|요즘은|현재는|이제는)",
    )
)


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
class ParsedExcludedConcern:
    tag_id: str
    name: str
    matched_text: str
    reason: str


@dataclass(frozen=True)
class ParsedEffect:
    effect_id: str
    name: str
    weight: float


@dataclass(frozen=True)
class _MatchedEffect:
    effect: ParsedEffect
    matched_text: str
    start: int
    end: int


@dataclass(frozen=True)
class _TermMatch:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ParsedConcernResult:
    normalized_text: str
    concerns: tuple[ParsedConcern, ...]
    effects: tuple[ParsedEffect, ...]
    excluded_concerns: tuple[ParsedExcludedConcern, ...]
    priority_effects: tuple[ParsedEffect, ...]
    unmatched_terms: tuple[str, ...]
    needs_llm: bool


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
            excluded_concerns=(),
            priority_effects=(),
            unmatched_terms=(),
            needs_llm=False,
        )

    concern_tags = repository.list_concern_tags()
    concerns, excluded_concerns = _match_concerns(normalized_text, concern_tags)
    direct_effects = _match_direct_effects(normalized_text, concern_tags, repository)
    effects = _build_effects(concerns, direct_effects, repository)
    priority_effects = _build_priority_effects(normalized_text, concerns, direct_effects, repository)
    unmatched_terms = _build_unmatched_terms(
        normalized_text,
        concerns,
        direct_effects,
        excluded_concerns,
    )

    return ParsedConcernResult(
        normalized_text=normalized_text,
        concerns=tuple(concerns),
        effects=tuple(effects),
        excluded_concerns=tuple(excluded_concerns),
        priority_effects=tuple(priority_effects),
        unmatched_terms=tuple(unmatched_terms),
        needs_llm=_needs_llm(normalized_text, concerns, effects, unmatched_terms),
    )


def _match_concerns(
    normalized_text: str,
    concern_tags: list[ConcernTag],
) -> tuple[list[ParsedConcern], list[ParsedExcludedConcern]]:
    matched_concerns: list[ParsedConcern] = []
    excluded_concerns: list[ParsedExcludedConcern] = []
    for tag in concern_tags:
        match = _find_best_match(normalized_text, _tag_match_terms(tag))
        if match is None:
            continue

        if _has_negation_context(normalized_text, match.start, match.end):
            excluded_concerns.append(
                ParsedExcludedConcern(
                    tag_id=tag.tag_id,
                    name=tag.name,
                    matched_text=match.text,
                    reason="negated_or_irrelevant",
                )
            )
            continue

        matched_concerns.append(
            ParsedConcern(
                tag_id=tag.tag_id,
                name=tag.name,
                matched_text=match.text,
                confidence=1.0,
            )
        )
    return matched_concerns, excluded_concerns


def _build_effects(
    concerns: list[ParsedConcern],
    direct_effects: list[_MatchedEffect],
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

    for matched_effect in direct_effects:
        effect = matched_effect.effect
        existing_effect = effects_by_id.get(effect.effect_id)
        if existing_effect is None or effect.weight > existing_effect.weight:
            effects_by_id[effect.effect_id] = effect

    return list(effects_by_id.values())


def _build_unmatched_terms(
    normalized_text: str,
    concerns: list[ParsedConcern],
    direct_effects: list[_MatchedEffect],
    excluded_concerns: list[ParsedExcludedConcern],
) -> list[str]:
    matched_terms = [
        *(concern.matched_text for concern in concerns),
        *(effect.matched_text for effect in direct_effects),
        *(concern.matched_text for concern in excluded_concerns),
    ]
    if not matched_terms:
        return [normalized_text]

    unmatched_terms: list[str] = []
    for phrase in _split_phrases(normalized_text):
        if any(_matches_text(phrase, term) for term in matched_terms):
            continue
        unmatched_terms.append(phrase)
    return unmatched_terms


def _build_priority_effects(
    normalized_text: str,
    concerns: list[ParsedConcern],
    direct_effects: list[_MatchedEffect],
    repository: ConcernRepository,
) -> list[ParsedEffect]:
    priority_effects_by_id: dict[str, ParsedEffect] = {}

    if not _has_priority_context(normalized_text, 0, len(normalized_text)):
        return []

    for concern in concerns:
        match = _find_first_match(normalized_text, concern.matched_text)
        if match is None or not _has_priority_context(normalized_text, match.start, match.end):
            continue

        for effect in repository.get_effects_for_concern(concern.tag_id):
            priority_effects_by_id[effect.effect_id] = ParsedEffect(
                effect_id=effect.effect_id,
                name=effect.effect_name,
                weight=effect.weight,
            )

    for matched_effect in direct_effects:
        if _has_priority_context(normalized_text, matched_effect.start, matched_effect.end):
            priority_effects_by_id[matched_effect.effect.effect_id] = matched_effect.effect

    return list(priority_effects_by_id.values())


def _match_direct_effects(
    normalized_text: str,
    concern_tags: list[ConcernTag],
    repository: ConcernRepository,
) -> list[_MatchedEffect]:
    matched_by_id: dict[str, _MatchedEffect] = {}
    for tag in concern_tags:
        for concern_effect in repository.get_effects_for_concern(tag.tag_id):
            match = _find_best_match(normalized_text, _effect_match_terms(concern_effect))
            if match is None:
                continue
            if _has_negation_context(normalized_text, match.start, match.end):
                continue

            parsed_effect = ParsedEffect(
                effect_id=concern_effect.effect_id,
                name=concern_effect.effect_name,
                weight=1.0,
            )
            current = matched_by_id.get(parsed_effect.effect_id)
            matched_effect = _MatchedEffect(
                effect=parsed_effect,
                matched_text=match.text,
                start=match.start,
                end=match.end,
            )
            if current is None or len(match.text) > len(current.matched_text):
                matched_by_id[parsed_effect.effect_id] = matched_effect

    return list(matched_by_id.values())


def _find_best_match(normalized_text: str, terms: list[str]) -> _TermMatch | None:
    matched_terms = [
        match
        for term in terms
        if (match := _find_first_match(normalized_text, term)) is not None
    ]
    if not matched_terms:
        return None
    return max(matched_terms, key=lambda match: len(match.text))


def _find_first_match(normalized_text: str, term: str) -> _TermMatch | None:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return None

    direct_position = normalized_text.find(normalized_term)
    if direct_position >= 0:
        return _TermMatch(
            text=term,
            start=direct_position,
            end=direct_position + len(normalized_term),
        )

    compact_text = _compact(normalized_text)
    compact_term = _compact(normalized_term)
    compact_position = compact_text.find(compact_term)
    if compact_position < 0:
        return None

    return _TermMatch(text=term, start=0, end=len(normalized_text))


def _matches_text(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    return normalized_term in normalized_text or _compact(normalized_term) in _compact(normalized_text)


def _tag_match_terms(tag: ConcernTag) -> list[str]:
    return [tag.name, *tag.synonyms]


def _effect_match_terms(effect: ConcernEffect) -> list[str]:
    terms = [effect.effect_name]
    terms.extend(
        term
        for term in re.split(r"[·/\s]+", effect.effect_name)
        if len(term) >= 2 and term not in {"조절", "강화", "정돈"}
    )
    return _dedupe_terms(terms)


def _has_negation_context(normalized_text: str, start: int, end: int) -> bool:
    window = normalized_text[start : min(len(normalized_text), end + 20)]
    return any(pattern.search(window) is not None for pattern in NEGATION_CONTEXT_PATTERNS)


def _has_priority_context(normalized_text: str, start: int, end: int) -> bool:
    window = normalized_text[max(0, start - 10) : min(len(normalized_text), end + 16)]
    return any(pattern.search(window) is not None for pattern in PRIORITY_CONTEXT_PATTERNS)


def _needs_llm(
    normalized_text: str,
    concerns: list[ParsedConcern],
    effects: list[ParsedEffect],
    unmatched_terms: list[str],
) -> bool:
    if _has_ambiguous_natural_language(normalized_text):
        return True
    if _has_temporal_shift_context(normalized_text):
        return True
    if not concerns and not effects:
        return True
    return bool(unmatched_terms and len(" ".join(unmatched_terms)) >= 8)


def _has_ambiguous_natural_language(normalized_text: str) -> bool:
    return any(term in normalized_text for term in AMBIGUOUS_NATURAL_LANGUAGE_TERMS)


def _has_temporal_shift_context(normalized_text: str) -> bool:
    return any(pattern.search(normalized_text) is not None for pattern in TEMPORAL_SHIFT_CONTEXT_PATTERNS)


def _split_phrases(normalized_text: str) -> list[str]:
    phrases = re.split(r"\s*(?:,|/|;|&|그리고|및|하고|랑|와|과)\s*", normalized_text)
    return [phrase.strip() for phrase in phrases if phrase.strip()]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _dedupe_terms(terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _normalize_text(term)
        if normalized and normalized not in seen:
            deduped.append(term)
            seen.add(normalized)
    return deduped
