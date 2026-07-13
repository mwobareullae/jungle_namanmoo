#!/usr/bin/env python3
"""Search free scholarly indexes for ingredient-first skin evidence.

This is a discovery-only collector. It writes bibliographic candidates and a
query log. It never changes runtime evidence, scores, DB rows, or review state.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from discover_new_evidence import normalize_doi


PIPELINE_VERSION = "mwbl-ingredient-multisource-discovery-v1"
SOURCES = ("europe_pmc", "openalex", "crossref")
DEFAULT_ROWS_PER_INGREDIENT = 25

PAPER_FIELDS = [
    "source",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "source_id",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "authors",
    "abstract",
    "source_url",
    "search_query",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
]

LOG_FIELDS = [
    "source",
    "ingredient_id",
    "name_en",
    "search_query",
    "raw_hit_count",
    "returned_count",
    "request_status",
    "error_message",
    "pipeline_version",
]


@dataclass(frozen=True)
class SourcePaper:
    source_id: str
    pmid: str = ""
    pmcid: str = ""
    doi: str = ""
    title: str = ""
    journal: str = ""
    publication_date: str = ""
    publication_types: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    abstract: str = ""
    source_url: str = ""


class RateLimitedJsonClient:
    def __init__(
        self,
        *,
        min_interval_seconds: float,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def get_json(self, url: str) -> Mapping[str, object]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "mwbl-evidence-discovery/1.0 (+https://github.com/mwobareullae/jungle_namanmoo)",
            },
        )
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise
                retry_after = float(exc.headers.get("Retry-After") or 0)
                time.sleep(max(retry_after, min(16.0, 2.0**attempt)))
            except (OSError, ValueError, json.JSONDecodeError):
                if attempt >= self.max_retries:
                    raise
                time.sleep(min(16.0, 2.0**attempt))
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
            self._last_request_at = time.monotonic()


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


def plain_text(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"<[^>]+>", " ", html.unescape(value or "")),
    ).strip()


def reconstruct_openalex_abstract(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    positions: list[tuple[int, str]] = []
    for word, raw_indexes in value.items():
        if not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            try:
                positions.append((int(raw_index), str(word)))
            except (TypeError, ValueError):
                continue
    return " ".join(word for _, word in sorted(positions))


def preferred_search_term(row: Mapping[str, str]) -> str:
    terms = [value.strip() for value in row.get("search_terms", "").split("|") if value.strip()]
    if not terms:
        terms = [row.get("name_en", "").strip()]
    simple = [
        term
        for term in terms
        if 3 < len(term) <= 80 and not re.search(r"[/()]", term)
    ]
    return (simple or terms)[0]


def europe_pmc_query(row: Mapping[str, str]) -> str:
    terms = [value.strip() for value in row.get("search_terms", "").split("|") if value.strip()]
    terms = [term.replace('"', " ") for term in terms[:12] if len(term) >= 4]
    ingredient = " OR ".join(f'TITLE_ABS:"{term}"' for term in terms)
    skin = " OR ".join(
        f'TITLE_ABS:"{term}"'
        for term in ("skin", "topical", "cutaneous", "dermatology", "cosmetic")
    )
    return f"({ingredient}) AND ({skin}) AND NOT SRC:MED AND NOT SRC:PAT"


def search_europe_pmc(
    client: RateLimitedJsonClient,
    row: Mapping[str, str],
    rows_per_ingredient: int,
) -> tuple[str, int, list[SourcePaper]]:
    query = europe_pmc_query(row)
    params = urllib.parse.urlencode(
        {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": rows_per_ingredient,
        }
    )
    payload = client.get_json(
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
    )
    papers = []
    for item in payload.get("resultList", {}).get("result", []):
        pub_types = item.get("pubTypeList") or {}
        raw_pub_types = pub_types.get("pubType") if isinstance(pub_types, Mapping) else []
        papers.append(
            SourcePaper(
                source_id=str(item.get("id") or ""),
                pmid=str(item.get("pmid") or ""),
                pmcid=str(item.get("pmcid") or ""),
                doi=normalize_doi(str(item.get("doi") or "")),
                title=plain_text(str(item.get("title") or "")),
                journal=plain_text(str(item.get("journalTitle") or "")),
                publication_date=str(item.get("firstPublicationDate") or ""),
                publication_types=tuple(str(value) for value in (raw_pub_types or [])),
                authors=tuple(
                    str(author.get("fullName") or "")
                    for author in (item.get("authorList") or {}).get("author", [])
                    if isinstance(author, Mapping)
                ),
                abstract=plain_text(str(item.get("abstractText") or "")),
                source_url=f"https://europepmc.org/article/{item.get('source', '')}/{item.get('id', '')}",
            )
        )
    return query, int(payload.get("hitCount") or 0), papers


def search_openalex(
    client: RateLimitedJsonClient,
    row: Mapping[str, str],
    rows_per_ingredient: int,
) -> tuple[str, int, list[SourcePaper]]:
    query = f'"{preferred_search_term(row)}" skin topical'
    params: dict[str, object] = {
        "search": query,
        "per-page": rows_per_ingredient,
        "select": (
            "id,doi,title,display_name,publication_date,type,primary_location,"
            "authorships,abstract_inverted_index,ids"
        ),
    }
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key
    payload = client.get_json(
        f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
    )
    papers = []
    for item in payload.get("results", []):
        ids = item.get("ids") or {}
        raw_pmid = str(ids.get("pmid") or "") if isinstance(ids, Mapping) else ""
        pmid = raw_pmid.rsplit("/", 1)[-1] if raw_pmid else ""
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {} if isinstance(primary_location, Mapping) else {}
        authors = []
        for authorship in item.get("authorships") or []:
            if not isinstance(authorship, Mapping):
                continue
            author = authorship.get("author") or {}
            if isinstance(author, Mapping) and author.get("display_name"):
                authors.append(str(author["display_name"]))
        papers.append(
            SourcePaper(
                source_id=str(item.get("id") or "").rsplit("/", 1)[-1],
                pmid=pmid,
                doi=normalize_doi(str(item.get("doi") or "")),
                title=plain_text(str(item.get("title") or item.get("display_name") or "")),
                journal=plain_text(str(source.get("display_name") or ""))
                if isinstance(source, Mapping)
                else "",
                publication_date=str(item.get("publication_date") or ""),
                publication_types=(str(item.get("type") or ""),),
                authors=tuple(authors),
                abstract=reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                source_url=str(item.get("id") or ""),
            )
        )
    meta = payload.get("meta") or {}
    return query, int(meta.get("count") or 0), papers


def _crossref_date(item: Mapping[str, object]) -> str:
    for field in ("published-print", "published-online", "issued", "created"):
        value = item.get(field) or {}
        parts = value.get("date-parts") if isinstance(value, Mapping) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            normalized = []
            for part in parts[0]:
                if part is None:
                    continue
                try:
                    normalized.append(f"{int(part):02d}")
                except (TypeError, ValueError):
                    continue
            if normalized:
                return "-".join(normalized)
    return ""


def search_crossref(
    client: RateLimitedJsonClient,
    row: Mapping[str, str],
    rows_per_ingredient: int,
) -> tuple[str, int, list[SourcePaper]]:
    query = f'"{preferred_search_term(row)}" skin topical'
    params: dict[str, object] = {
        "query.bibliographic": query,
        "rows": rows_per_ingredient,
        "select": "DOI,title,abstract,published-print,published-online,issued,created,type,container-title,author,URL",
    }
    email = os.getenv("NCBI_EMAIL", "").strip()
    if email:
        params["mailto"] = email
    payload = client.get_json(
        f"https://api.crossref.org/works?{urllib.parse.urlencode(params)}"
    )
    message = payload.get("message") or {}
    papers = []
    for item in message.get("items") or []:
        title_values = item.get("title") or []
        journal_values = item.get("container-title") or []
        authors = []
        for author in item.get("author") or []:
            if not isinstance(author, Mapping):
                continue
            full_name = " ".join(
                value
                for value in (str(author.get("given") or ""), str(author.get("family") or ""))
                if value
            )
            if full_name:
                authors.append(full_name)
        doi = normalize_doi(str(item.get("DOI") or ""))
        papers.append(
            SourcePaper(
                source_id=doi,
                doi=doi,
                title=plain_text(str(title_values[0] if title_values else "")),
                journal=plain_text(str(journal_values[0] if journal_values else "")),
                publication_date=_crossref_date(item),
                publication_types=(str(item.get("type") or ""),),
                authors=tuple(authors),
                abstract=plain_text(str(item.get("abstract") or "")),
                source_url=str(item.get("URL") or (f"https://doi.org/{doi}" if doi else "")),
            )
        )
    return query, int(message.get("total-results") or 0), papers


SEARCHERS: dict[
    str,
    Callable[
        [RateLimitedJsonClient, Mapping[str, str], int],
        tuple[str, int, list[SourcePaper]],
    ],
] = {
    "europe_pmc": search_europe_pmc,
    "openalex": search_openalex,
    "crossref": search_crossref,
}


def paper_row(
    source: str,
    ingredient: Mapping[str, str],
    query: str,
    paper: SourcePaper,
) -> dict[str, object]:
    return {
        "source": source,
        "ingredient_id": ingredient["ingredient_id"],
        "name_ko": ingredient.get("name_ko", ""),
        "name_en": ingredient.get("name_en", ""),
        "product_count": ingredient.get("product_count", "0"),
        "source_id": paper.source_id,
        "pmid": paper.pmid,
        "pmcid": paper.pmcid,
        "doi": paper.doi,
        "title": paper.title,
        "journal": paper.journal,
        "publication_date": paper.publication_date,
        "publication_types": "; ".join(value for value in paper.publication_types if value),
        "authors": "; ".join(value for value in paper.authors if value),
        "abstract": paper.abstract,
        "source_url": paper.source_url,
        "search_query": query,
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
        "pipeline_version": PIPELINE_VERSION,
    }


def run_source_search(
    *,
    source: str,
    targets: Sequence[Mapping[str, str]],
    rows_per_ingredient: int,
    workers: int,
    paper_output: Path,
    log_output: Path,
) -> None:
    intervals = {"europe_pmc": 0.12, "openalex": 0.12, "crossref": 0.08}
    client = RateLimitedJsonClient(min_interval_seconds=intervals[source])
    searcher = SEARCHERS[source]
    paper_rows: list[dict[str, object]] = []
    log_rows: list[dict[str, object]] = []

    def execute(row: Mapping[str, str]):
        try:
            query, raw_count, papers = searcher(client, row, rows_per_ingredient)
            return row, query, raw_count, papers, "ok", ""
        except Exception as exc:  # surfaced in the query log and final failure count
            return row, "", 0, [], "error", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(execute, row) for row in targets]
        for completed, future in enumerate(as_completed(futures), start=1):
            row, query, raw_count, papers, status, error = future.result()
            paper_rows.extend(paper_row(source, row, query, paper) for paper in papers)
            log_rows.append(
                {
                    "source": source,
                    "ingredient_id": row["ingredient_id"],
                    "name_en": row.get("name_en", ""),
                    "search_query": query,
                    "raw_hit_count": raw_count,
                    "returned_count": len(papers),
                    "request_status": status,
                    "error_message": error,
                    "pipeline_version": PIPELINE_VERSION,
                }
            )
            if completed == 1 or completed % 25 == 0 or completed == len(targets):
                print(
                    f"{source} {completed}/{len(targets)} "
                    f"papers={len(paper_rows)} errors={sum(r['request_status'] == 'error' for r in log_rows)}",
                    flush=True,
                )
                write_csv(
                    paper_output,
                    PAPER_FIELDS,
                    sorted(paper_rows, key=lambda item: (str(item["ingredient_id"]), str(item["source_id"]))),
                )
                write_csv(
                    log_output,
                    LOG_FIELDS,
                    sorted(log_rows, key=lambda item: str(item["ingredient_id"])),
                )

    errors = [row for row in log_rows if row["request_status"] == "error"]
    if errors:
        raise RuntimeError(f"{source} search finished with {len(errors)} request errors")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_482.csv"),
    )
    parser.add_argument("--rows-per-ingredient", type=int, default=DEFAULT_ROWS_PER_INGREDIENT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=Path("data/reconciliation"))
    args = parser.parse_args()

    targets = read_csv(args.targets)
    if args.limit:
        targets = targets[: args.limit]
    target_label = str(len(targets))
    run_source_search(
        source=args.source,
        targets=targets,
        rows_per_ingredient=args.rows_per_ingredient,
        workers=args.workers,
        paper_output=args.output_dir / f"ingredient_multisource_{args.source}_{target_label}.csv",
        log_output=(
            args.output_dir
            / f"ingredient_multisource_{args.source}_query_log_{target_label}.csv"
        ),
    )


if __name__ == "__main__":
    main()
