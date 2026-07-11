#!/usr/bin/env python3
"""Screen canonical ingredient/effect pairs before paper review.

Existing runtime pairs are preserved. BLEACHING and SOOTHING remain direct
search signals. Broad moisture signals, ANTI-SEBORRHEIC, and KERATOLYTIC must
have at least one ingredient-focused human topical PubMed candidate.

This script never approves evidence or changes runtime scores.
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


SCREENING_VERSION = "mwbl-effect-review-screen-v1"
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
    r"\b(patient|patients|participant|participants|volunteer|volunteers|women|men|"
    r"randomi[sz]ed|double-blind|split-face|clinical trial)\b",
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
    r"mesotherapy|filler|microneedle)\b",
    re.IGNORECASE,
)
REVIEW_PUBLICATION_TYPES = {"review", "systematic review", "meta-analysis"}

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


def is_human_topical_focused(
    paper: PaperMetadata,
    ingredient_terms: Sequence[str],
) -> bool:
    if not paper.abstract or not title_mentions_ingredient(paper.title, ingredient_terms):
        return False
    if NON_TOPICAL_TITLE_RE.search(paper.title) and not re.search(
        r"\b(topical|cream|lotion|serum|ointment|emulsion|moisturi[sz]er)\b",
        paper.title,
        re.IGNORECASE,
    ):
        return False
    text = f"{paper.title} {paper.abstract}"
    publication_types = {value.casefold() for value in paper.publication_types}
    if publication_types & REVIEW_PUBLICATION_TYPES and not (
        publication_types & HUMAN_PUBLICATION_TYPES
    ):
        return False
    is_human = bool(publication_types & HUMAN_PUBLICATION_TYPES) or bool(
        HUMAN_TEXT_RE.search(text)
    )
    is_topical = bool(TOPICAL_TEXT_RE.search(text))
    return is_human and is_topical


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
    conditional = [
        candidate
        for candidate in candidates
        if candidate.selection_policy == "human_topical_pubmed_required"
    ]
    raw_pmids: dict[tuple[str, str], list[str]] = {}
    queries: dict[tuple[str, str], str] = {}
    all_pmids: set[str] = set()

    for index, candidate in enumerate(conditional, start=1):
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
            progress(index, len(conditional), candidate, len(pmids))

    papers = client.fetch(sorted(all_pmids)) if all_pmids else {}
    output: list[dict[str, str]] = []
    for candidate in candidates:
        key = (candidate.ingredient_id, candidate.effect_id)
        terms = ingredient_terms[candidate.ingredient_id]
        found = raw_pmids.get(key, [])
        qualified = [
            papers[pmid]
            for pmid in found
            if pmid in papers and is_human_topical_focused(papers[pmid], terms)
        ]

        if candidate.selection_policy == "existing_runtime":
            selected = True
            status = "existing_runtime"
            review_status = "existing_runtime"
        elif candidate.selection_policy == "direct_cosing_signal":
            selected = True
            status = "direct_cosing_signal"
            review_status = "candidate_unverified"
        elif qualified:
            selected = True
            status = "human_topical_pubmed_candidate"
            review_status = "candidate_unverified"
        else:
            selected = False
            status = "no_human_topical_pubmed_candidate"
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
