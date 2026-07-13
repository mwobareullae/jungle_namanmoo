#!/usr/bin/env python3
"""Classify observed paper-result direction against reviewed outcome metrics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from effect_outcome_dictionary import (
    EFFECT_IDS,
    OutcomeMatch,
    OutcomeTerm,
    match_outcome_matches,
    normalize_phrase,
)


DIRECTION_POLICY_VERSION = "mwbl-effect-direction-v1"
DIRECTION_DICTIONARY_PATH = (
    Path(__file__).resolve().parents[1] / "effect_direction_dictionary.csv"
)
DIRECTION_FIELDS = (
    "cue_id",
    "term",
    "cue_type",
    "priority",
    "required_context",
    "forbidden_context",
    "source_type",
    "source_reference",
    "review_status",
    "notes",
)
CUE_TYPES = {"increase", "decrease", "improvement", "worsening", "null", "uncertain"}
SOURCE_TYPES = {"internal_language_policy", "internal_statistical_policy"}
MAX_CUE_DISTANCE_TOKENS = 10
CLAUSE_SPLIT_RE = re.compile(r"\s*;\s*")
NEGATED_RESULT_RE = re.compile(
    r"\b(?:no|not|never|without|failed|lacked|absence of)"
    r"(?:\s+[a-z0-9]+){0,3}\s+"
    r"(?:effect|benefit|change|difference|improvement|reduction|increase|decrease|"
    r"improved|reduced|increased|decreased)\b"
)
NEGATION_TOKENS = {"no", "not", "never", "without", "failed", "lacked", "absence"}
NEGATION_SCOPE_BOUNDARIES = {"and", "but", "while", "whereas"}
COMPARISON_CONTEXT_FOLLOWERS = {
    "age",
    "arm",
    "concentration",
    "dose",
    "dosage",
    "eyelid",
    "face",
    "group",
    "groups",
    "leg",
    "temperature",
}
CONTEXT_SENSITIVE_COMPARISON_CUES = {"lower", "higher", "greater", "elevated"}


class DirectionDictionaryError(ValueError):
    """Raised when the direction cue dictionary violates its contract."""


@dataclass(frozen=True)
class DirectionCue:
    cue_id: str
    term: str
    cue_type: str
    priority: str
    required_context: str
    forbidden_context: str
    source_type: str
    source_reference: str
    review_status: str
    notes: str

    @property
    def priority_value(self) -> int:
        return int(self.priority)

    @property
    def required_context_terms(self) -> tuple[str, ...]:
        return _split_terms(self.required_context)

    @property
    def forbidden_context_terms(self) -> tuple[str, ...]:
        return _split_terms(self.forbidden_context)


@dataclass(frozen=True)
class DirectionCueMatch:
    cue: DirectionCue
    start: int
    end: int


@dataclass(frozen=True)
class OutcomeDirectionAssessment:
    effect_id: str
    outcome_concept_id: str
    outcome_term: str
    expected_direction: str
    observed_change: str
    direction: str
    cue: str
    cue_id: str
    token_distance: int | None
    conflict: bool
    reason: str


def _split_terms(value: str) -> tuple[str, ...]:
    return tuple(term.strip() for term in (value or "").split("|") if term.strip())


def _phrase_spans(normalized_text: str, value: str) -> tuple[tuple[int, int], ...]:
    normalized_value = normalize_phrase(value)
    if not normalized_value:
        return ()
    pattern = re.compile(rf"(?<!\S){re.escape(normalized_value)}(?!\S)")
    return tuple(match.span() for match in pattern.finditer(normalized_text))


def _contains_phrase(normalized_text: str, value: str) -> bool:
    return bool(_phrase_spans(normalized_text, value))


def _next_token(normalized_text: str, end: int) -> str:
    remainder = normalized_text[end:].strip()
    return remainder.split(maxsplit=1)[0] if remainder else ""


def _is_contextual_comparison(normalized_text: str, cue: DirectionCue, end: int) -> bool:
    return (
        normalize_phrase(cue.term) in CONTEXT_SENSITIVE_COMPARISON_CUES
        and _next_token(normalized_text, end) in COMPARISON_CONTEXT_FOLLOWERS
    )


def load_effect_direction_dictionary(
    path: Path = DIRECTION_DICTIONARY_PATH,
) -> tuple[DirectionCue, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != DIRECTION_FIELDS:
            raise DirectionDictionaryError(
                f"Unexpected columns in {path}: {reader.fieldnames}; expected {DIRECTION_FIELDS}"
            )
        cues = tuple(
            DirectionCue(
                **{
                    field: (row.get(field) or "").strip()
                    for field in DIRECTION_FIELDS
                }
            )
            for row in reader
        )
    validate_effect_direction_dictionary(cues)
    return cues


def validate_effect_direction_dictionary(cues: Sequence[DirectionCue]) -> None:
    if not cues:
        raise DirectionDictionaryError("The effect direction dictionary is empty")

    errors: list[str] = []
    cue_ids: set[str] = set()
    normalized_terms: set[str] = set()
    for line_number, cue in enumerate(cues, start=2):
        prefix = f"line {line_number}"
        normalized_term = normalize_phrase(cue.term)
        if not cue.cue_id or cue.cue_id in cue_ids:
            errors.append(f"{prefix}: cue_id must be unique")
        cue_ids.add(cue.cue_id)
        if not normalized_term or normalized_term in normalized_terms:
            errors.append(f"{prefix}: normalized term must be nonempty and unique")
        normalized_terms.add(normalized_term)
        if cue.cue_type not in CUE_TYPES:
            errors.append(f"{prefix}: invalid cue_type {cue.cue_type!r}")
        try:
            priority = cue.priority_value
        except ValueError:
            errors.append(f"{prefix}: priority must be an integer")
        else:
            if not 1 <= priority <= 100:
                errors.append(f"{prefix}: priority must be between 1 and 100")
        if cue.source_type not in SOURCE_TYPES:
            errors.append(f"{prefix}: invalid source_type {cue.source_type!r}")
        if cue.source_reference != "POLICY:effect-direction-v1":
            errors.append(f"{prefix}: direction cues must cite the v1 internal policy")
        if cue.review_status != "approved":
            errors.append(f"{prefix}: only approved direction cues belong in the dictionary")
    if errors:
        raise DirectionDictionaryError("\n".join(errors))


def match_direction_cues(
    text: str,
    cues: Sequence[DirectionCue] | None = None,
) -> list[DirectionCueMatch]:
    cues = tuple(cues) if cues is not None else EFFECT_DIRECTION_CUES
    normalized_text = normalize_phrase(text)
    candidates: list[DirectionCueMatch] = []
    for cue in cues:
        if cue.required_context_terms and not any(
            _contains_phrase(normalized_text, term) for term in cue.required_context_terms
        ):
            continue
        if any(_contains_phrase(normalized_text, term) for term in cue.forbidden_context_terms):
            continue
        for start, end in _phrase_spans(normalized_text, cue.term):
            if _is_contextual_comparison(normalized_text, cue, end):
                continue
            candidates.append(DirectionCueMatch(cue=cue, start=start, end=end))

    candidates.sort(
        key=lambda match: (
            -(match.end - match.start),
            -match.cue.priority_value,
            match.start,
            match.cue.cue_id,
        )
    )
    selected: list[DirectionCueMatch] = []
    for candidate in candidates:
        if any(
            candidate.start < current.end and current.start < candidate.end
            for current in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda match: (match.start, match.end, match.cue.cue_id))


def _token_distance(
    normalized_text: str,
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> int:
    if left_end <= right_start:
        between = normalized_text[left_end:right_start]
    elif right_end <= left_start:
        between = normalized_text[right_end:left_start]
    else:
        return 0
    return len(between.split())


def _direction_from_cue(expected_direction: str, cue_type: str) -> tuple[str, str]:
    if cue_type == "null":
        return "null", "explicit_null_result"
    if cue_type == "uncertain":
        return "unclear", "hedged_or_insufficient_result"
    if expected_direction == "parameter_specific":
        return "unclear", "parameter_specific_manual_review"
    if cue_type == "improvement":
        return "positive", "explicit_beneficial_interpretation"
    if cue_type == "worsening":
        return "negative", "explicit_harmful_interpretation"
    if cue_type in {"increase", "decrease"}:
        if cue_type == expected_direction:
            return "positive", f"expected_{expected_direction}_observed_{cue_type}"
        return "negative", f"expected_{expected_direction}_observed_{cue_type}"
    return "unclear", "unsupported_direction_cue"


def _cue_score(match: DirectionCueMatch, distance: int) -> int:
    return match.cue.priority_value - (distance * 10)


def _tokens_with_spans(normalized_text: str) -> list[tuple[str, int, int]]:
    return [(match.group(), match.start(), match.end()) for match in re.finditer(r"\S+", normalized_text)]


def _is_negated_cue(normalized_text: str, cue_match: DirectionCueMatch) -> bool:
    tokens = _tokens_with_spans(normalized_text)
    cue_index = next(
        (index for index, (_, start, end) in enumerate(tokens) if start <= cue_match.start < end),
        None,
    )
    if cue_index is None:
        return False
    lower_bound = max(0, cue_index - 4)
    window = tokens[lower_bound:cue_index]
    for offset in range(len(window) - 1, -1, -1):
        token = window[offset][0]
        if token in NEGATION_SCOPE_BOUNDARIES:
            break
        if token not in NEGATION_TOKENS:
            continue
        following = window[offset + 1][0] if offset + 1 < len(window) else ""
        if token == "not" and following == "only":
            continue
        return True
    return False


def _negated_result_near_outcome(
    normalized_text: str,
    outcome: OutcomeMatch,
) -> bool:
    for match in NEGATED_RESULT_RE.finditer(normalized_text):
        if match.group().startswith("not only"):
            continue
        distance = _token_distance(
            normalized_text,
            outcome.start,
            outcome.end,
            match.start(),
            match.end(),
        )
        if distance <= MAX_CUE_DISTANCE_TOKENS:
            return True
    return False


def _has_statistical_support(text: str) -> bool:
    normalized_text = normalize_phrase(text)
    for match in re.finditer(r"\bsignificant(?:ly)?\b", normalized_text):
        prefix = normalized_text[max(0, match.start() - 20) : match.start()].split()
        if any(token in {"no", "not", "non"} for token in prefix[-2:]):
            continue
        return True
    for match in re.finditer(r"\bp\s*(<=|<|=)\s*(0?\.\d+)\b", text, re.IGNORECASE):
        operator, raw_value = match.groups()
        value = float(raw_value)
        if operator in {"<", "<="} and value <= 0.05:
            return True
        if operator == "=" and value < 0.05:
            return True
    return bool(
        re.search(
            r"\b(?:95\s*%\s*(?:ci|confidence interval)|confidence interval|effect size)\b",
            text,
            re.IGNORECASE,
        )
    )


def has_statistical_support(text: str) -> bool:
    """Return whether a result span contains non-negated statistical support."""

    return _has_statistical_support(text)


def _assess_match(
    raw_text: str,
    normalized_text: str,
    outcome: OutcomeMatch,
    cue_matches: Sequence[DirectionCueMatch],
) -> OutcomeDirectionAssessment:
    nearby: list[tuple[int, int, DirectionCueMatch]] = []
    for cue_match in cue_matches:
        distance = _token_distance(
            normalized_text,
            outcome.start,
            outcome.end,
            cue_match.start,
            cue_match.end,
        )
        if distance <= MAX_CUE_DISTANCE_TOKENS:
            nearby.append((_cue_score(cue_match, distance), distance, cue_match))

    entry = outcome.entry
    if _negated_result_near_outcome(normalized_text, outcome):
        return OutcomeDirectionAssessment(
            effect_id=entry.effect_id,
            outcome_concept_id=entry.outcome_concept_id,
            outcome_term=entry.term,
            expected_direction=entry.positive_direction,
            observed_change="null",
            direction="null",
            cue="negated result",
            cue_id="rule_negated_result",
            token_distance=0,
            conflict=False,
            reason="negated_result_scope",
        )
    if not nearby:
        return OutcomeDirectionAssessment(
            effect_id=entry.effect_id,
            outcome_concept_id=entry.outcome_concept_id,
            outcome_term=entry.term,
            expected_direction=entry.positive_direction,
            observed_change="unresolved",
            direction="unclear",
            cue="",
            cue_id="",
            token_distance=None,
            conflict=False,
            reason="no_linked_direction_cue",
        )

    explicit_null = [item for item in nearby if item[2].cue.cue_type == "null"]
    concrete = [
        item
        for item in nearby
        if item[2].cue.cue_type in {"increase", "decrease", "improvement", "worsening"}
    ]
    uncertain = [item for item in nearby if item[2].cue.cue_type == "uncertain"]
    if explicit_null:
        nearby = explicit_null
    elif uncertain and concrete and _has_statistical_support(raw_text):
        nearby = concrete
    elif uncertain:
        nearby = uncertain

    nearby.sort(
        key=lambda item: (
            -item[0],
            item[1],
            -(item[2].end - item[2].start),
            item[2].cue.cue_id,
        )
    )
    best_score, best_distance, best_match = nearby[0]
    if best_match.cue.cue_type not in {"null", "uncertain"} and _is_negated_cue(
        normalized_text, best_match
    ):
        return OutcomeDirectionAssessment(
            effect_id=entry.effect_id,
            outcome_concept_id=entry.outcome_concept_id,
            outcome_term=entry.term,
            expected_direction=entry.positive_direction,
            observed_change="null",
            direction="null",
            cue=best_match.cue.term,
            cue_id=best_match.cue.cue_id,
            token_distance=best_distance,
            conflict=False,
            reason="negated_direction_cue",
        )
    directional_types = {
        match.cue.cue_type
        for score, _, match in nearby
        if score >= best_score - 10
        and match.cue.cue_type in {"increase", "decrease", "improvement", "worsening"}
    }
    conflict = bool(
        ({"increase", "decrease"} <= directional_types)
        or ({"improvement", "worsening"} <= directional_types)
    )
    if conflict and best_match.cue.cue_type not in {"null", "uncertain"}:
        direction, reason = "unclear", "conflicting_nearby_direction_cues"
    else:
        direction, reason = _direction_from_cue(
            entry.positive_direction,
            best_match.cue.cue_type,
        )
    return OutcomeDirectionAssessment(
        effect_id=entry.effect_id,
        outcome_concept_id=entry.outcome_concept_id,
        outcome_term=entry.term,
        expected_direction=entry.positive_direction,
        observed_change=best_match.cue.cue_type,
        direction=direction,
        cue=best_match.cue.term,
        cue_id=best_match.cue.cue_id,
        token_distance=best_distance,
        conflict=conflict,
        reason=reason,
    )


def assess_outcome_directions(
    text: str,
    *,
    outcomes: Sequence[OutcomeMatch] | None = None,
    cues: Sequence[DirectionCue] | None = None,
) -> list[OutcomeDirectionAssessment]:
    if outcomes is None and ";" in text:
        output: list[OutcomeDirectionAssessment] = []
        for clause in CLAUSE_SPLIT_RE.split(text):
            if clause.strip():
                output.extend(assess_outcome_directions(clause, cues=cues))
        return output
    normalized_text = normalize_phrase(text)
    outcome_matches = list(outcomes) if outcomes is not None else match_outcome_matches(text)
    cue_matches = match_direction_cues(text, cues)
    return [
        _assess_match(text, normalized_text, outcome, cue_matches)
        for outcome in outcome_matches
    ]


def assess_generic_direction(
    text: str,
    cues: Sequence[DirectionCue] | None = None,
) -> str:
    matches = match_direction_cues(text, cues)
    if not matches:
        return "unclear"
    best = max(
        matches,
        key=lambda match: (
            match.cue.priority_value,
            match.end - match.start,
            -match.start,
        ),
    )
    return {
        "null": "null",
        "uncertain": "unclear",
        "improvement": "positive",
        "worsening": "negative",
        "increase": "unclear",
        "decrease": "unclear",
    }[best.cue.cue_type]


def summarize_direction_assessments(
    assessments: Sequence[OutcomeDirectionAssessment],
    *,
    fallback_text: str = "",
) -> tuple[str, bool, str]:
    if not assessments:
        return assess_generic_direction(fallback_text), False, "{}"

    grouped: dict[str, list[OutcomeDirectionAssessment]] = defaultdict(list)
    for assessment in assessments:
        grouped[assessment.effect_id].append(assessment)

    output: dict[str, object] = {}
    overall_directions: set[str] = set()
    conflict = False
    for effect_id in EFFECT_IDS:
        values = grouped.get(effect_id)
        if not values:
            continue
        directions = {value.direction for value in values}
        effect_conflict = any(value.conflict for value in values) or len(directions) > 1
        effect_direction = next(iter(directions)) if len(directions) == 1 else "unclear"
        overall_directions.add(effect_direction)
        conflict = conflict or effect_conflict
        output[effect_id] = {
            "direction": effect_direction,
            "conflict": effect_conflict,
            "outcomes": [asdict(value) for value in values],
        }

    overall = next(iter(overall_directions)) if len(overall_directions) == 1 else "unclear"
    return (
        overall,
        conflict or len(overall_directions) > 1,
        json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    )


def build_validation_report(
    path: Path = DIRECTION_DICTIONARY_PATH,
    cues: Sequence[DirectionCue] | None = None,
) -> dict[str, object]:
    cues = tuple(cues) if cues is not None else load_effect_direction_dictionary(path)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        display_path = path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        display_path = str(path)
    return {
        "dictionary_path": display_path,
        "dictionary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "policy_version": DIRECTION_POLICY_VERSION,
        "entry_count": len(cues),
        "entries_by_cue_type": dict(sorted(Counter(cue.cue_type for cue in cues).items())),
        "max_cue_distance_tokens": MAX_CUE_DISTANCE_TOKENS,
        "runtime_scoring_changed": False,
        "validation_status": "passed",
    }


def write_validation_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


EFFECT_DIRECTION_CUES = load_effect_direction_dictionary()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", type=Path, default=DIRECTION_DICTIONARY_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    cues = load_effect_direction_dictionary(args.dictionary)
    report = build_validation_report(args.dictionary, cues)
    if args.output:
        write_validation_report(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
