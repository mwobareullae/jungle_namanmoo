#!/usr/bin/env python3
"""Load and validate the reviewed six-axis outcome vocabulary.

The dictionary separates broad discovery vocabulary from terms that are safe
enough to map a measured paper outcome to one of the six existing effects.
Instrument, method, context, and mechanism names remain discoverable but never
map an effect by themselves.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "effect_outcome_dictionary.csv"
EFFECT_IDS = (
    "effect_brightening",
    "effect_acne_sebum",
    "effect_wrinkle",
    "effect_moisture_barrier",
    "effect_calming",
    "effect_exfoliation",
)
DICTIONARY_FIELDS = (
    "effect_id",
    "outcome_concept_id",
    "term",
    "term_type",
    "positive_direction",
    "required_context",
    "forbidden_context",
    "discovery_use",
    "mapping_use",
    "source_type",
    "source_reference",
    "review_status",
    "notes",
)
TERM_TYPES = {
    "outcome",
    "metric",
    "scale",
    "abbreviation",
    "instrument",
    "method",
    "context",
    "mechanism",
}
SOURCE_TYPES = {
    "guideline",
    "measurement_guidance",
    "validation_study",
    "internal_mapping_policy",
    "internal_guardrail",
}
POSITIVE_DIRECTIONS = {"increase", "decrease", "parameter_specific", "not_applicable"}
REVIEW_STATUSES = {"approved", "context_only", "mechanism_only", "ambiguous_review"}
MAPPABLE_TERM_TYPES = {"outcome", "metric", "scale", "abbreviation"}
YES_NO = {"Y", "N"}

# These broad words are useful for discovery, but they are not a measured
# cosmetic outcome without a more specific metric or scale.
BANNED_STANDALONE_MAPPING_TERMS = {
    "acne",
    "collagen",
    "comedone",
    "dermatitis",
    "erythema",
    "inflammation",
    "keratinization",
    "melanin",
    "melanogenesis",
    "redness",
    "sebum",
    "skin barrier",
    "skin roughness",
    "stratum corneum",
    "tyrosinase",
}


class OutcomeDictionaryError(ValueError):
    """Raised when the reviewed outcome dictionary violates its contract."""


@dataclass(frozen=True)
class OutcomeTerm:
    effect_id: str
    outcome_concept_id: str
    term: str
    term_type: str
    positive_direction: str
    required_context: str
    forbidden_context: str
    discovery_use: str
    mapping_use: str
    source_type: str
    source_reference: str
    review_status: str
    notes: str

    @property
    def required_context_terms(self) -> tuple[str, ...]:
        return _split_terms(self.required_context)

    @property
    def forbidden_context_terms(self) -> tuple[str, ...]:
        return _split_terms(self.forbidden_context)


@dataclass(frozen=True)
class OutcomeMatch:
    entry: OutcomeTerm
    start: int
    end: int


def normalize_phrase(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _split_terms(value: str) -> tuple[str, ...]:
    return tuple(term.strip() for term in (value or "").split("|") if term.strip())


def _contains_phrase(normalized_text: str, value: str) -> bool:
    return bool(_phrase_spans(normalized_text, value))


def _phrase_spans(normalized_text: str, value: str) -> tuple[tuple[int, int], ...]:
    normalized_value = normalize_phrase(value)
    if not normalized_value:
        return ()
    pattern = re.compile(rf"(?<!\S){re.escape(normalized_value)}(?!\S)")
    return tuple(match.span() for match in pattern.finditer(normalized_text))


def _entry_matches(text: str, entry: OutcomeTerm) -> bool:
    normalized_text = normalize_phrase(text)
    if not _contains_phrase(normalized_text, entry.term):
        return False
    if entry.required_context_terms and not any(
        _contains_phrase(normalized_text, term) for term in entry.required_context_terms
    ):
        return False
    if any(_contains_phrase(normalized_text, term) for term in entry.forbidden_context_terms):
        return False
    return True


def load_effect_outcome_dictionary(path: Path = DICTIONARY_PATH) -> tuple[OutcomeTerm, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != DICTIONARY_FIELDS:
            raise OutcomeDictionaryError(
                f"Unexpected columns in {path}: {reader.fieldnames}; expected {DICTIONARY_FIELDS}"
            )
        entries = tuple(
            OutcomeTerm(
                **{
                    field: (row.get(field) or "").strip()
                    for field in DICTIONARY_FIELDS
                }
            )
            for row in reader
        )
    validate_effect_outcome_dictionary(entries)
    return entries


def validate_effect_outcome_dictionary(entries: Sequence[OutcomeTerm]) -> None:
    if not entries:
        raise OutcomeDictionaryError("The effect outcome dictionary is empty")

    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    effects_seen: set[str] = set()
    for line_number, entry in enumerate(entries, start=2):
        prefix = f"line {line_number}"
        effects_seen.add(entry.effect_id)
        if entry.effect_id not in EFFECT_IDS:
            errors.append(f"{prefix}: unknown effect_id {entry.effect_id!r}")
        if not entry.outcome_concept_id or not entry.term:
            errors.append(f"{prefix}: outcome_concept_id and term are required")
        if entry.term_type not in TERM_TYPES:
            errors.append(f"{prefix}: invalid term_type {entry.term_type!r}")
        if entry.positive_direction not in POSITIVE_DIRECTIONS:
            errors.append(f"{prefix}: invalid positive_direction {entry.positive_direction!r}")
        if entry.discovery_use not in YES_NO or entry.mapping_use not in YES_NO:
            errors.append(f"{prefix}: discovery_use and mapping_use must be Y or N")
        if entry.review_status not in REVIEW_STATUSES:
            errors.append(f"{prefix}: invalid review_status {entry.review_status!r}")
        if entry.source_type not in SOURCE_TYPES:
            errors.append(f"{prefix}: invalid source_type {entry.source_type!r}")
        if not entry.source_reference:
            errors.append(f"{prefix}: source_reference is required")

        key = (entry.effect_id, entry.outcome_concept_id, normalize_phrase(entry.term))
        if key in seen:
            errors.append(f"{prefix}: duplicate effect/concept/term {key}")
        seen.add(key)

        if entry.mapping_use == "Y":
            if entry.review_status != "approved":
                errors.append(f"{prefix}: mapping_use=Y requires review_status=approved")
            if entry.term_type not in MAPPABLE_TERM_TYPES:
                errors.append(f"{prefix}: {entry.term_type} terms cannot map an effect alone")
            if entry.positive_direction == "not_applicable":
                errors.append(f"{prefix}: mapped outcomes require a benefit direction policy")
            if normalize_phrase(entry.term) in BANNED_STANDALONE_MAPPING_TERMS:
                errors.append(f"{prefix}: broad term {entry.term!r} cannot map alone")
        elif entry.review_status == "approved":
            errors.append(f"{prefix}: review_status=approved requires mapping_use=Y")

        if entry.mapping_use == "N" and (
            entry.source_type != "internal_guardrail"
            or entry.source_reference != "POLICY:effect-outcome-v1"
        ):
            errors.append(
                f"{prefix}: blocked terms must cite the internal guardrail policy"
            )

    missing_effects = set(EFFECT_IDS) - effects_seen
    if missing_effects:
        errors.append(f"missing effects: {sorted(missing_effects)}")
    if errors:
        raise OutcomeDictionaryError("\n".join(errors))


def terms_by_effect(
    entries: Sequence[OutcomeTerm],
    *,
    use: str,
) -> dict[str, tuple[str, ...]]:
    if use not in {"discovery", "mapping"}:
        raise ValueError("use must be 'discovery' or 'mapping'")
    flag_name = f"{use}_use"
    output: dict[str, list[str]] = {effect_id: [] for effect_id in EFFECT_IDS}
    seen: dict[str, set[str]] = {effect_id: set() for effect_id in EFFECT_IDS}
    for entry in entries:
        if getattr(entry, flag_name) != "Y":
            continue
        normalized = normalize_phrase(entry.term)
        if normalized in seen[entry.effect_id]:
            continue
        seen[entry.effect_id].add(normalized)
        output[entry.effect_id].append(entry.term)
    return {effect_id: tuple(terms) for effect_id, terms in output.items()}


def match_outcome_matches(
    text: str,
    entries: Sequence[OutcomeTerm] | None = None,
) -> list[OutcomeMatch]:
    entries = tuple(entries) if entries is not None else EFFECT_OUTCOME_ENTRIES
    normalized_text = normalize_phrase(text)
    candidates: list[tuple[int, int, OutcomeTerm]] = []
    for entry in entries:
        if entry.mapping_use != "Y" or entry.review_status != "approved":
            continue
        if not _entry_matches(text, entry):
            continue
        for start, end in _phrase_spans(normalized_text, entry.term):
            candidates.append((start, end, entry))

    # Prefer the longest expression when approved terms overlap. A shorter
    # blocked/context term never vetoes a longer approved outcome.
    candidates.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2].effect_id))
    selected: list[tuple[int, int, OutcomeTerm]] = []
    for start, end, entry in candidates:
        if any(start < selected_end and selected_start < end for selected_start, selected_end, _ in selected):
            continue
        selected.append((start, end, entry))
    selected.sort(key=lambda item: (item[0], item[1], item[2].effect_id))
    return [OutcomeMatch(entry=entry, start=start, end=end) for start, end, entry in selected]


def match_outcome_terms(
    text: str,
    entries: Sequence[OutcomeTerm] | None = None,
) -> list[OutcomeTerm]:
    return [match.entry for match in match_outcome_matches(text, entries)]


def match_effect_ids(
    text: str,
    entries: Sequence[OutcomeTerm] | None = None,
) -> list[str]:
    matched = {entry.effect_id for entry in match_outcome_terms(text, entries)}
    return [effect_id for effect_id in EFFECT_IDS if effect_id in matched]


def build_validation_report(
    path: Path = DICTIONARY_PATH,
    entries: Sequence[OutcomeTerm] | None = None,
) -> dict[str, object]:
    entries = tuple(entries) if entries is not None else load_effect_outcome_dictionary(path)
    raw_bytes = path.read_bytes()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        display_path = path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        display_path = str(path)
    return {
        "dictionary_path": display_path,
        "dictionary_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "entry_count": len(entries),
        "effect_count": len({entry.effect_id for entry in entries}),
        "entries_by_effect": dict(sorted(Counter(entry.effect_id for entry in entries).items())),
        "entries_by_review_status": dict(
            sorted(Counter(entry.review_status for entry in entries).items())
        ),
        "entries_by_source_type": dict(
            sorted(Counter(entry.source_type for entry in entries).items())
        ),
        "unique_source_reference_count": len(
            {entry.source_reference for entry in entries}
        ),
        "pubmed_source_reference_count": len(
            {
                entry.source_reference
                for entry in entries
                if entry.source_reference.startswith("PMID:")
            }
        ),
        "approved_mapping_entry_count": sum(entry.mapping_use == "Y" for entry in entries),
        "discovery_entry_count": sum(entry.discovery_use == "Y" for entry in entries),
        "standalone_blocked_entry_count": sum(
            entry.discovery_use == "Y" and entry.mapping_use == "N" for entry in entries
        ),
        "runtime_scoring_changed": False,
        "validation_status": "passed",
    }


def write_validation_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


EFFECT_OUTCOME_ENTRIES = load_effect_outcome_dictionary()
APPROVED_DISCOVERY_TERMS = terms_by_effect(EFFECT_OUTCOME_ENTRIES, use="discovery")
APPROVED_MAPPING_TERMS = terms_by_effect(EFFECT_OUTCOME_ENTRIES, use="mapping")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", type=Path, default=DICTIONARY_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    entries = load_effect_outcome_dictionary(args.dictionary)
    report = build_validation_report(args.dictionary, entries)
    if args.output:
        write_validation_report(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
