#!/usr/bin/env python3
"""Search non-PubMed Europe PMC records for still-missing evidence pairs."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from build_ingredient_role_inventory import EFFECT_NAMES
from discover_new_evidence import PaperMetadata, load_ingredient_terms, normalize_doi
from screen_effect_review_candidates import assess_paper_candidate, normalize_phrase
from search_missing_effect_evidence import (
    EXPANDED_EFFECT_TERMS,
    EXPANDED_SKIN_CONTEXT_TERMS,
    effect_match_scope,
    read_csv,
)


EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SEARCH_VERSION = "mwbl-missing-effect-europe-pmc-v1"
DEFAULT_PAGE_SIZE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.25

OUTPUT_FIELDS = [
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "search_query",
    "raw_hit_count",
    "matched_paper_count",
    "best_paper_key",
    "best_source",
    "best_source_id",
    "best_doi",
    "best_title",
    "best_evidence_tier",
    "best_evidence_kind",
    "best_relation_scope",
    "best_effect_match_scope",
    "best_applicability",
    "best_signal_score",
    "candidate_papers_json",
    "search_status",
    "review_status",
    "score_change",
    "search_version",
]


@dataclass(frozen=True)
class EuropePmcPaper:
    source: str
    source_id: str
    pmid: str
    pmcid: str
    doi: str
    title: str
    abstract: str
    publication_types: tuple[str, ...]

    @property
    def paper_key(self) -> str:
        if self.doi:
            return f"DOI:{self.doi}"
        return f"EPMC:{self.source}:{self.source_id}"

    def as_pubmed_metadata(self) -> PaperMetadata:
        return PaperMetadata(
            pmid=self.source_id,
            doi=self.doi,
            title=self.title,
            publication_types=self.publication_types,
            abstract=self.abstract,
        )


class EuropePmcSearchClient(Protocol):
    request_count: int
    retry_count: int

    def search(self, query: str, *, page_size: int) -> tuple[int, list[EuropePmcPaper]]: ...


class EuropePmcClient:
    def __init__(
        self,
        *,
        request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.opener = opener or urllib.request.build_opener()
        self.request_count = 0
        self.retry_count = 0
        self._last_request_at = 0.0

    def search(self, query: str, *, page_size: int) -> tuple[int, list[EuropePmcPaper]]:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": str(page_size),
            }
        )
        request = urllib.request.Request(
            f"{EUROPE_PMC_SEARCH_URL}?{params}",
            headers={"User-Agent": "mwbl_evidence_discovery/1.0"},
        )
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.request_count += 1
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                results = payload.get("resultList", {}).get("result", [])
                return int(payload.get("hitCount") or 0), [
                    parse_europe_pmc_paper(result) for result in results
                ]
            except (OSError, ValueError, json.JSONDecodeError):
                if attempt >= self.max_retries:
                    raise
                self.retry_count += 1
                time.sleep(min(8.0, 2.0**attempt))
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_delay_seconds:
            time.sleep(self.request_delay_seconds - elapsed)
        self._last_request_at = time.monotonic()


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()


def parse_europe_pmc_paper(row: Mapping[str, object]) -> EuropePmcPaper:
    pub_type = row.get("pubTypeList") or {}
    publication_types = ()
    if isinstance(pub_type, Mapping):
        values = pub_type.get("pubType") or []
        if isinstance(values, list):
            publication_types = tuple(str(value) for value in values)
    return EuropePmcPaper(
        source=str(row.get("source") or ""),
        source_id=str(row.get("id") or ""),
        pmid=str(row.get("pmid") or ""),
        pmcid=str(row.get("pmcid") or ""),
        doi=normalize_doi(str(row.get("doi") or "")),
        title=_plain_text(str(row.get("title") or "")),
        abstract=_plain_text(str(row.get("abstractText") or "")),
        publication_types=publication_types,
    )


def _epmc_field_phrase(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.replace('"', " ")).strip()
    return f'TITLE_ABS:"{cleaned}"'


def build_europe_pmc_query(
    ingredient_terms: Sequence[str],
    effect_ids: Sequence[str],
) -> str:
    usable_terms = [term for term in ingredient_terms if len(normalize_phrase(term)) >= 4]
    if not usable_terms:
        return ""
    ingredient_clause = " OR ".join(_epmc_field_phrase(term) for term in usable_terms[:16])
    outcome_terms = sorted(
        {
            term
            for effect_id in effect_ids
            for term in EXPANDED_EFFECT_TERMS[effect_id]
        }
        | set(EXPANDED_SKIN_CONTEXT_TERMS)
    )
    outcome_clause = " OR ".join(_epmc_field_phrase(term) for term in outcome_terms)
    return f"({ingredient_clause}) AND ({outcome_clause}) AND NOT SRC:MED AND NOT SRC:PAT"


def search_europe_pmc_pairs(
    *,
    pair_rows: Sequence[Mapping[str, str]],
    ingredient_terms: Mapping[str, Sequence[str]],
    client: EuropePmcSearchClient,
    page_size: int,
) -> list[dict[str, object]]:
    pairs_by_ingredient: dict[str, list[Mapping[str, str]]] = {}
    for row in pair_rows:
        pairs_by_ingredient.setdefault(row["ingredient_id"], []).append(row)

    output: list[dict[str, object]] = []
    total = len(pairs_by_ingredient)
    for index, ingredient_id in enumerate(sorted(pairs_by_ingredient), start=1):
        pairs = pairs_by_ingredient[ingredient_id]
        effect_ids = sorted({row["effect_id"] for row in pairs})
        query = build_europe_pmc_query(ingredient_terms[ingredient_id], effect_ids)
        if query:
            hit_count, papers = client.search(query, page_size=page_size)
        else:
            hit_count, papers = 0, []
        if index == 1 or index % 25 == 0 or index == total:
            print(
                f"Europe PMC second source {index}/{total}: "
                f"{ingredient_id} raw_hits={hit_count}",
                flush=True,
            )

        for pair in pairs:
            effect_id = pair["effect_id"]
            candidates: list[tuple[EuropePmcPaper, object, str]] = []
            for paper in papers:
                metadata = paper.as_pubmed_metadata()
                assessment = assess_paper_candidate(metadata, ingredient_terms[ingredient_id])
                if assessment.relation_scope == "unconfirmed":
                    continue
                match_scope = effect_match_scope(
                    metadata,
                    effect_id,
                    ingredient_terms[ingredient_id],
                )
                if match_scope == "unconfirmed":
                    continue
                candidates.append((paper, assessment, match_scope))
            candidates.sort(
                key=lambda item: (
                    -item[1].signal_score,
                    item[1].evidence_tier,
                    0 if item[2] == "title_effect" else 1,
                    item[0].paper_key,
                )
            )
            best = candidates[0] if candidates else None
            output.append(
                {
                    "ingredient_id": ingredient_id,
                    "name_ko": pair.get("name_ko", ""),
                    "name_en": pair.get("name_en", ""),
                    "effect_id": effect_id,
                    "effect_name": EFFECT_NAMES[effect_id],
                    "search_query": query,
                    "raw_hit_count": hit_count,
                    "matched_paper_count": len(candidates),
                    "best_paper_key": best[0].paper_key if best else "",
                    "best_source": best[0].source if best else "",
                    "best_source_id": best[0].source_id if best else "",
                    "best_doi": best[0].doi if best else "",
                    "best_title": best[0].title if best else "",
                    "best_evidence_tier": best[1].evidence_tier if best else "",
                    "best_evidence_kind": best[1].evidence_kind if best else "",
                    "best_relation_scope": best[1].relation_scope if best else "",
                    "best_effect_match_scope": best[2] if best else "",
                    "best_applicability": best[1].applicability if best else "",
                    "best_signal_score": best[1].signal_score if best else 0,
                    "candidate_papers_json": json.dumps(
                        [
                            {
                                "paper_key": paper.paper_key,
                                "source": paper.source,
                                "source_id": paper.source_id,
                                "doi": paper.doi,
                                "title": paper.title,
                                "tier": assessment.evidence_tier,
                                "relation_scope": assessment.relation_scope,
                                "effect_match_scope": match_scope,
                                "applicability": assessment.applicability,
                                "signal_score": assessment.signal_score,
                            }
                            for paper, assessment, match_scope in candidates
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "search_status": "expanded_candidate_found" if best else "not_found",
                    "review_status": "candidate_unverified" if best else "not_found",
                    "score_change": "none",
                    "search_version": SEARCH_VERSION,
                }
            )
    output.sort(key=lambda row: (str(row["ingredient_id"]), str(row["effect_id"])))
    return output


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
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
        default=Path(
            "data/reconciliation/ingredient_effect_europe_pmc_second_source.csv"
        ),
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
    )
    args = parser.parse_args()

    pair_rows = [
        row
        for row in read_csv(args.proposal)
        if row.get("score_exclusion_reason") == "no_exact_pubmed_paper"
    ]
    ingredient_ids = {row["ingredient_id"] for row in pair_rows}
    ingredient_terms = load_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        ingredient_ids,
    )
    client = EuropePmcClient(request_delay_seconds=args.request_delay)
    rows = search_europe_pmc_pairs(
        pair_rows=pair_rows,
        ingredient_terms=ingredient_terms,
        client=client,
        page_size=args.page_size,
    )
    write_csv(args.output, rows)
    print(
        "Europe PMC second source complete: "
        f"pairs={len(rows)} found={sum(row['best_paper_key'] != '' for row in rows)} "
        f"requests={client.request_count} retries={client.retry_count} output={args.output}"
    )


if __name__ == "__main__":
    main()
