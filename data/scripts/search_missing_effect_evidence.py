#!/usr/bin/env python3
"""Run a broader PubMed second pass for pairs missed by the strict query.

The ingredient must still appear exactly in the title or abstract. The broader
query only relaxes the outcome vocabulary and the redundant requirement that a
paper contain both an effect phrase and a separate skin-context phrase.
Results remain candidate_unverified and never change runtime scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from build_ingredient_role_inventory import EFFECT_NAMES
from effect_outcome_dictionary import APPROVED_DISCOVERY_TERMS
from discover_new_evidence import (
    DEFAULT_REQUEST_DELAY_SECONDS,
    DEFAULT_TOOL_NAME,
    PaperMetadata,
    PubMedClient,
    load_ingredient_terms,
    pubmed_title_abstract_term,
)
from screen_effect_review_candidates import (
    ALL_HISTORY_START,
    PaperAssessment,
    assess_paper_candidate,
    normalize_phrase,
)


SECOND_PASS_VERSION = "mwbl-missing-effect-search-v1"
DEFAULT_RETMAX_PER_INGREDIENT = 100

# Compatibility name retained for the second-source collector. Search terms
# now come from the same reviewed dictionary as outcome mapping.
EXPANDED_EFFECT_TERMS: dict[str, tuple[str, ...]] = APPROVED_DISCOVERY_TERMS

EXPANDED_SKIN_CONTEXT_TERMS = (
    "skin",
    "topical",
    "cutaneous",
    "dermal",
    "epidermis",
    "epidermal",
    "stratum corneum",
    "corneocyte",
    "keratinocyte",
    "dermatology",
    "dermatitis",
    "cosmetic",
)

OUTPUT_FIELDS = [
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "search_query",
    "raw_pubmed_pmids",
    "raw_hit_count",
    "matched_pmids",
    "matched_paper_count",
    "best_evidence_tier",
    "best_evidence_kind",
    "best_relation_scope",
    "best_effect_match_scope",
    "best_applicability",
    "best_pmid",
    "best_title",
    "best_signal_score",
    "candidate_papers_json",
    "second_pass_status",
    "review_status",
    "score_change",
    "searched_on",
    "search_version",
]


class SearchClient(Protocol):
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    normalized_text = f" {normalize_phrase(text)} "
    return any(
        normalized_term and f" {normalized_term} " in normalized_text
        for term in terms
        if (normalized_term := normalize_phrase(term))
    )


def _abstract_sentences(abstract: str) -> list[str]:
    return [
        value.strip()
        for value in re.split(r"(?<=[.!?])\s+|\s+(?=[A-Z]+:)", abstract or "")
        if value.strip()
    ]


def effect_match_scope(
    paper: PaperMetadata,
    effect_id: str,
    ingredient_terms: Sequence[str],
) -> str:
    effect_terms = EXPANDED_EFFECT_TERMS[effect_id]
    title_has_ingredient = _contains_any(paper.title, ingredient_terms)
    if (
        title_has_ingredient
        and _contains_any(paper.title, effect_terms)
        and _contains_any(paper.title, EXPANDED_SKIN_CONTEXT_TERMS)
    ):
        return "title_effect"

    for sentence in _abstract_sentences(paper.abstract):
        if not _contains_any(sentence, effect_terms):
            continue
        if not _contains_any(sentence, EXPANDED_SKIN_CONTEXT_TERMS):
            continue
        if title_has_ingredient or _contains_any(sentence, ingredient_terms):
            return "abstract_effect"
    return "unconfirmed"


def build_expanded_query(
    ingredient_terms: Sequence[str],
    effect_ids: Sequence[str],
) -> str:
    usable_terms = [term for term in ingredient_terms if len(normalize_phrase(term)) >= 4]
    if not usable_terms:
        return ""
    ingredient_clause = " OR ".join(
        pubmed_title_abstract_term(term) for term in usable_terms[:16]
    )
    outcome_terms = sorted(
        {
            term
            for effect_id in effect_ids
            for term in EXPANDED_EFFECT_TERMS[effect_id]
        }
        | set(EXPANDED_SKIN_CONTEXT_TERMS)
    )
    outcome_clause = " OR ".join(pubmed_title_abstract_term(term) for term in outcome_terms)
    return f"({ingredient_clause}) AND ({outcome_clause})"


def search_missing_pairs(
    *,
    pair_rows: Sequence[Mapping[str, str]],
    ingredient_terms: Mapping[str, Sequence[str]],
    client: SearchClient,
    as_of: date,
    retmax_per_ingredient: int,
    progress: Callable[[int, int, str, int], None] | None = None,
) -> list[dict[str, object]]:
    pairs_by_ingredient: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in pair_rows:
        pairs_by_ingredient[row["ingredient_id"]].append(row)

    queries: dict[str, str] = {}
    raw_pmids: dict[str, list[str]] = {}
    all_pmids: set[str] = set()
    ingredient_ids = sorted(pairs_by_ingredient)
    for index, ingredient_id in enumerate(ingredient_ids, start=1):
        effect_ids = sorted({row["effect_id"] for row in pairs_by_ingredient[ingredient_id]})
        query = build_expanded_query(ingredient_terms[ingredient_id], effect_ids)
        queries[ingredient_id] = query
        if query:
            pmids = client.search(
                query,
                window_start=ALL_HISTORY_START,
                window_end=as_of,
                retmax=retmax_per_ingredient,
            )
        else:
            pmids = []
        raw_pmids[ingredient_id] = pmids
        all_pmids.update(pmids)
        if progress:
            progress(index, len(ingredient_ids), ingredient_id, len(pmids))

    papers = client.fetch(sorted(all_pmids, key=int)) if all_pmids else {}
    output: list[dict[str, object]] = []
    for ingredient_id in ingredient_ids:
        ingredient_papers = [
            papers[pmid]
            for pmid in raw_pmids[ingredient_id]
            if pmid in papers
        ]
        terms = ingredient_terms[ingredient_id]
        for pair in pairs_by_ingredient[ingredient_id]:
            effect_id = pair["effect_id"]
            candidates: list[tuple[PaperAssessment, str]] = []
            for paper in ingredient_papers:
                assessment = assess_paper_candidate(paper, terms)
                if assessment.relation_scope == "unconfirmed":
                    continue
                match_scope = effect_match_scope(paper, effect_id, terms)
                if match_scope == "unconfirmed":
                    continue
                candidates.append((assessment, match_scope))
            candidates.sort(
                key=lambda item: (
                    -item[0].signal_score,
                    item[0].evidence_tier,
                    0 if item[1] == "title_effect" else 1,
                    item[0].paper.pmid,
                )
            )
            best = candidates[0] if candidates else None
            status = "expanded_candidate_found" if best else "no_expanded_pubmed_candidate"
            output.append(
                {
                    "ingredient_id": ingredient_id,
                    "name_ko": pair.get("name_ko", ""),
                    "name_en": pair.get("name_en", ""),
                    "effect_id": effect_id,
                    "effect_name": EFFECT_NAMES[effect_id],
                    "search_query": queries[ingredient_id],
                    "raw_pubmed_pmids": "|".join(raw_pmids[ingredient_id]),
                    "raw_hit_count": len(raw_pmids[ingredient_id]),
                    "matched_pmids": "|".join(item[0].paper.pmid for item in candidates),
                    "matched_paper_count": len(candidates),
                    "best_evidence_tier": best[0].evidence_tier if best else "",
                    "best_evidence_kind": best[0].evidence_kind if best else "",
                    "best_relation_scope": best[0].relation_scope if best else "",
                    "best_effect_match_scope": best[1] if best else "",
                    "best_applicability": best[0].applicability if best else "",
                    "best_pmid": best[0].paper.pmid if best else "",
                    "best_title": best[0].paper.title if best else "",
                    "best_signal_score": best[0].signal_score if best else 0,
                    "candidate_papers_json": json.dumps(
                        [
                            {
                                "pmid": assessment.paper.pmid,
                                "title": assessment.paper.title,
                                "tier": assessment.evidence_tier,
                                "relation_scope": assessment.relation_scope,
                                "effect_match_scope": match_scope,
                                "applicability": assessment.applicability,
                                "signal_score": assessment.signal_score,
                            }
                            for assessment, match_scope in candidates
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "second_pass_status": status,
                    "review_status": "candidate_unverified" if best else "not_found",
                    "score_change": "none",
                    "searched_on": as_of.isoformat(),
                    "search_version": SECOND_PASS_VERSION,
                }
            )
    output.sort(key=lambda row: (str(row["ingredient_id"]), str(row["effect_id"])))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--proposal",
        type=Path,
        default=Path(
            "data/reconciliation/ingredient_effect_business_score_proposal_500.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_pubmed_second_pass.csv"),
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--retmax-per-ingredient",
        type=int,
        default=DEFAULT_RETMAX_PER_INGREDIENT,
    )
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""))
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pair_rows = [
        row
        for row in read_csv(args.proposal)
        if row.get("score_exclusion_reason") == "no_exact_pubmed_paper"
    ]
    ingredient_ids = {row["ingredient_id"] for row in pair_rows}
    terms = load_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        ingredient_ids,
    )
    client = PubMedClient(
        email=args.email,
        api_key=args.api_key,
        tool=DEFAULT_TOOL_NAME,
        request_delay_seconds=args.request_delay,
    )

    def progress(index: int, total: int, ingredient_id: str, hit_count: int) -> None:
        if index == 1 or index % 25 == 0 or index == total:
            print(
                f"PubMed second pass {index}/{total}: "
                f"{ingredient_id} raw_hits={hit_count}",
                flush=True,
            )

    rows = search_missing_pairs(
        pair_rows=pair_rows,
        ingredient_terms=terms,
        client=client,
        as_of=args.as_of,
        retmax_per_ingredient=args.retmax_per_ingredient,
        progress=progress,
    )
    write_csv(args.output, rows)
    print(
        "PubMed second pass complete: "
        f"pairs={len(rows)} found={sum(row['best_pmid'] != '' for row in rows)} "
        f"requests={client.request_count} retries={client.retry_count} output={args.output}"
    )


if __name__ == "__main__":
    main()
