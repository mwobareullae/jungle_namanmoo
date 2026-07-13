#!/usr/bin/env python3
"""Evaluate the 482-ingredient multi-source evidence funnel.

Each paper must pass every filter sequentially. Evidence from different papers
is never combined to manufacture a passing ingredient. Outputs are review-only
and never modify runtime evidence or recommendation scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from assess_ingredient_score_eligibility import (
    STRONG_RESULT_RE,
    UNCERTAIN_EFFECT_RE,
)
from build_ingredient_first_paper_catalog import (
    _term_form_is_limited,
    extract_outcomes,
)
from discover_new_evidence import PaperMetadata, load_ingredient_terms, normalize_doi
from effect_direction_dictionary import DIRECTION_DICTIONARY_PATH
from effect_outcome_dictionary import DICTIONARY_PATH
from screen_effect_review_candidates import PaperAssessment, assess_paper_candidate, normalize_phrase


POLICY_VERSION = "mwbl-multisource-score-funnel-v1"
SOURCE_PRIORITY = {"pubmed": 3, "europe_pmc": 2, "openalex": 1, "crossref": 0}

FILTERS = (
    ("exact_single_ingredient", "정확한 단일성분"),
    ("human_skin_topical", "인체 피부 도포 연구"),
    ("not_combination_product", "복합제품이 아님"),
    ("direct_existing_effect", "기존 6효능 중 하나를 직접 측정"),
    ("positive_result", "긍정적인 결과"),
    ("certain_result", "불확실 표현이 아님"),
    ("standalone_evidence_tier", "동물·세포·일반 리뷰 단독 점수 금지"),
)

HUMAN_RE = re.compile(
    r"\b(humans?|patients?|volunteers?|participants?|subjects?|clinical|"
    r"randomi[sz]ed|double[- ]blind|split[- ]face|placebo[- ]controlled)\b",
    re.IGNORECASE,
)
TOPICAL_SKIN_RE = re.compile(
    r"\b(topical(?:ly)?|cream|gel|lotion|serum|ointment|applied|application|"
    r"cutaneous|dermal|skin|face|facial)\b",
    re.IGNORECASE,
)
NON_STANDALONE_PUBLICATION_RE = re.compile(
    r"\b(preprint|review|editorial|letter|commentary|book[- ]chapter)\b",
    re.IGNORECASE,
)
SYSTEMATIC_PUBLICATION_RE = re.compile(
    r"\b(systematic review|meta[- ]analysis)\b",
    re.IGNORECASE,
)

PAPER_FIELDS = [
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "sources",
    "paper_key",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "abstract_available",
    "evidence_tier",
    "evidence_kind",
    "relation_scope",
    "applicability",
    "mapped_effect_ids",
    "directions",
    "evidence_spans",
    "passed_stage_count",
    "first_failed_filter",
    "review_status",
    "runtime_score_change",
]

INGREDIENT_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "source_count",
    "sources",
    "deduplicated_paper_count",
    "max_passed_stage_count",
    "first_failed_filter",
    "first_failed_filter_ko",
    "final_score_candidate",
    "candidate_effect_ids",
    "candidate_paper_keys",
    "review_status",
    "runtime_score_change",
]

FUNNEL_FIELDS = [
    "stage_order",
    "filter_id",
    "filter_name_ko",
    "input_ingredient_count",
    "filtered_ingredient_count",
    "remaining_ingredient_count",
    "note",
]


@dataclass(frozen=True)
class CandidatePaper:
    ingredient_id: str
    sources: tuple[str, ...]
    metadata: PaperMetadata


@dataclass(frozen=True)
class EvaluatedPaper:
    candidate: CandidatePaper
    assessment: PaperAssessment
    outcomes: tuple[Mapping[str, str], ...]
    passed_stage_count: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_title(value: str) -> str:
    return normalize_phrase(value)


def paper_identifiers(metadata: PaperMetadata) -> tuple[str, ...]:
    identifiers = []
    if metadata.pmid:
        identifiers.append(f"pmid:{metadata.pmid}")
    if metadata.doi:
        identifiers.append(f"doi:{normalize_doi(metadata.doi)}")
    title = normalize_title(metadata.title)
    if title:
        identifiers.append(f"title:{title}")
    return tuple(identifiers)


def paper_key(metadata: PaperMetadata) -> str:
    if metadata.pmid:
        return f"PMID:{metadata.pmid}"
    if metadata.doi:
        return f"DOI:{normalize_doi(metadata.doi)}"
    return f"TITLE:{normalize_title(metadata.title)}"


def _metadata_richness(metadata: PaperMetadata, sources: Sequence[str]) -> tuple[int, int, int]:
    return (
        int(bool(metadata.abstract)),
        len(metadata.abstract),
        max((SOURCE_PRIORITY.get(source, -1) for source in sources), default=-1),
    )


def merge_candidate_papers(rows: Sequence[CandidatePaper]) -> list[CandidatePaper]:
    groups: list[CandidatePaper] = []
    identifier_to_group: dict[str, int] = {}
    for row in rows:
        identifiers = paper_identifiers(row.metadata)
        matches = {identifier_to_group[value] for value in identifiers if value in identifier_to_group}
        if matches:
            index = min(matches)
            existing = groups[index]
            sources = tuple(sorted(set(existing.sources) | set(row.sources)))
            best = max(
                (existing, row),
                key=lambda candidate: _metadata_richness(candidate.metadata, candidate.sources),
            )
            metadata = replace(
                best.metadata,
                pmid=existing.metadata.pmid or row.metadata.pmid,
                doi=existing.metadata.doi or row.metadata.doi,
            )
            groups[index] = CandidatePaper(row.ingredient_id, sources, metadata)
            for value in paper_identifiers(metadata):
                identifier_to_group[value] = index
        else:
            index = len(groups)
            groups.append(row)
            for value in identifiers:
                identifier_to_group[value] = index
    return groups


def pubmed_candidate(row: Mapping[str, str]) -> CandidatePaper:
    return CandidatePaper(
        ingredient_id=row["ingredient_id"],
        sources=("pubmed",),
        metadata=PaperMetadata(
            pmid=row.get("pmid", ""),
            doi=normalize_doi(row.get("doi", "")),
            title=row.get("title", ""),
            journal=row.get("journal", ""),
            publication_date=row.get("publication_date", ""),
            publication_types=tuple(
                value for value in row.get("publication_types", "").split("; ") if value
            ),
            authors=tuple(value for value in row.get("authors", "").split("; ") if value),
            abstract=row.get("abstract", ""),
        ),
    )


def external_candidate(row: Mapping[str, str]) -> CandidatePaper:
    return CandidatePaper(
        ingredient_id=row["ingredient_id"],
        sources=(row["source"],),
        metadata=PaperMetadata(
            pmid=row.get("pmid", ""),
            doi=normalize_doi(row.get("doi", "")),
            title=row.get("title", ""),
            journal=row.get("journal", ""),
            publication_date=row.get("publication_date", ""),
            publication_types=tuple(
                value for value in row.get("publication_types", "").split("; ") if value
            ),
            authors=tuple(value for value in row.get("authors", "").split("; ") if value),
            abstract=row.get("abstract", ""),
        ),
    )


def has_human_topical_context(
    metadata: PaperMetadata,
    assessment: PaperAssessment,
) -> bool:
    if assessment.applicability == "human_topical":
        return True
    text = f"{metadata.title} {metadata.abstract}"
    return bool(HUMAN_RE.search(text) and TOPICAL_SKIN_RE.search(text))


def is_certain_outcome(outcome: Mapping[str, str], metadata: PaperMetadata) -> bool:
    return not UNCERTAIN_EFFECT_RE.search(outcome.get("evidence_span", "")) or bool(
        STRONG_RESULT_RE.search(metadata.abstract)
    )


def evaluate_paper(
    candidate: CandidatePaper,
    ingredient_terms: Sequence[str],
) -> EvaluatedPaper:
    metadata = candidate.metadata
    assessment = assess_paper_candidate(metadata, ingredient_terms)
    outcomes = tuple(extract_outcomes(metadata, assessment, ingredient_terms))
    stages: list[bool] = []

    exact = (
        assessment.relation_scope != "unconfirmed"
        and not _term_form_is_limited(metadata.title, ingredient_terms)
    )
    stages.append(exact)

    human_topical = exact and has_human_topical_context(metadata, assessment)
    stages.append(human_topical)

    non_combination = human_topical and assessment.applicability != "combination_or_formulation"
    stages.append(non_combination)

    direct_outcomes = tuple(
        row
        for row in outcomes
        if row["mapping_status"] == "mapped_existing_effect"
        and row["ingredient_outcome_relation"] in {"direct", "review_summary"}
    )
    direct_effect = non_combination and bool(direct_outcomes)
    stages.append(direct_effect)

    positive_outcomes = tuple(row for row in direct_outcomes if row["direction"] == "positive")
    positive = direct_effect and bool(positive_outcomes)
    stages.append(positive)

    certain_outcomes = tuple(
        row for row in positive_outcomes if is_certain_outcome(row, metadata)
    )
    certain = positive and bool(certain_outcomes)
    stages.append(certain)

    publication_label = " ".join(metadata.publication_types)
    non_standalone_publication = bool(
        NON_STANDALONE_PUBLICATION_RE.search(publication_label)
        and not SYSTEMATIC_PUBLICATION_RE.search(publication_label)
    )
    standalone = (
        certain
        and assessment.evidence_tier <= 4
        and assessment.applicability == "human_topical"
        and not non_standalone_publication
    )
    stages.append(standalone)

    passed = 0
    for stage in stages:
        if not stage:
            break
        passed += 1
    return EvaluatedPaper(candidate, assessment, outcomes, passed)


def first_failed_filter(passed_stage_count: int) -> tuple[str, str]:
    if passed_stage_count >= len(FILTERS):
        return "passed_all", "전체 통과"
    return FILTERS[passed_stage_count]


def evaluate_funnel(
    *,
    targets: Sequence[Mapping[str, str]],
    candidates: Sequence[CandidatePaper],
    ingredient_terms: Mapping[str, Sequence[str]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    target_by_id = {row["ingredient_id"]: row for row in targets}
    candidates_by_ingredient: dict[str, list[CandidatePaper]] = defaultdict(list)
    for candidate in candidates:
        if candidate.ingredient_id in target_by_id:
            candidates_by_ingredient[candidate.ingredient_id].append(candidate)

    evaluated_by_ingredient: dict[str, list[EvaluatedPaper]] = {}
    paper_rows: list[dict[str, object]] = []
    for target in targets:
        ingredient_id = target["ingredient_id"]
        deduped = merge_candidate_papers(candidates_by_ingredient.get(ingredient_id, []))
        evaluated = [
            evaluate_paper(candidate, ingredient_terms[ingredient_id])
            for candidate in deduped
            if candidate.metadata.title
        ]
        evaluated_by_ingredient[ingredient_id] = evaluated
        for item in evaluated:
            mapped_effects = sorted(
                {
                    effect_id
                    for outcome in item.outcomes
                    for effect_id in outcome["mapped_effect_ids"].split("|")
                    if effect_id
                }
            )
            spans = [outcome["evidence_span"] for outcome in item.outcomes if outcome["evidence_span"]]
            directions = sorted({outcome["direction"] for outcome in item.outcomes})
            failed_id, _ = first_failed_filter(item.passed_stage_count)
            paper_rows.append(
                {
                    "ingredient_id": ingredient_id,
                    "name_ko": target.get("name_ko", ""),
                    "name_en": target.get("name_en", ""),
                    "product_count": target.get("product_count", "0"),
                    "sources": "|".join(item.candidate.sources),
                    "paper_key": paper_key(item.candidate.metadata),
                    "pmid": item.candidate.metadata.pmid,
                    "doi": item.candidate.metadata.doi,
                    "title": item.candidate.metadata.title,
                    "journal": item.candidate.metadata.journal,
                    "publication_date": item.candidate.metadata.publication_date,
                    "publication_types": "; ".join(item.candidate.metadata.publication_types),
                    "abstract_available": "Y" if item.candidate.metadata.abstract else "N",
                    "evidence_tier": item.assessment.evidence_tier,
                    "evidence_kind": item.assessment.evidence_kind,
                    "relation_scope": item.assessment.relation_scope,
                    "applicability": item.assessment.applicability,
                    "mapped_effect_ids": "|".join(mapped_effects),
                    "directions": "|".join(directions),
                    "evidence_spans": " || ".join(spans),
                    "passed_stage_count": item.passed_stage_count,
                    "first_failed_filter": failed_id,
                    "review_status": "candidate_unverified",
                    "runtime_score_change": "none",
                }
            )

    ingredient_rows: list[dict[str, object]] = []
    max_stage_counts = Counter()
    for target in targets:
        ingredient_id = target["ingredient_id"]
        evaluated = evaluated_by_ingredient[ingredient_id]
        max_stage = max((item.passed_stage_count for item in evaluated), default=0)
        max_stage_counts[max_stage] += 1
        failed_id, failed_ko = first_failed_filter(max_stage)
        passing = [item for item in evaluated if item.passed_stage_count == len(FILTERS)]
        effects = sorted(
            {
                effect_id
                for item in passing
                for outcome in item.outcomes
                if outcome["mapping_status"] == "mapped_existing_effect"
                and outcome["direction"] == "positive"
                and is_certain_outcome(outcome, item.candidate.metadata)
                for effect_id in outcome["mapped_effect_ids"].split("|")
                if effect_id
            }
        )
        sources = sorted({source for item in evaluated for source in item.candidate.sources})
        ingredient_rows.append(
            {
                "ingredient_rank": target["ingredient_rank"],
                "ingredient_id": ingredient_id,
                "name_ko": target.get("name_ko", ""),
                "name_en": target.get("name_en", ""),
                "product_count": target.get("product_count", "0"),
                "source_count": len(sources),
                "sources": "|".join(sources),
                "deduplicated_paper_count": len(evaluated),
                "max_passed_stage_count": max_stage,
                "first_failed_filter": failed_id,
                "first_failed_filter_ko": failed_ko,
                "final_score_candidate": "Y" if passing else "N",
                "candidate_effect_ids": "|".join(effects),
                "candidate_paper_keys": "|".join(
                    sorted({paper_key(item.candidate.metadata) for item in passing})
                ),
                "review_status": "candidate_unverified",
                "runtime_score_change": "none",
            }
        )

    funnel_rows: list[dict[str, object]] = []
    previous = len(targets)
    for stage, (filter_id, filter_ko) in enumerate(FILTERS, start=1):
        remaining = sum(
            max((item.passed_stage_count for item in evaluated_by_ingredient[row["ingredient_id"]]), default=0)
            >= stage
            for row in targets
        )
        filtered = previous - remaining
        note = "Sequential first-failure count; the same paper must pass every prior stage."
        if filter_id == "human_skin_topical":
            note += " Animal/cell-only evidence is removed here."
        if filter_id == "standalone_evidence_tier":
            note += " General reviews and tiers 5-8 cannot stand alone."
        funnel_rows.append(
            {
                "stage_order": stage,
                "filter_id": filter_id,
                "filter_name_ko": filter_ko,
                "input_ingredient_count": previous,
                "filtered_ingredient_count": filtered,
                "remaining_ingredient_count": remaining,
                "note": note,
            }
        )
        previous = remaining

    source_ingredient_counts = Counter()
    for ingredient_id, evaluated in evaluated_by_ingredient.items():
        for source in {source for item in evaluated for source in item.candidate.sources}:
            source_ingredient_counts[source] += 1
    summary = {
        "generated_on": date.today().isoformat(),
        "policy_version": POLICY_VERSION,
        "input_ingredient_count": len(targets),
        "excluded_before_search_count": max(0, 500 - len(targets)),
        "source_ingredient_counts": dict(sorted(source_ingredient_counts.items())),
        "deduplicated_paper_count": len(paper_rows),
        "effect_outcome_dictionary_sha256": file_sha256(DICTIONARY_PATH),
        "effect_direction_dictionary_sha256": file_sha256(
            DIRECTION_DICTIONARY_PATH
        ),
        "final_score_candidate_count": sum(
            row["final_score_candidate"] == "Y" for row in ingredient_rows
        ),
        "filter_funnel": funnel_rows,
        "source_limitations": {
            "openalex": (
                f"Partial 50-ingredient result excluded from the complete {len(targets)}-ingredient "
                "analysis after free daily budget exhaustion."
            ),
            "kci": "Not queried: KCI_API_KEY is not configured.",
            "riss": "Not queried: RISS_API_KEY is not configured.",
        },
        "review_status": "candidate_unverified",
        "runtime_changed": False,
    }
    return ingredient_rows, paper_rows, funnel_rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_482.csv"),
    )
    parser.add_argument(
        "--pubmed",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_screening_all_500.csv"),
    )
    parser.add_argument(
        "--europe-pmc",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_europe_pmc_482.csv"),
    )
    parser.add_argument(
        "--crossref",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_crossref_482.csv"),
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--ingredient-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_score_eligibility_482.csv"),
    )
    parser.add_argument(
        "--paper-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_screening_482.csv"),
    )
    parser.add_argument(
        "--funnel-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_filter_funnel_482.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_multisource_summary_482.json"),
    )
    args = parser.parse_args()

    targets = read_csv(args.targets)
    target_ids = {row["ingredient_id"] for row in targets}
    terms = load_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        target_ids,
    )
    candidates = [
        pubmed_candidate(row)
        for row in read_csv(args.pubmed)
        if row["ingredient_id"] in target_ids
    ]
    for path in (args.europe_pmc, args.crossref):
        candidates.extend(
            external_candidate(row)
            for row in read_csv(path)
            if row["ingredient_id"] in target_ids
        )
    ingredient_rows, paper_rows, funnel_rows, summary = evaluate_funnel(
        targets=targets,
        candidates=candidates,
        ingredient_terms=terms,
    )
    write_csv(args.ingredient_output, INGREDIENT_FIELDS, ingredient_rows)
    write_csv(args.paper_output, PAPER_FIELDS, paper_rows)
    write_csv(args.funnel_output, FUNNEL_FIELDS, funnel_rows)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Multi-source funnel complete: "
        f"ingredients={len(ingredient_rows)} papers={len(paper_rows)} "
        f"score_candidates={summary['final_score_candidate_count']}"
    )


if __name__ == "__main__":
    main()
