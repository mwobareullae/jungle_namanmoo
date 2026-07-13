#!/usr/bin/env python3
"""Record the robots-blocked KCI portion of filter-contract v1.1 discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Mapping, Sequence

from fresh_pubmed_search_v1_1 import (
    PIPELINE_VERSION as PUBMED_PIPELINE_VERSION,
    build_approved_terms,
    file_sha256,
    read_csv,
    text_sha256,
    utc_now,
    write_csv,
)


PIPELINE_VERSION = "mwbl-ingredient-evidence-filter-v1.1-fresh-kci"
KCI_ROBOTS_URL = "https://www.kci.go.kr/robots.txt"
KCI_SEARCH_URL = "https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiSearch.kci"
USER_AGENT = "mwbl-evidence-research/1.1"

QUERY_FIELDS: tuple[str, ...] = (
    "query_id",
    "source",
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "canonical_name_en",
    "approved_search_terms",
    "search_query",
    "query_sha256",
    "query_version",
    "request_status",
    "total_hit_count",
    "raw_hit_count",
    "retrieval_cap",
    "retrieved_count",
    "returned_count",
    "pagination_complete",
    "pagination_status",
    "searched_at",
    "query_contract_status",
    "rerun_required",
    "error_type",
    "error_message",
    "robots_url",
    "robots_fetched_at_utc",
    "robots_sha256",
    "robots_rule",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
)

CANDIDATE_FIELDS: tuple[str, ...] = (
    "source",
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "canonical_name_en",
    "source_id",
    "control_no",
    "title",
    "pre_abstract",
    "authors",
    "journal",
    "publication_year",
    "source_url",
    "best_result_position",
    "matched_search_terms",
    "execution_query_ids",
    "metadata_status",
    "retrieved_at_utc",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
)


class KciAccessError(RuntimeError):
    pass


def fetch_robots(timeout_seconds: float = 30.0) -> tuple[str, str]:
    request = urllib.request.Request(
        KCI_ROBOTS_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise KciAccessError(f"KCI robots.txt returned HTTP {response.status}")
        return response.read().decode("utf-8", "replace"), utc_now()


def robots_allows(robots_text: str, target_url: str = KCI_SEARCH_URL) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(KCI_ROBOTS_URL)
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(USER_AGENT, target_url)


def build_rows(
    cohort_rows: Sequence[Mapping[str, str]],
    terms_by_id: Mapping[str, Sequence[object]],
    robots_text: str,
    robots_fetched_at: str,
) -> list[dict[str, object]]:
    robots_sha = text_sha256(robots_text)
    rows: list[dict[str, object]] = []
    for cohort_row in cohort_rows:
        ingredient_id = cohort_row["ingredient_id"].strip()
        terms = [getattr(value, "term") for value in terms_by_id[ingredient_id]]
        planned_queries = [f'"{term}" skin' for term in terms]
        search_query = json.dumps(
            planned_queries, ensure_ascii=False, separators=(",", ":")
        )
        query_sha = text_sha256(search_query)
        rows.append(
            {
                "query_id": f"kci:{ingredient_id}:{query_sha[:16]}",
                "source": "kci",
                "ingredient_rank": cohort_row.get("ingredient_rank", ""),
                "ingredient_id": ingredient_id,
                "name_ko": cohort_row.get("name_ko", ""),
                "canonical_name_en": terms[0],
                "approved_search_terms": "|".join(terms),
                "search_query": search_query,
                "query_sha256": query_sha,
                "query_version": "mwbl-kci-approved-term-skin-context-v1.1",
                "request_status": "access_unavailable",
                "total_hit_count": "",
                "raw_hit_count": "",
                "retrieval_cap": 0,
                "retrieved_count": 0,
                "returned_count": 0,
                "pagination_complete": "N",
                "pagination_status": "not_run_robots_disallowed",
                "searched_at": robots_fetched_at,
                "query_contract_status": "approved_terms_only",
                "rerun_required": "N",
                "error_type": "robots_disallowed",
                "error_message": "KCI robots.txt disallows / for User-agent: *; search was not requested",
                "robots_url": KCI_ROBOTS_URL,
                "robots_fetched_at_utc": robots_fetched_at,
                "robots_sha256": robots_sha,
                "robots_rule": "User-agent: * / Disallow: /",
                "review_status": "candidate_unverified",
                "runtime_score_change": "none",
                "pipeline_version": PIPELINE_VERSION,
            }
        )
    return rows


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466.csv"),
    )
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--aliases", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/reconciliation/v1_1_fresh")
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cohort = read_csv(args.cohort)
    ids = {row.get("ingredient_id", "").strip() for row in cohort}
    if len(cohort) != 466 or len(ids) != 466 or "" in ids:
        raise KciAccessError("Frozen KCI cohort must contain 466 unique ingredient IDs")
    terms = build_approved_terms(ids, read_csv(args.ingredients), read_csv(args.aliases))
    robots_text, fetched_at = fetch_robots()
    if robots_allows(robots_text):
        raise KciAccessError("KCI robots.txt unexpectedly allows the configured collector")

    query_path = args.output_dir / "kci_query_log_466_v1_1_fresh.csv"
    candidate_path = args.output_dir / "kci_candidates_466_v1_1_fresh.csv"
    summary_path = args.output_dir / "kci_search_summary_466_v1_1_fresh.json"
    rows = build_rows(cohort, terms, robots_text, fetched_at)
    write_csv(query_path, QUERY_FIELDS, rows)
    write_csv(candidate_path, CANDIDATE_FIELDS, [])
    summary = {
        "source": "kci",
        "pipeline_version": PIPELINE_VERSION,
        "frozen_cohort_row_count": 466,
        "query_log_row_count": len(rows),
        "request_status_counts": {"access_unavailable": len(rows)},
        "candidate_row_count": 0,
        "robots_url": KCI_ROBOTS_URL,
        "robots_fetched_at_utc": fetched_at,
        "robots_sha256": text_sha256(robots_text),
        "robots_evidence_text": robots_text,
        "robots_decision": "collection_prohibited_for_user_agent_star",
        "search_requests_sent": 0,
        "input_sha256": {
            str(args.cohort): file_sha256(args.cohort),
            str(args.ingredients): file_sha256(args.ingredients),
            str(args.aliases): file_sha256(args.aliases),
        },
        "output_sha256": {
            query_path.name: file_sha256(query_path),
            candidate_path.name: file_sha256(candidate_path),
        },
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
