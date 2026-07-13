#!/usr/bin/env python3
"""Run fresh v1.1 ingredient-first searches in three public scholarly APIs.

The collector is discovery-only.  It reads the frozen 466-ingredient review
cohort and the approved ingredient dictionary, writes source-specific candidate
and execution ledgers, and never updates adjudication, runtime scores, or the DB.

Queries contain only approved English ingredient names and skin/topical context
words.  They deliberately contain no efficacy/effect terms and never synthesize
a search term from ``ingredient_id``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
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

from adjudicate_ingredient_evidence_466 import (
    canonical_manifest_sha256,
    load_approved_ingredient_terms,
)
from discover_new_evidence import normalize_doi


PIPELINE_VERSION = "mwbl-ingredient-multisource-discovery-v1.1-fresh"
QUERY_VERSION = "mwbl-ingredient-evidence-query-v1.1"
SOURCES = ("europe_pmc", "crossref", "openalex")
CONTEXT_TERMS = ("skin", "topical")
DEFAULT_ROWS_PER_INGREDIENT = 50

CANDIDATE_FIELDS = [
    "query_id",
    "source",
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "canonical_name_en",
    "result_position",
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
    "metadata_status",
    "metadata_error",
    "source_url",
    "search_query",
    "query_sha256",
    "retrieved_at_utc",
    "searched_at_utc",
    "searched_at",
    "query_contract_status",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
    "manifest_sha256",
]

LOG_FIELDS = [
    "query_id",
    "source",
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "canonical_name_en",
    "approved_search_terms",
    "term_provenance_json",
    "search_query",
    "query_sha256",
    "query_version",
    "started_at_utc",
    "completed_at_utc",
    "total_hit_count",
    "raw_hit_count",
    "retrieval_cap",
    "retrieved_count",
    "returned_count",
    "pagination_status",
    "retrieval_complete",
    "pagination_complete",
    "searched_at",
    "request_status",
    "request_attempt_count",
    "retry_count",
    "error_type",
    "error_message",
    "api_endpoint",
    "sort_order",
    "query_contract_status",
    "rerun_required",
    "http_status",
    "elapsed_ms",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
    "manifest_sha256",
]


@dataclass(frozen=True)
class FetchResult:
    payload: Mapping[str, object]
    http_status: int
    attempt_count: int


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


@dataclass(frozen=True)
class SearchResult:
    query: str
    api_url: str
    total_count: int
    papers: tuple[SourcePaper, ...]
    http_status: int
    attempt_count: int


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_atomic(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _deduplicate_terms(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", value.strip())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        if not normalized.isascii() or not re.search(r"[A-Za-z]", normalized):
            continue
        seen.add(key)
        output.append(normalized)
    return output


def load_targets(
    *,
    cohort_path: Path,
    ingredients_path: Path,
    aliases_path: Path,
) -> tuple[
    list[dict[str, str]],
    dict[str, list[str]],
    dict[str, list[dict[str, str]]],
    str,
]:
    cohort = read_csv(cohort_path)
    cohort.sort(key=lambda row: int(row["ingredient_rank"]))
    ingredient_ids = [row["ingredient_id"] for row in cohort]
    if len(cohort) != 466 or len(set(ingredient_ids)) != 466:
        raise ValueError(
            f"Frozen cohort must contain 466 unique ingredients; got "
            f"rows={len(cohort)} unique={len(set(ingredient_ids))}"
        )

    ingredient_rows = read_csv(ingredients_path)
    alias_rows = read_csv(aliases_path)
    approved = load_approved_ingredient_terms(
        ingredient_rows,
        alias_rows,
        set(ingredient_ids),
    )
    approved = {
        ingredient_id: _deduplicate_terms(values)
        for ingredient_id, values in approved.items()
    }
    missing = [ingredient_id for ingredient_id in ingredient_ids if not approved[ingredient_id]]
    if missing:
        raise ValueError(
            "No approved English search term for frozen cohort ingredient(s): "
            + ", ".join(missing)
        )

    canonical_terms: dict[str, set[str]] = {ingredient_id: set() for ingredient_id in ingredient_ids}
    canonical_sources: dict[tuple[str, str], str] = {}
    for row in ingredient_rows:
        ingredient_id = row.get("ingredient_id", "").strip()
        if ingredient_id not in canonical_terms:
            continue
        for term in row.get("name_en", "").split("|"):
            normalized = re.sub(r"\s+", " ", term.strip())
            if normalized and normalized.isascii() and re.search(r"[A-Za-z]", normalized):
                canonical_terms[ingredient_id].add(normalized.casefold())
                canonical_sources[(ingredient_id, normalized.casefold())] = row.get(
                    "source_url", ""
                ).strip()

    alias_metadata: dict[tuple[str, str], dict[str, str]] = {}
    for row in alias_rows:
        ingredient_id = row.get("canonical_id", "").strip()
        if ingredient_id not in canonical_terms:
            continue
        if row.get("confidence", "").strip().casefold() != "high":
            continue
        alias_type = row.get("alias_type", "").strip().casefold()
        if alias_type not in {"inci", "synonym", "en"}:
            continue
        for alias in row.get("alias", "").split("|"):
            normalized = re.sub(r"\s+", " ", alias.strip())
            if normalized and normalized.isascii() and re.search(r"[A-Za-z]", normalized):
                alias_metadata[(ingredient_id, normalized.casefold())] = {
                    "alias_type": alias_type,
                    "source": row.get("source", "").strip(),
                }

    provenance: dict[str, list[dict[str, str]]] = {}
    for ingredient_id in ingredient_ids:
        rows: list[dict[str, str]] = []
        for term in approved[ingredient_id]:
            key = (ingredient_id, term.casefold())
            if term.casefold() in canonical_terms[ingredient_id]:
                rows.append(
                    {
                        "term": term,
                        "origin": "canonical_name_en",
                        "alias_type": "",
                        "source": canonical_sources.get(key, ""),
                    }
                )
            else:
                metadata = alias_metadata.get(key, {})
                rows.append(
                    {
                        "term": term,
                        "origin": "approved_alias",
                        "alias_type": metadata.get("alias_type", ""),
                        "source": metadata.get("source", ""),
                    }
                )
        provenance[ingredient_id] = rows

    return cohort, approved, provenance, canonical_manifest_sha256(cohort)


class RateLimitedJsonClient:
    def __init__(
        self,
        *,
        min_interval_seconds: float,
        timeout_seconds: float = 45.0,
        max_retries: int = 5,
    ) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def get_json(self, url: str) -> FetchResult:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "mwbl-ingredient-evidence-search/1.1 "
                    "(+https://github.com/mwobareullae/jungle_namanmoo)"
                ),
            },
        )
        for attempt_index in range(self.max_retries + 1):
            self._throttle()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                    if not isinstance(payload, Mapping):
                        raise ValueError("API response was not a JSON object")
                    return FetchResult(payload, int(response.status), attempt_index + 1)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in {408, 425, 429, 500, 502, 503, 504}
                if not retryable or attempt_index >= self.max_retries:
                    raise
                raw_retry_after = (exc.headers.get("Retry-After") or "").strip()
                try:
                    retry_after = float(raw_retry_after)
                except ValueError:
                    retry_after = 0.0
                # A reset-scale Retry-After (OpenAlex can return many hours
                # after daily budget exhaustion) is a hard external block for
                # this run, not a transient retry.  Surface it in the ledger
                # instead of sleeping an unattended worker until the next day.
                if retry_after > 60.0:
                    raise
                time.sleep(max(retry_after, min(30.0, 2.0**attempt_index)))
            except (OSError, ValueError, json.JSONDecodeError):
                if attempt_index >= self.max_retries:
                    raise
                time.sleep(min(30.0, 2.0**attempt_index))
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
            self._last_request_at = time.monotonic()


def _quoted_term_group(terms: Sequence[str]) -> str:
    return " OR ".join(f'"{term.replace(chr(34), " ")}"' for term in terms)


def europe_pmc_query(terms: Sequence[str]) -> str:
    ingredient = " OR ".join(
        f'TITLE_ABS:"{term.replace(chr(34), " ")}"' for term in terms
    )
    context = " OR ".join(f'TITLE_ABS:"{term}"' for term in CONTEXT_TERMS)
    return f"({ingredient}) AND ({context}) AND NOT SRC:MED AND NOT SRC:PAT"


def search_europe_pmc(
    client: RateLimitedJsonClient,
    terms: Sequence[str],
    rows_per_ingredient: int,
) -> SearchResult:
    query = europe_pmc_query(terms)
    params = urllib.parse.urlencode(
        {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": rows_per_ingredient,
        }
    )
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
    fetched = client.get_json(url)
    papers: list[SourcePaper] = []
    result_list = fetched.payload.get("resultList") or {}
    raw_results = result_list.get("result") if isinstance(result_list, Mapping) else []
    for item in raw_results or []:
        if not isinstance(item, Mapping):
            continue
        pub_types = item.get("pubTypeList") or {}
        raw_pub_types = pub_types.get("pubType") if isinstance(pub_types, Mapping) else []
        author_list = item.get("authorList") or {}
        raw_authors = author_list.get("author") if isinstance(author_list, Mapping) else []
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
                    for author in (raw_authors or [])
                    if isinstance(author, Mapping) and author.get("fullName")
                ),
                abstract=plain_text(str(item.get("abstractText") or "")),
                source_url=(
                    f"https://europepmc.org/article/"
                    f"{item.get('source', '')}/{item.get('id', '')}"
                ),
            )
        )
    return SearchResult(
        query=query,
        api_url=url,
        total_count=int(fetched.payload.get("hitCount") or 0),
        papers=tuple(papers),
        http_status=fetched.http_status,
        attempt_count=fetched.attempt_count,
    )


def _crossref_date(item: Mapping[str, object]) -> str:
    for field in ("published-print", "published-online", "issued", "created"):
        value = item.get(field) or {}
        parts = value.get("date-parts") if isinstance(value, Mapping) else None
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
            continue
        normalized: list[str] = []
        for part in parts[0]:
            try:
                normalized.append(f"{int(part):02d}")
            except (TypeError, ValueError):
                continue
        if normalized:
            return "-".join(normalized)
    return ""


def search_crossref(
    client: RateLimitedJsonClient,
    terms: Sequence[str],
    rows_per_ingredient: int,
) -> SearchResult:
    query = f"({_quoted_term_group(terms)}) skin topical"
    params: dict[str, object] = {
        "query.bibliographic": query,
        "rows": rows_per_ingredient,
        "select": (
            "DOI,title,abstract,published-print,published-online,issued,created,"
            "type,container-title,author,URL"
        ),
    }
    email = (os.getenv("CROSSREF_MAILTO") or os.getenv("NCBI_EMAIL") or "").strip()
    if email:
        params["mailto"] = email
    url = f"https://api.crossref.org/works?{urllib.parse.urlencode(params)}"
    fetched = client.get_json(url)
    message = fetched.payload.get("message") or {}
    if not isinstance(message, Mapping):
        raise ValueError("Crossref response omitted message object")
    papers: list[SourcePaper] = []
    for item in message.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        title_values = item.get("title") or []
        journal_values = item.get("container-title") or []
        authors: list[str] = []
        for author in item.get("author") or []:
            if not isinstance(author, Mapping):
                continue
            full_name = " ".join(
                value
                for value in (
                    str(author.get("given") or ""),
                    str(author.get("family") or ""),
                )
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
                source_url=str(
                    item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
                ),
            )
        )
    return SearchResult(
        query=query,
        api_url=url,
        total_count=int(message.get("total-results") or 0),
        papers=tuple(papers),
        http_status=fetched.http_status,
        attempt_count=fetched.attempt_count,
    )


def search_openalex(
    client: RateLimitedJsonClient,
    terms: Sequence[str],
    rows_per_ingredient: int,
) -> SearchResult:
    query = f"({_quoted_term_group(terms)}) skin topical"
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
    url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
    fetched = client.get_json(url)
    papers: list[SourcePaper] = []
    for item in fetched.payload.get("results") or []:
        if not isinstance(item, Mapping):
            continue
        ids = item.get("ids") or {}
        raw_pmid = str(ids.get("pmid") or "") if isinstance(ids, Mapping) else ""
        pmid = raw_pmid.rsplit("/", 1)[-1] if raw_pmid else ""
        primary_location = item.get("primary_location") or {}
        source = (
            primary_location.get("source") or {}
            if isinstance(primary_location, Mapping)
            else {}
        )
        authors: list[str] = []
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
                title=plain_text(
                    str(item.get("title") or item.get("display_name") or "")
                ),
                journal=(
                    plain_text(str(source.get("display_name") or ""))
                    if isinstance(source, Mapping)
                    else ""
                ),
                publication_date=str(item.get("publication_date") or ""),
                publication_types=(str(item.get("type") or ""),),
                authors=tuple(authors),
                abstract=reconstruct_openalex_abstract(
                    item.get("abstract_inverted_index")
                ),
                source_url=str(item.get("id") or ""),
            )
        )
    meta = fetched.payload.get("meta") or {}
    if not isinstance(meta, Mapping):
        raise ValueError("OpenAlex response omitted meta object")
    return SearchResult(
        query=query,
        api_url=url,
        total_count=int(meta.get("count") or 0),
        papers=tuple(papers),
        http_status=fetched.http_status,
        attempt_count=fetched.attempt_count,
    )


SEARCHERS: dict[
    str,
    Callable[
        [RateLimitedJsonClient, Sequence[str], int],
        SearchResult,
    ],
] = {
    "europe_pmc": search_europe_pmc,
    "crossref": search_crossref,
    "openalex": search_openalex,
}


def candidate_row(
    *,
    source: str,
    ingredient: Mapping[str, str],
    canonical_name_en: str,
    result_position: int,
    result: SearchResult,
    paper: SourcePaper,
    retrieved_at: str,
    manifest_sha256: str,
) -> dict[str, object]:
    query_sha256 = text_sha256(result.query)
    query_id = f"{source}:{ingredient['ingredient_id']}:{query_sha256[:16]}"
    return {
        "query_id": query_id,
        "source": source,
        "ingredient_rank": ingredient["ingredient_rank"],
        "ingredient_id": ingredient["ingredient_id"],
        "name_ko": ingredient.get("name_ko", ""),
        "canonical_name_en": canonical_name_en,
        "result_position": result_position,
        "source_id": paper.source_id,
        "pmid": paper.pmid,
        "pmcid": paper.pmcid,
        "doi": paper.doi,
        "title": paper.title,
        "journal": paper.journal,
        "publication_date": paper.publication_date,
        "publication_types": "; ".join(
            value for value in paper.publication_types if value
        ),
        "authors": "; ".join(value for value in paper.authors if value),
        "abstract": paper.abstract,
        "metadata_status": "complete",
        "metadata_error": "",
        "source_url": paper.source_url,
        "search_query": result.query,
        "query_sha256": query_sha256,
        "retrieved_at_utc": retrieved_at,
        "searched_at_utc": retrieved_at,
        "searched_at": retrieved_at,
        "query_contract_status": "approved_terms_only",
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
        "pipeline_version": PIPELINE_VERSION,
        "manifest_sha256": manifest_sha256,
    }


def output_paths(output_dir: Path, source: str) -> tuple[Path, Path, Path]:
    return (
        output_dir / f"{source}_candidates_466_v1_1_fresh.csv",
        output_dir / f"{source}_query_log_466_v1_1_fresh.csv",
        output_dir / f"{source}_search_summary_466_v1_1_fresh.json",
    )


def _load_resume_rows(
    candidate_path: Path,
    log_path: Path,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    candidates = read_csv(candidate_path) if candidate_path.exists() else []
    logs = read_csv(log_path) if log_path.exists() else []
    return candidates, {row["ingredient_id"]: row for row in logs}


def _sorted_candidates(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            int(str(row["ingredient_rank"])),
            int(str(row["result_position"])),
            str(row["source_id"]),
        ),
    )


def _sorted_logs(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(rows, key=lambda row: int(str(row["ingredient_rank"])))


def run_source(
    *,
    source: str,
    targets: Sequence[Mapping[str, str]],
    approved_terms: Mapping[str, Sequence[str]],
    term_provenance: Mapping[str, Sequence[Mapping[str, str]]],
    manifest_sha256: str,
    rows_per_ingredient: int,
    workers: int,
    output_dir: Path,
    resume: bool,
) -> dict[str, object]:
    candidate_path, log_path, summary_path = output_paths(output_dir, source)
    existing_candidates, existing_logs = (
        _load_resume_rows(candidate_path, log_path) if resume else ([], {})
    )
    for row in existing_logs.values():
        if not row.get("rerun_required"):
            row["rerun_required"] = (
                "N"
                if row.get("request_status") in {"success", "access_unavailable"}
                else "Y"
            )
        ingredient_id = row.get("ingredient_id", "")
        if ingredient_id in approved_terms:
            row["canonical_name_en"] = approved_terms[ingredient_id][0]
            row["approved_search_terms"] = "|".join(approved_terms[ingredient_id])
            row["term_provenance_json"] = json.dumps(
                list(term_provenance[ingredient_id]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
    completed_ids = {
        ingredient_id
        for ingredient_id, row in existing_logs.items()
        if row.get("request_status") in {"success", "access_unavailable"}
        and row.get("rerun_required", "N") == "N"
        and row.get("pipeline_version") == PIPELINE_VERSION
        and row.get("manifest_sha256") == manifest_sha256
        and int(row.get("retrieval_cap") or 0) == rows_per_ingredient
    }
    candidate_rows: list[dict[str, object]] = [
        dict(row)
        for row in existing_candidates
        if row.get("ingredient_id") in completed_ids
    ]
    for row in candidate_rows:
        ingredient_id = str(row.get("ingredient_id", ""))
        if ingredient_id in approved_terms:
            row["canonical_name_en"] = approved_terms[ingredient_id][0]
    log_by_id: dict[str, dict[str, object]] = {
        ingredient_id: dict(row)
        for ingredient_id, row in existing_logs.items()
        if ingredient_id in completed_ids
    }
    pending = [row for row in targets if row["ingredient_id"] not in completed_ids]

    intervals = {"europe_pmc": 0.13, "crossref": 0.13, "openalex": 0.13}
    client = RateLimitedJsonClient(min_interval_seconds=intervals[source])
    searcher = SEARCHERS[source]
    started_at = utc_now()

    def execute(row: Mapping[str, str]) -> tuple[
        Mapping[str, str],
        Sequence[str],
        SearchResult | None,
        str,
        int,
        str,
        str,
    ]:
        terms = approved_terms[row["ingredient_id"]]
        started = time.monotonic()
        searched_at = utc_now()
        try:
            result = searcher(client, terms, rows_per_ingredient)
            return (
                row,
                terms,
                result,
                searched_at,
                round((time.monotonic() - started) * 1000),
                "",
                "",
            )
        except Exception as exc:  # exception details are preserved in the ledger
            if (
                source == "openalex"
                and isinstance(exc, urllib.error.HTTPError)
                and exc.code == 429
            ):
                retry_after = (exc.headers.get("Retry-After") or "").strip()
                error_type = "HTTPError_429_access_unavailable"
                error_message = (
                    "OpenAlex HTTP 429 daily budget/access limit; "
                    f"Retry-After={retry_after or 'not_reported'}"
                )
            else:
                error_type = type(exc).__name__
                error_message = str(exc)
            return (
                row,
                terms,
                None,
                searched_at,
                round((time.monotonic() - started) * 1000),
                error_type,
                error_message,
            )

    # OpenAlex assigns an unauthenticated daily search budget at the source
    # level.  One real HTTP 429 with a reset-scale Retry-After establishes that
    # all remaining same-credential requests are unavailable until conditions
    # change.  Record that source-level fact for every pending cohort member
    # without issuing hundreds of knowingly rejected calls.
    if source == "openalex" and pending:
        preflight = execute(pending[0])
        if preflight[5] == "HTTPError_429_access_unavailable":
            evidence_at = utc_now()
            evidence_message = preflight[6]
            first_pending_id = pending[0]["ingredient_id"]
            for row in pending:
                ingredient_id = row["ingredient_id"]
                terms = approved_terms[ingredient_id]
                query = f"({_quoted_term_group(terms)}) skin topical"
                query_sha256 = text_sha256(query)
                provenance_json = json.dumps(
                    list(term_provenance[ingredient_id]),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                attempted = ingredient_id == first_pending_id
                log_by_id[ingredient_id] = {
                    "query_id": f"{source}:{ingredient_id}:{query_sha256[:16]}",
                    "source": source,
                    "ingredient_rank": row["ingredient_rank"],
                    "ingredient_id": ingredient_id,
                    "name_ko": row.get("name_ko", ""),
                    "canonical_name_en": terms[0],
                    "approved_search_terms": "|".join(terms),
                    "term_provenance_json": provenance_json,
                    "search_query": query,
                    "query_sha256": query_sha256,
                    "query_version": QUERY_VERSION,
                    "started_at_utc": preflight[3] if attempted else evidence_at,
                    "completed_at_utc": evidence_at,
                    "total_hit_count": 0,
                    "raw_hit_count": 0,
                    "retrieval_cap": rows_per_ingredient,
                    "retrieved_count": 0,
                    "returned_count": 0,
                    "pagination_status": "not_applicable",
                    "retrieval_complete": "N",
                    "pagination_complete": "N",
                    "searched_at": evidence_at,
                    "request_status": "access_unavailable",
                    "request_attempt_count": 1 if attempted else 0,
                    "retry_count": 0,
                    "error_type": "HTTPError_429_access_unavailable",
                    "error_message": (
                        evidence_message
                        if attempted
                        else "Not attempted: source-level OpenAlex HTTP 429 access "
                        "condition established by the first pending request in this run"
                    ),
                    "api_endpoint": "https://api.openalex.org/works",
                    "sort_order": "relevance",
                    "query_contract_status": "approved_terms_only",
                    "rerun_required": "N",
                    "http_status": 429 if attempted else "",
                    "elapsed_ms": preflight[4] if attempted else 0,
                    "review_status": "candidate_unverified",
                    "runtime_score_change": "none",
                    "pipeline_version": PIPELINE_VERSION,
                    "manifest_sha256": manifest_sha256,
                }
            print(
                f"openalex access unavailable: preserved {len(completed_ids)} "
                f"successful queries and recorded {len(pending)} pending rows",
                flush=True,
            )
            pending = []

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(execute, row) for row in pending]
            for completed, future in enumerate(as_completed(futures), start=1):
                row, terms, result, searched_at, elapsed_ms, error_type, error = (
                    future.result()
                )
                ingredient_id = row["ingredient_id"]
                approved_joined = "|".join(terms)
                provenance_json = json.dumps(
                    list(term_provenance[ingredient_id]),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                candidate_rows = [
                    candidate
                    for candidate in candidate_rows
                    if candidate.get("ingredient_id") != ingredient_id
                ]
                if result is None:
                    access_unavailable = (
                        source == "openalex"
                        and error_type == "HTTPError_429_access_unavailable"
                    )
                    query = (
                        europe_pmc_query(terms)
                        if source == "europe_pmc"
                        else f"({_quoted_term_group(terms)}) skin topical"
                    )
                    query_sha256 = text_sha256(query)
                    completed_at = utc_now()
                    log_by_id[ingredient_id] = {
                        "query_id": f"{source}:{ingredient_id}:{query_sha256[:16]}",
                        "source": source,
                        "ingredient_rank": row["ingredient_rank"],
                        "ingredient_id": ingredient_id,
                        "name_ko": row.get("name_ko", ""),
                        "canonical_name_en": terms[0],
                        "approved_search_terms": approved_joined,
                        "term_provenance_json": provenance_json,
                        "search_query": query,
                        "query_sha256": query_sha256,
                        "query_version": QUERY_VERSION,
                        "started_at_utc": searched_at,
                        "completed_at_utc": completed_at,
                        "total_hit_count": 0,
                        "raw_hit_count": 0,
                        "retrieval_cap": rows_per_ingredient,
                        "retrieved_count": 0,
                        "returned_count": 0,
                        "pagination_status": (
                            "not_applicable" if access_unavailable else "failed"
                        ),
                        "retrieval_complete": "N",
                        "pagination_complete": "N",
                        "searched_at": completed_at,
                        "request_status": (
                            "access_unavailable" if access_unavailable else "error"
                        ),
                        "request_attempt_count": 0,
                        "retry_count": 0,
                        "error_type": error_type,
                        "error_message": error,
                        "api_endpoint": "",
                        "sort_order": "relevance",
                        "query_contract_status": "approved_terms_only",
                        "rerun_required": "N" if access_unavailable else "Y",
                        "http_status": 429 if access_unavailable else "",
                        "elapsed_ms": elapsed_ms,
                        "review_status": "candidate_unverified",
                        "runtime_score_change": "none",
                        "pipeline_version": PIPELINE_VERSION,
                        "manifest_sha256": manifest_sha256,
                    }
                else:
                    retrieved_at = utc_now()
                    for result_position, paper in enumerate(result.papers, start=1):
                        candidate_rows.append(
                            candidate_row(
                                source=source,
                                ingredient=row,
                                canonical_name_en=terms[0],
                                result_position=result_position,
                                result=result,
                                paper=paper,
                                retrieved_at=retrieved_at,
                                manifest_sha256=manifest_sha256,
                            )
                        )
                    returned_count = len(result.papers)
                    pagination_complete = result.total_count <= returned_count
                    pagination_status = (
                        "complete" if pagination_complete else "capped_at_retrieval_limit"
                    )
                    query_sha256 = text_sha256(result.query)
                    log_by_id[ingredient_id] = {
                        "query_id": f"{source}:{ingredient_id}:{query_sha256[:16]}",
                        "source": source,
                        "ingredient_rank": row["ingredient_rank"],
                        "ingredient_id": ingredient_id,
                        "name_ko": row.get("name_ko", ""),
                        "canonical_name_en": terms[0],
                        "approved_search_terms": approved_joined,
                        "term_provenance_json": provenance_json,
                        "search_query": result.query,
                        "query_sha256": query_sha256,
                        "query_version": QUERY_VERSION,
                        "started_at_utc": searched_at,
                        "completed_at_utc": retrieved_at,
                        "total_hit_count": result.total_count,
                        "raw_hit_count": result.total_count,
                        "retrieval_cap": rows_per_ingredient,
                        "retrieved_count": returned_count,
                        "returned_count": returned_count,
                        "pagination_status": pagination_status,
                        "retrieval_complete": "Y" if pagination_complete else "N",
                        "pagination_complete": "Y" if pagination_complete else "N",
                        "searched_at": retrieved_at,
                        "request_status": "success",
                        "request_attempt_count": result.attempt_count,
                        "retry_count": max(0, result.attempt_count - 1),
                        "error_type": "",
                        "error_message": "",
                        "api_endpoint": result.api_url.split("?", 1)[0],
                        "sort_order": "relevance",
                        "query_contract_status": "approved_terms_only",
                        "rerun_required": "N",
                        "http_status": result.http_status,
                        "elapsed_ms": elapsed_ms,
                        "review_status": "candidate_unverified",
                        "runtime_score_change": "none",
                        "pipeline_version": PIPELINE_VERSION,
                        "manifest_sha256": manifest_sha256,
                    }

                if completed == 1 or completed % 10 == 0 or completed == len(pending):
                    sorted_candidates = _sorted_candidates(candidate_rows)
                    sorted_logs = _sorted_logs(list(log_by_id.values()))
                    write_csv_atomic(candidate_path, CANDIDATE_FIELDS, sorted_candidates)
                    write_csv_atomic(log_path, LOG_FIELDS, sorted_logs)
                    errors = sum(row_["request_status"] == "error" for row_ in sorted_logs)
                    print(
                        f"{source} {len(completed_ids) + completed}/{len(targets)} "
                        f"candidates={len(sorted_candidates)} errors={errors}",
                        flush=True,
                    )

    sorted_candidates = _sorted_candidates(candidate_rows)
    sorted_logs = _sorted_logs(list(log_by_id.values()))
    write_csv_atomic(candidate_path, CANDIDATE_FIELDS, sorted_candidates)
    write_csv_atomic(log_path, LOG_FIELDS, sorted_logs)
    error_rows = [row for row in sorted_logs if row["request_status"] == "error"]
    access_unavailable_rows = [
        row for row in sorted_logs if row["request_status"] == "access_unavailable"
    ]
    if len(sorted_logs) != 466 or error_rows:
        source_status = "incomplete"
    elif access_unavailable_rows:
        source_status = "partial_access_unavailable"
    else:
        source_status = "complete"
    summary: dict[str, object] = {
        "source": source,
        "pipeline_version": PIPELINE_VERSION,
        "source_status": source_status,
        "started_at_utc": min(
            (str(row["started_at_utc"]) for row in sorted_logs),
            default=started_at,
        ),
        "completed_at_utc": max(
            (str(row["completed_at_utc"]) for row in sorted_logs),
            default=utc_now(),
        ),
        "cohort_size": len(targets),
        "logged_ingredient_count": len(sorted_logs),
        "successful_ingredient_count": sum(
            row["request_status"] == "success" for row in sorted_logs
        ),
        "error_ingredient_count": len(error_rows),
        "access_unavailable_ingredient_count": len(access_unavailable_rows),
        "ingredients_with_candidates": len(
            {str(row["ingredient_id"]) for row in sorted_candidates}
        ),
        "candidate_row_count": len(sorted_candidates),
        "reported_source_total_sum": sum(
            int(str(row["total_hit_count"])) for row in sorted_logs
        ),
        "pagination_complete_count": sum(
            row["pagination_complete"] == "Y" for row in sorted_logs
        ),
        "retrieval_cap_reached_count": sum(
            row["pagination_status"] == "capped_at_retrieval_limit"
            for row in sorted_logs
        ),
        "retrieval_cap_per_ingredient": rows_per_ingredient,
        "effect_terms_used": [],
        "context_terms": list(CONTEXT_TERMS),
        "term_policy": (
            "canonical names plus high-confidence approved English "
            "INCI/synonym/en aliases; no ingredient_id fallback"
        ),
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
        "manifest_sha256": manifest_sha256,
        "candidate_file": candidate_path.name,
        "candidate_file_sha256": file_sha256(candidate_path),
        "search_log_file": log_path.name,
        "search_log_file_sha256": file_sha256(log_path),
        "errors": [
            {
                "ingredient_id": row["ingredient_id"],
                "error_type": row["error_type"],
                "error_message": row["error_message"],
            }
            for row in error_rows
        ],
    }
    write_json_atomic(summary_path, summary)
    return summary


def validate_source_outputs(
    *,
    source: str,
    output_dir: Path,
    manifest_sha256: str,
    rows_per_ingredient: int,
) -> dict[str, object]:
    candidate_path, log_path, summary_path = output_paths(output_dir, source)
    logs = read_csv(log_path)
    candidates = read_csv(candidate_path)
    errors: list[str] = []
    if len(logs) != 466:
        errors.append(f"expected 466 log rows, got {len(logs)}")
    ids = [row.get("ingredient_id", "") for row in logs]
    if len(set(ids)) != len(ids):
        errors.append("duplicate ingredient_id in search log")
    if {row.get("source") for row in logs} != {source}:
        errors.append("unexpected source value in search log")
    if any(row.get("manifest_sha256") != manifest_sha256 for row in logs):
        errors.append("manifest_sha256 mismatch in search log")
    if any(row.get("pipeline_version") != PIPELINE_VERSION for row in logs):
        errors.append("pipeline_version mismatch in search log")
    if any(int(row.get("retrieval_cap") or 0) != rows_per_ingredient for row in logs):
        errors.append("retrieval_cap mismatch in search log")
    allowed_statuses = (
        {"success", "access_unavailable"} if source == "openalex" else {"success"}
    )
    if any(row.get("request_status") not in allowed_statuses for row in logs):
        errors.append("one or more source requests have an invalid/incomplete status")
    if any(
        row.get("request_status") == "error" and row.get("rerun_required") != "Y"
        for row in logs
    ):
        errors.append("error row must have rerun_required=Y")
    if any(
        row.get("request_status") in {"success", "access_unavailable"}
        and row.get("rerun_required") != "N"
        for row in logs
    ):
        errors.append("settled row must have rerun_required=N")
    if source == "openalex" and any(
        row.get("request_status") == "access_unavailable"
        and row.get("pagination_status") != "not_applicable"
        for row in logs
    ):
        errors.append("OpenAlex access_unavailable row must use pagination_status=not_applicable")
    returned_sum = sum(int(row.get("returned_count") or 0) for row in logs)
    if returned_sum != len(candidates):
        errors.append(
            f"candidate row count {len(candidates)} != returned_count sum {returned_sum}"
        )
    valid_ids = set(ids)
    if any(row.get("ingredient_id") not in valid_ids for row in candidates):
        errors.append("candidate row has ingredient_id outside frozen cohort")
    if any(row.get("review_status") != "candidate_unverified" for row in candidates):
        errors.append("candidate review_status is not candidate_unverified")
    if any(row.get("runtime_score_change") != "none" for row in candidates):
        errors.append("candidate runtime_score_change is not none")
    if not summary_path.exists():
        errors.append("summary file missing")
    result = {
        "source": source,
        "valid": not errors,
        "log_rows": len(logs),
        "candidate_rows": len(candidates),
        "successful_queries": sum(row.get("request_status") == "success" for row in logs),
        "access_unavailable_queries": sum(
            row.get("request_status") == "access_unavailable" for row in logs
        ),
        "pagination_complete": sum(row.get("pagination_complete") == "Y" for row in logs),
        "cap_reached": sum(
            row.get("pagination_status") == "capped_at_retrieval_limit" for row in logs
        ),
        "errors": errors,
    }
    if errors:
        raise ValueError(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=(*SOURCES, "all"), default="all")
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466_v1_1.csv"),
    )
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("data/ingredient_aliases.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reconciliation/v1_1_fresh"),
    )
    parser.add_argument(
        "--rows-per-ingredient",
        type=int,
        default=DEFAULT_ROWS_PER_INGREDIENT,
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.rows_per_ingredient <= 100:
        raise ValueError("--rows-per-ingredient must be between 1 and 100")
    targets, approved_terms, term_provenance, manifest_sha256 = load_targets(
        cohort_path=args.cohort,
        ingredients_path=args.ingredients,
        aliases_path=args.aliases,
    )
    selected_sources = SOURCES if args.source == "all" else (args.source,)

    if args.validate_only:
        validations = [
            validate_source_outputs(
                source=source,
                output_dir=args.output_dir,
                manifest_sha256=manifest_sha256,
                rows_per_ingredient=args.rows_per_ingredient,
            )
            for source in selected_sources
        ]
        print(json.dumps(validations, ensure_ascii=False, indent=2))
        return

    summaries: list[dict[str, object]] = []
    if len(selected_sources) == 1:
        summaries.append(
            run_source(
                source=selected_sources[0],
                targets=targets,
                approved_terms=approved_terms,
                term_provenance=term_provenance,
                manifest_sha256=manifest_sha256,
                rows_per_ingredient=args.rows_per_ingredient,
                workers=args.workers,
                output_dir=args.output_dir,
                resume=not args.no_resume,
            )
        )
    else:
        with ThreadPoolExecutor(max_workers=len(selected_sources)) as executor:
            future_by_source = {
                executor.submit(
                    run_source,
                    source=source,
                    targets=targets,
                    approved_terms=approved_terms,
                    term_provenance=term_provenance,
                    manifest_sha256=manifest_sha256,
                    rows_per_ingredient=args.rows_per_ingredient,
                    workers=args.workers,
                    output_dir=args.output_dir,
                    resume=not args.no_resume,
                ): source
                for source in selected_sources
            }
            for future in as_completed(future_by_source):
                summaries.append(future.result())

    validations = [
        validate_source_outputs(
            source=source,
            output_dir=args.output_dir,
            manifest_sha256=manifest_sha256,
            rows_per_ingredient=args.rows_per_ingredient,
        )
        for source in selected_sources
    ]
    print(
        json.dumps(
            {"summaries": summaries, "validations": validations},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
