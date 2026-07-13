#!/usr/bin/env python3
"""Collect and tier PubMed signals for canonical ingredient/effect pairs.

The search is intentionally broad. Exact ingredient mentions in titles and
abstracts are recorded separately, study design is classified from tier 1 to
8, and formulation or route limitations remain explicit. This script never
approves evidence or changes runtime scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from build_ingredient_role_inventory import (
    CosingRecord,
    EFFECT_NAMES,
    effect_signals,
    load_cosing_cache,
    load_current_effects,
    match_cosing_record,
)
from discover_new_evidence import (
    DEFAULT_REQUEST_DELAY_SECONDS,
    DEFAULT_TOOL_NAME,
    PaperMetadata,
    PubMedClient,
    build_pair_query,
    load_ingredient_terms,
)


SCREENING_VERSION = "mwbl-effect-review-screen-v2-tiered"
ALL_HISTORY_START = date(1900, 1, 1)
DEFAULT_RETMAX_PER_PAIR = 50

DIRECT_SIGNAL_FUNCTIONS: dict[str, set[str]] = {
    "effect_brightening": {"BLEACHING"},
    "effect_calming": {"SOOTHING"},
}

HUMAN_PUBLICATION_TYPES = {
    "clinical trial",
    "clinical trial, phase i",
    "clinical trial, phase ii",
    "clinical trial, phase iii",
    "clinical trial, phase iv",
    "controlled clinical trial",
    "randomized controlled trial",
}

HUMAN_TEXT_RE = re.compile(
    r"\b(patient|patients|participant|participants|subject|subjects|volunteer|volunteers|"
    r"women|men|adults|randomi[sz]ed|double-blind|split-face|clinical trial|consumer test)\b",
    re.IGNORECASE,
)
TOPICAL_TEXT_RE = re.compile(
    r"\b(topical(?:ly)?|cream|lotion|serum|ointment|emulsion|moisturi[sz]er|"
    r"split-face|forearm|facial|skin application|cutaneous application|"
    r"appl(?:y|ied)\s+(?:to\s+)?(?:the\s+)?(?:skin|face|facial|forearm))\b",
    re.IGNORECASE,
)
NON_TOPICAL_TITLE_RE = re.compile(
    r"\b(oral|supplement|supplementation|ingestion|dietary|injectable|injection|"
    r"mesotherapy|fillers?|microneedle)\b",
    re.IGNORECASE,
)
TOPICAL_ROUTE_TITLE_RE = re.compile(
    r"\b(topical|cream|lotion|ointment|emulsion|moisturi[sz]er|skin application)\b",
    re.IGNORECASE,
)
REVIEW_PUBLICATION_TYPES = {"review", "systematic review", "meta-analysis"}
SYSTEMATIC_PUBLICATION_TYPES = {"systematic review", "meta-analysis"}
RANDOMIZED_PUBLICATION_TYPES = {"randomized controlled trial"}
CONTROLLED_PUBLICATION_TYPES = {"controlled clinical trial"}
CLINICAL_PUBLICATION_TYPES = HUMAN_PUBLICATION_TYPES | {
    "comparative study",
    "observational study",
}
EX_VIVO_RE = re.compile(
    r"\b(ex vivo|skin explant|human skin equivalent|reconstructed human epidermis|"
    r"artificial skin|3d skin model)\b",
    re.IGNORECASE,
)
ANIMAL_RE = re.compile(
    r"\b(mouse|mice|rat|rats|rabbit|rabbits|guinea pig|porcine|dog|dogs|canine|"
    r"animal model|in vivo murine)\b",
    re.IGNORECASE,
)
IN_VITRO_RE = re.compile(
    r"\b(in vitro|cell culture|cell line|stem cells?|keratinocyte|fibroblast|melanocyte|"
    r"melanogenesis assay)\b",
    re.IGNORECASE,
)
COMBINATION_RE = re.compile(
    r"\b(combination|combined with|multi[- ]ingredient|containing|formulated with|"
    r"blend of|complex of|loaded|enriched|adjuvant|3[- ]in[- ]1|multi[- ]modal)\b",
    re.IGNORECASE,
)
TIER_BASE_SIGNAL = {1: 100, 2: 90, 3: 78, 4: 60, 5: 40, 6: 25, 7: 20, 8: 10}

SCREENING_FIELDS = [
    "ingredient_id",
    "name_en",
    "effect_id",
    "effect_name",
    "signal_strength",
    "signal_functions",
    "selection_policy",
    "search_query",
    "raw_pubmed_pmids",
    "human_topical_pmids",
    "human_topical_titles_json",
    "best_evidence_tier",
    "best_evidence_kind",
    "best_relation_scope",
    "best_applicability",
    "best_pmid",
    "best_title",
    "best_signal_score",
    "tier_counts_json",
    "candidate_papers_json",
    "screening_status",
    "selected_for_paper_review",
    "review_status",
    "score_change",
    "screened_on",
    "screening_version",
]


class ScreeningClient(Protocol):
    request_count: int
    retry_count: int

    def search(
        self,
        query: str,
        *,
        window_start: date,
        window_end: date,
        retmax: int,
    ) -> list[str]: ...

    def fetch(self, pmids: Sequence[str]) -> dict[str, PaperMetadata]: ...


@dataclass(frozen=True)
class PairCandidate:
    ingredient_id: str
    name_en: str
    effect_id: str
    signal_strength: str
    signal_functions: tuple[str, ...]
    selection_policy: str


@dataclass(frozen=True)
class PaperAssessment:
    paper: PaperMetadata
    evidence_tier: int
    evidence_kind: str
    relation_scope: str
    applicability: str
    signal_score: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_phrase(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def title_mentions_ingredient(title: str, ingredient_terms: Sequence[str]) -> bool:
    normalized_title = f" {normalize_phrase(title)} "
    for term in ingredient_terms:
        normalized_term = normalize_phrase(term)
        if len(normalized_term) < 4:
            continue
        if f" {normalized_term} " in normalized_title:
            return True
    return False


def ingredient_mention_scope(
    paper: PaperMetadata,
    ingredient_terms: Sequence[str],
) -> str:
    if title_mentions_ingredient(paper.title, ingredient_terms):
        return "title_exact"
    if title_mentions_ingredient(paper.abstract, ingredient_terms):
        return "abstract_exact"
    return "unconfirmed"


def assess_paper_candidate(
    paper: PaperMetadata,
    ingredient_terms: Sequence[str],
) -> PaperAssessment:
    relation_scope = ingredient_mention_scope(paper, ingredient_terms)
    text = f"{paper.title} {paper.abstract}"
    publication_types = {value.casefold() for value in paper.publication_types}
    is_review = bool(publication_types & REVIEW_PUBLICATION_TYPES)
    has_human_publication_type = bool(publication_types & HUMAN_PUBLICATION_TYPES)
    is_human = has_human_publication_type or bool(
        HUMAN_TEXT_RE.search(text)
    )
    is_topical = bool(TOPICAL_TEXT_RE.search(text))
    has_animal_signal = bool(ANIMAL_RE.search(text))
    route_mismatch = bool(NON_TOPICAL_TITLE_RE.search(paper.title)) and not bool(
        TOPICAL_ROUTE_TITLE_RE.search(paper.title)
    )

    if publication_types & SYSTEMATIC_PUBLICATION_TYPES and is_human and is_topical:
        tier, kind = 1, "human_topical_systematic_review"
    elif is_review:
        tier, kind = 8, "review_or_reference"
    elif has_animal_signal and not has_human_publication_type:
        tier, kind = 6, "animal"
    elif (
        publication_types & RANDOMIZED_PUBLICATION_TYPES
        or re.search(r"\brandomi[sz]ed\b", text, re.IGNORECASE)
    ) and is_human and is_topical:
        tier, kind = 2, "human_topical_rct"
    elif (
        publication_types & (CONTROLLED_PUBLICATION_TYPES | CLINICAL_PUBLICATION_TYPES)
        or re.search(r"\b(controlled|split-face|clinical trial)\b", text, re.IGNORECASE)
    ) and is_human and is_topical:
        tier, kind = 3, "human_topical_clinical"
    elif is_human and is_topical:
        tier, kind = 4, "human_topical_observational_or_use_test"
    elif EX_VIVO_RE.search(text):
        tier, kind = 5, "ex_vivo_or_artificial_skin"
    elif has_animal_signal:
        tier, kind = 6, "animal"
    elif IN_VITRO_RE.search(text):
        tier, kind = 7, "in_vitro"
    else:
        tier, kind = 8, "review_or_reference"

    if route_mismatch:
        applicability = "route_mismatch"
    elif COMBINATION_RE.search(text):
        applicability = "combination_or_formulation"
    elif tier <= 4:
        applicability = "human_topical"
    elif tier <= 7:
        applicability = "mechanistic"
    else:
        applicability = "reference_only"

    score = TIER_BASE_SIGNAL[tier]
    if relation_scope == "title_exact":
        score += 5
    elif relation_scope == "unconfirmed":
        score = 0
    if applicability == "combination_or_formulation":
        score = round(score * 0.65)
    elif applicability == "route_mismatch":
        score = round(score * 0.20)
    return PaperAssessment(
        paper=paper,
        evidence_tier=tier,
        evidence_kind=kind,
        relation_scope=relation_scope,
        applicability=applicability,
        signal_score=min(score, 100),
    )


def is_human_topical_focused(
    paper: PaperMetadata,
    ingredient_terms: Sequence[str],
) -> bool:
    assessment = assess_paper_candidate(paper, ingredient_terms)
    return (
        assessment.evidence_tier <= 4
        and assessment.relation_scope != "unconfirmed"
        and assessment.applicability != "route_mismatch"
    )


def is_direct_signal(effect_id: str, matched_functions: Sequence[str]) -> bool:
    return bool(DIRECT_SIGNAL_FUNCTIONS.get(effect_id, set()) & set(matched_functions))


def build_pair_candidates(
    ingredient_rows: Sequence[Mapping[str, str]],
    records: Mapping[str, CosingRecord],
    current_effects: Mapping[str, Mapping[str, str]],
) -> list[PairCandidate]:
    candidates: list[PairCandidate] = []
    for ingredient in ingredient_rows:
        ingredient_id = ingredient["ingredient_id"]
        _, record = match_cosing_record(ingredient.get("name_en", ""), dict(records))
        signals = effect_signals(record.functions if record else ())
        existing = current_effects.get(ingredient_id, {})
        for effect_id in sorted(set(existing) | set(signals)):
            if effect_id in existing:
                strength = "current"
                functions: tuple[str, ...] = ()
                policy = "existing_runtime"
            else:
                strength, functions = signals[effect_id]
                policy = (
                    "direct_cosing_signal"
                    if is_direct_signal(effect_id, functions)
                    else "human_topical_pubmed_required"
                )
            candidates.append(
                PairCandidate(
                    ingredient_id=ingredient_id,
                    name_en=ingredient.get("name_en", ""),
                    effect_id=effect_id,
                    signal_strength=strength,
                    signal_functions=functions,
                    selection_policy=policy,
                )
            )
    return candidates


def screen_candidates(
    *,
    candidates: Sequence[PairCandidate],
    ingredient_terms: Mapping[str, Sequence[str]],
    client: ScreeningClient,
    as_of: date,
    retmax_per_pair: int,
    progress: Callable[[int, int, PairCandidate, int], None] | None = None,
) -> list[dict[str, str]]:
    searched = [
        candidate
        for candidate in candidates
        if candidate.selection_policy != "existing_runtime"
    ]
    raw_pmids: dict[tuple[str, str], list[str]] = {}
    queries: dict[tuple[str, str], str] = {}
    all_pmids: set[str] = set()

    for index, candidate in enumerate(searched, start=1):
        key = (candidate.ingredient_id, candidate.effect_id)
        query = build_pair_query(ingredient_terms[candidate.ingredient_id], candidate.effect_id)
        pmids = client.search(
            query,
            window_start=ALL_HISTORY_START,
            window_end=as_of,
            retmax=retmax_per_pair,
        )
        queries[key] = query
        raw_pmids[key] = pmids
        all_pmids.update(pmids)
        if progress:
            progress(index, len(searched), candidate, len(pmids))

    papers = client.fetch(sorted(all_pmids)) if all_pmids else {}
    output: list[dict[str, str]] = []
    for candidate in candidates:
        key = (candidate.ingredient_id, candidate.effect_id)
        terms = ingredient_terms[candidate.ingredient_id]
        found = raw_pmids.get(key, [])
        assessments = [
            assess_paper_candidate(papers[pmid], terms)
            for pmid in found
            if pmid in papers
        ]
        assessments = [assessment for assessment in assessments if assessment.signal_score > 0]
        assessments.sort(
            key=lambda item: (
                -item.signal_score,
                item.evidence_tier,
                0 if item.relation_scope == "title_exact" else 1,
                item.paper.pmid,
            )
        )
        best = assessments[0] if assessments else None
        qualified = [
            assessment.paper
            for assessment in assessments
            if assessment.evidence_tier <= 4
            and assessment.applicability != "route_mismatch"
        ]
        tier_counts: dict[str, int] = {}
        for assessment in assessments:
            key_name = str(assessment.evidence_tier)
            tier_counts[key_name] = tier_counts.get(key_name, 0) + 1

        if candidate.selection_policy == "existing_runtime":
            selected = True
            status = "existing_runtime"
            review_status = "existing_runtime"
        elif best is not None:
            selected = True
            status = f"evidence_tier_{best.evidence_tier}"
            review_status = "candidate_unverified"
        elif candidate.signal_functions:
            selected = True
            status = "cosing_only"
            review_status = "candidate_unverified"
        else:
            selected = False
            status = "no_pubmed_signal"
            review_status = "not_selected"

        output.append(
            {
                "ingredient_id": candidate.ingredient_id,
                "name_en": candidate.name_en,
                "effect_id": candidate.effect_id,
                "effect_name": EFFECT_NAMES[candidate.effect_id],
                "signal_strength": candidate.signal_strength,
                "signal_functions": "+".join(candidate.signal_functions),
                "selection_policy": candidate.selection_policy,
                "search_query": queries.get(key, ""),
                "raw_pubmed_pmids": "|".join(found),
                "human_topical_pmids": "|".join(paper.pmid for paper in qualified),
                "human_topical_titles_json": json.dumps(
                    [{"pmid": paper.pmid, "title": paper.title} for paper in qualified],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "best_evidence_tier": str(best.evidence_tier) if best else "",
                "best_evidence_kind": best.evidence_kind if best else "",
                "best_relation_scope": best.relation_scope if best else "",
                "best_applicability": best.applicability if best else "",
                "best_pmid": best.paper.pmid if best else "",
                "best_title": best.paper.title if best else "",
                "best_signal_score": str(best.signal_score) if best else "0",
                "tier_counts_json": json.dumps(
                    tier_counts,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "candidate_papers_json": json.dumps(
                    [
                        {
                            "pmid": assessment.paper.pmid,
                            "tier": assessment.evidence_tier,
                            "kind": assessment.evidence_kind,
                            "relation_scope": assessment.relation_scope,
                            "applicability": assessment.applicability,
                            "signal_score": assessment.signal_score,
                            "title": assessment.paper.title,
                        }
                        for assessment in assessments
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "screening_status": status,
                "selected_for_paper_review": "Y" if selected else "N",
                "review_status": review_status,
                "score_change": "none",
                "screened_on": as_of.isoformat(),
                "screening_version": SCREENING_VERSION,
            }
        )

    output.sort(key=lambda row: (row["ingredient_id"], row["effect_id"]))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--cosing-cache",
        type=Path,
        default=Path("data/reconciliation/ingredient_cosing_function_snapshot.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_pubmed_screening.csv"),
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--retmax-per-pair", type=int, default=DEFAULT_RETMAX_PER_PAIR)
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""))
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ingredient_rows = [
        row
        for row in read_csv(args.data_dir / "ingredients.csv")
        if not row["ingredient_id"].startswith("ing_pending_")
    ]
    records, _ = load_cosing_cache(args.cosing_cache)
    current_effects = load_current_effects(args.data_dir / "ingredient_effect.csv")
    candidates = build_pair_candidates(ingredient_rows, records, current_effects)
    ingredient_ids = {candidate.ingredient_id for candidate in candidates}
    terms = load_ingredient_terms(
        ingredient_rows,
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        ingredient_ids,
    )
    client = PubMedClient(
        email=args.email,
        api_key=args.api_key,
        tool=DEFAULT_TOOL_NAME,
        request_delay_seconds=args.request_delay,
    )

    def report_progress(index: int, total: int, candidate: PairCandidate, hits: int) -> None:
        if index == 1 or index % 25 == 0 or index == total:
            print(
                f"PubMed preflight {index}/{total}: "
                f"{candidate.ingredient_id}×{candidate.effect_id} raw_hits={hits}",
                flush=True,
            )

    rows = screen_candidates(
        candidates=candidates,
        ingredient_terms=terms,
        client=client,
        as_of=args.as_of,
        retmax_per_pair=args.retmax_per_pair,
        progress=report_progress,
    )
    write_csv(args.output, rows)
    selected_pairs = [row for row in rows if row["selected_for_paper_review"] == "Y"]
    selected_ingredients = {row["ingredient_id"] for row in selected_pairs}
    print(
        f"screened_pairs={len(rows)} selected_pairs={len(selected_pairs)} "
        f"selected_ingredients={len(selected_ingredients)} "
        f"requests={client.request_count} retries={client.retry_count} output={args.output}"
    )


if __name__ == "__main__":
    main()
