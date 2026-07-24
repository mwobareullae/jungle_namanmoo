#!/usr/bin/env python3
"""Run the filter-contract v1.1 ingredient-first PubMed search.

The collector is deliberately source-specific and discovery-only.  It searches
the frozen 466-ingredient v1 cohort with canonical English names plus reviewed,
high-confidence English aliases.  It never derives a search term from an
``ingredient_id`` and never adds an efficacy/outcome term to a query.

Outputs are review candidates and provenance logs only.  Runtime evidence,
scores, databases, and the frozen v1 files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PIPELINE_VERSION = "mwbl-ingredient-evidence-filter-v1.1-fresh-pubmed"
QUERY_VERSION = "mwbl-pubmed-ingredient-skin-context-v1.1"
NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_TOOL = "mwbl_filter_v1_1_pubmed"
DEFAULT_RETMAX = 100
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_NO_KEY_INTERVAL_SECONDS = 0.36
DEFAULT_API_KEY_INTERVAL_SECONDS = 0.11
FETCH_BATCH_SIZE = 100

ALLOWED_ALIAS_TYPES = frozenset({"inci", "synonym", "en"})
SKIN_CONTEXT_TERMS: tuple[str, ...] = (
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

QUERY_LOG_FIELDS: tuple[str, ...] = (
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
    "review_status",
    "runtime_score_change",
    "pipeline_version",
)

CANDIDATE_FIELDS: tuple[str, ...] = (
    "query_id",
    "source",
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "canonical_name_en",
    "result_position",
    "pmid",
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
    "searched_at_utc",
    "searched_at",
    "query_contract_status",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
)


class PubMedSearchError(RuntimeError):
    """Raised for invalid inputs or exhausted PubMed requests."""


@dataclass(frozen=True)
class TermProvenance:
    term: str
    origin: str
    alias_type: str = ""
    source: str = ""


@dataclass(frozen=True)
class PubMedPaper:
    pmid: str
    doi: str = ""
    title: str = ""
    journal: str = ""
    publication_date: str = ""
    publication_types: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    abstract: str = ""


@dataclass(frozen=True)
class RequestResult:
    payload: bytes
    attempt_count: int
    retry_count: int


class RateLimitedPubMedClient:
    def __init__(
        self,
        *,
        email: str = "",
        api_key: str = "",
        tool: str = DEFAULT_TOOL,
        request_interval_seconds: float | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.email = email.strip()
        self.api_key = api_key.strip()
        self.tool = tool.strip() or DEFAULT_TOOL
        safe_floor = (
            DEFAULT_API_KEY_INTERVAL_SECONDS
            if self.api_key
            else DEFAULT_NO_KEY_INTERVAL_SECONDS
        )
        requested_interval = (
            safe_floor
            if request_interval_seconds is None
            else max(0.0, request_interval_seconds)
        )
        self.request_interval_seconds = max(safe_floor, requested_interval)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.opener = opener or urllib.request.build_opener()
        self.request_count = 0
        self.retry_count = 0
        self._last_request_at = 0.0

    def search(self, query: str, retmax: int) -> tuple[int, list[str], RequestResult]:
        result = self._request(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retstart": "0",
                "retmax": str(retmax),
                "sort": "relevance",
            },
        )
        try:
            decoded = json.loads(result.payload.decode("utf-8"))
            search_result = decoded["esearchresult"]
            total_count = int(search_result["count"])
            pmids = stable_unique(
                str(value) for value in search_result["idlist"] if str(value).isdigit()
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PubMedSearchError("PubMed ESearch returned an unexpected response") from exc
        return total_count, pmids, result

    def fetch(self, pmids: Sequence[str]) -> tuple[dict[str, PubMedPaper], RequestResult]:
        unique_pmids = stable_unique(pmid for pmid in pmids if pmid.isdigit())
        if not unique_pmids:
            return {}, RequestResult(payload=b"", attempt_count=0, retry_count=0)
        result = self._request(
            "efetch.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(unique_pmids),
                "retmode": "xml",
            },
        )
        return parse_pubmed_xml(result.payload), result

    def _request(self, endpoint: str, params: Mapping[str, str]) -> RequestResult:
        request_params = dict(params)
        request_params["tool"] = self.tool
        if self.email:
            request_params["email"] = self.email
        if self.api_key:
            request_params["api_key"] = self.api_key
        url = f"{NCBI_EUTILS_BASE_URL}/{endpoint}?{urllib.parse.urlencode(request_params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, application/xml;q=0.9, */*;q=0.8",
                "User-Agent": f"{self.tool}/1.1",
            },
        )

        attempts = 0
        retries = 0
        for attempt_index in range(self.max_retries + 1):
            self._throttle()
            attempts += 1
            self.request_count += 1
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return RequestResult(
                        payload=response.read(),
                        attempt_count=attempts,
                        retry_count=retries,
                    )
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt_index >= self.max_retries:
                    raise PubMedSearchError(
                        f"PubMed {endpoint} failed with HTTP {exc.code} after {attempts} attempt(s)"
                    ) from exc
                retry_after = parse_retry_after(exc.headers.get("Retry-After"))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt_index >= self.max_retries:
                    raise PubMedSearchError(
                        f"PubMed {endpoint} failed after {attempts} attempt(s): {type(exc).__name__}"
                    ) from exc
                retry_after = 0.0

            retries += 1
            self.retry_count += 1
            time.sleep(max(retry_after, min(32.0, 2.0**attempt_index)))

        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        remaining = self.request_interval_seconds - (
            time.monotonic() - self._last_request_at
        )
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def stable_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])


def is_approved_english_term(value: str) -> bool:
    value = value.strip()
    return value.isascii() and bool(re.search(r"[A-Za-z]", value)) and len(value) >= 2


def split_canonical_name(name_en: str) -> list[str]:
    return [
        value
        for value in (part.strip() for part in name_en.split("|"))
        if is_approved_english_term(value)
    ]


def build_approved_terms(
    ingredient_ids: set[str],
    ingredient_rows: Sequence[Mapping[str, str]],
    alias_rows: Sequence[Mapping[str, str]],
) -> dict[str, list[TermProvenance]]:
    """Return only canonical and reviewed high-confidence English terms.

    There is intentionally no ``ingredient_id.replace('_', ' ')`` fallback.
    Missing approved terms are fatal so a broad synthetic query can never be
    issued silently.
    """

    by_id: dict[str, list[TermProvenance]] = {value: [] for value in ingredient_ids}
    ingredient_seen: set[str] = set()
    for row in ingredient_rows:
        ingredient_id = row.get("ingredient_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        ingredient_seen.add(ingredient_id)
        for term in split_canonical_name(row.get("name_en", "")):
            by_id[ingredient_id].append(
                TermProvenance(
                    term=term,
                    origin="canonical_name_en",
                    source=row.get("source_url", "").strip(),
                )
            )

    missing_master = sorted(ingredient_ids - ingredient_seen)
    if missing_master:
        raise PubMedSearchError(
            "Frozen cohort ingredient IDs missing from data/ingredients.csv: "
            + "|".join(missing_master)
        )

    for row in alias_rows:
        ingredient_id = row.get("canonical_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        confidence = row.get("confidence", "").strip().casefold()
        alias_type = row.get("alias_type", "").strip().casefold()
        if confidence != "high" or alias_type not in ALLOWED_ALIAS_TYPES:
            continue
        # The reviewed alias contract uses a pipe as its explicit alternative-
        # name delimiter.  Each alternative is an independently approved exact
        # term; the literal pipe-joined string is never a PubMed search term.
        for alias in row.get("alias", "").split("|"):
            alias = alias.strip()
            if not is_approved_english_term(alias):
                continue
            by_id[ingredient_id].append(
                TermProvenance(
                    term=alias,
                    origin="approved_alias",
                    alias_type=alias_type,
                    source=row.get("source", "").strip(),
                )
            )

    result: dict[str, list[TermProvenance]] = {}
    for ingredient_id, values in by_id.items():
        seen: set[str] = set()
        selected: list[TermProvenance] = []
        for value in values:
            key = value.term.casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(value)
        if not selected:
            raise PubMedSearchError(
                f"No canonical or approved high-confidence English term: {ingredient_id}"
            )
        result[ingredient_id] = selected
    return result


def pubmed_title_abstract_term(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.replace('"', " ")).strip()
    if not cleaned:
        raise PubMedSearchError("Empty PubMed Title/Abstract term")
    return f'"{cleaned}"[Title/Abstract]'


def build_query(terms: Sequence[str]) -> str:
    if not terms:
        raise PubMedSearchError("At least one approved ingredient term is required")
    ingredient_clause = " OR ".join(pubmed_title_abstract_term(term) for term in terms)
    context_clause = " OR ".join(
        pubmed_title_abstract_term(term) for term in SKIN_CONTEXT_TERMS
    )
    return f"({ingredient_clause}) AND ({context_clause})"


def pagination_status(total_hit_count: int, retrieved_count: int, cap: int) -> tuple[str, str]:
    if retrieved_count < min(total_hit_count, cap):
        return "incomplete_response", "N"
    if total_hit_count > cap:
        return "capped_at_retrieval_limit", "N"
    return "complete", "Y"


def parse_retry_after(raw_value: str | None) -> float:
    try:
        return max(0.0, float(raw_value or 0.0))
    except ValueError:
        return 0.0


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def parse_pubmed_date(article: ET.Element) -> str:
    for path in (
        ".//ArticleDate",
        ".//JournalIssue/PubDate",
        ".//Book/PubDate",
        ".//PubMedPubDate[@PubStatus='pubmed']",
        ".//PubMedPubDate[@PubStatus='entrez']",
    ):
        node = article.find(path)
        if node is None:
            continue
        medline = element_text(node.find("MedlineDate"))
        if medline:
            return medline
        year = element_text(node.find("Year"))
        month = element_text(node.find("Month"))
        day = element_text(node.find("Day"))
        parts = [value for value in (year, month, day) if value]
        if parts:
            return "-".join(parts)
    return ""


def parse_pubmed_xml(payload: bytes) -> dict[str, PubMedPaper]:
    if not payload:
        return {}
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PubMedSearchError("PubMed EFetch returned invalid XML") from exc

    papers: dict[str, PubMedPaper] = {}
    records = list(root.findall(".//PubmedArticle")) + list(
        root.findall(".//PubmedBookArticle")
    )
    for record in records:
        is_book = record.tag == "PubmedBookArticle"
        pmid = element_text(record.find(".//MedlineCitation/PMID"))
        if is_book:
            pmid = element_text(record.find(".//BookDocument/PMID"))
        if not pmid:
            continue
        doi = ""
        article_id_path = (
            ".//BookDocument/ArticleIdList/ArticleId"
            if is_book
            else ".//PubmedData/ArticleIdList/ArticleId"
        )
        for article_id in record.findall(article_id_path):
            if article_id.attrib.get("IdType", "").casefold() == "doi":
                doi = element_text(article_id).casefold()
                break
        article = (
            record.find(".//BookDocument")
            if is_book
            else record.find(".//MedlineCitation/Article")
        )
        if article is None:
            article = record
        if is_book:
            # PubmedBookArticle entries may represent whole books and therefore
            # have no BookDocument/ArticleTitle.  BookTitle is the stable NLM
            # bibliographic title; CollectionTitle (or publisher) is the
            # closest journal/container analogue.
            title = element_text(article.find(".//Book/BookTitle"))
            journal = element_text(article.find(".//Book/CollectionTitle"))
            if not journal:
                journal = element_text(article.find(".//Book/Publisher/PublisherName"))
        else:
            title = element_text(article.find("ArticleTitle"))
            journal = element_text(article.find(".//Journal/Title"))
        publication_types = tuple(
            stable_unique(
                element_text(node)
                for node in (
                    article.findall("./PublicationType")
                    if is_book
                    else article.findall(".//PublicationTypeList/PublicationType")
                )
            )
        )
        authors: list[str] = []
        author_nodes = (
            article.findall("./AuthorList[@Type='authors']/Author")
            if is_book
            else article.findall(".//AuthorList/Author")
        )
        for author in author_nodes:
            collective = element_text(author.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            last_name = element_text(author.find("LastName"))
            initials = element_text(author.find("Initials"))
            full_name = " ".join(value for value in (last_name, initials) if value)
            if full_name:
                authors.append(full_name)
        abstract = " ".join(
            element_text(node) for node in article.findall(".//Abstract/AbstractText")
        ).strip()
        papers[pmid] = PubMedPaper(
            pmid=pmid,
            doi=doi,
            title=title,
            journal=journal,
            publication_date=parse_pubmed_date(record),
            publication_types=publication_types,
            authors=tuple(stable_unique(authors)),
            abstract=abstract,
        )
    return papers


def validate_frozen_cohort(rows: Sequence[Mapping[str, str]]) -> None:
    if len(rows) != 466:
        raise PubMedSearchError(f"Frozen v1 cohort must contain 466 rows, found {len(rows)}")
    ingredient_ids = [row.get("ingredient_id", "").strip() for row in rows]
    if not all(ingredient_ids) or len(set(ingredient_ids)) != 466:
        raise PubMedSearchError("Frozen v1 cohort ingredient_id values must be nonblank and unique")


def query_row_base(
    cohort_row: Mapping[str, str],
    terms: Sequence[TermProvenance],
) -> dict[str, object]:
    query = build_query([value.term for value in terms])
    query_sha = text_sha256(query)
    ingredient_id = cohort_row.get("ingredient_id", "").strip()
    return {
        "query_id": f"pubmed:{ingredient_id}:{query_sha[:16]}",
        "source": "pubmed",
        "ingredient_rank": cohort_row.get("ingredient_rank", "").strip(),
        "ingredient_id": ingredient_id,
        "name_ko": cohort_row.get("name_ko", "").strip(),
        "canonical_name_en": terms[0].term,
        "approved_search_terms": "|".join(value.term for value in terms),
        "term_provenance_json": json.dumps(
            [value.__dict__ for value in terms],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "search_query": query,
        "query_sha256": query_sha,
        "query_version": QUERY_VERSION,
    }


def run_search(
    *,
    cohort_rows: Sequence[Mapping[str, str]],
    terms_by_id: Mapping[str, Sequence[TermProvenance]],
    client: RateLimitedPubMedClient,
    retmax: int,
    checkpoint_log: Path,
) -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    query_rows: list[dict[str, object]] = []
    hit_map: dict[str, list[str]] = {}
    for index, cohort_row in enumerate(cohort_rows, start=1):
        ingredient_id = cohort_row.get("ingredient_id", "").strip()
        base = query_row_base(cohort_row, terms_by_id[ingredient_id])
        started_at = utc_now()
        before_requests = client.request_count
        before_retries = client.retry_count
        try:
            total_count, pmids, result = client.search(str(base["search_query"]), retmax)
            page_status, retrieval_complete = pagination_status(
                total_count, len(pmids), retmax
            )
            request_status = "success"
            error_type = ""
            error_message = ""
            attempt_count = result.attempt_count
            retry_count = result.retry_count
            hit_map[ingredient_id] = pmids
        except Exception as exc:  # continue so every ingredient gets a provenance row
            total_count = 0
            pmids = []
            page_status = "failed"
            retrieval_complete = "N"
            request_status = "error"
            error_type = type(exc).__name__
            error_message = str(exc)[:1000]
            attempt_count = client.request_count - before_requests
            retry_count = client.retry_count - before_retries
            hit_map[ingredient_id] = []
        completed_at = utc_now()
        row = {
            **base,
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "total_hit_count": total_count,
            "raw_hit_count": total_count,
            "retrieval_cap": retmax,
            "retrieved_count": len(pmids),
            "returned_count": len(pmids),
            "pagination_status": page_status,
            "retrieval_complete": retrieval_complete,
            "pagination_complete": retrieval_complete,
            "searched_at": completed_at,
            "request_status": request_status,
            "request_attempt_count": attempt_count,
            "retry_count": retry_count,
            "error_type": error_type,
            "error_message": error_message,
            "api_endpoint": f"{NCBI_EUTILS_BASE_URL}/esearch.fcgi",
            "sort_order": "relevance",
            "query_contract_status": "approved_terms_only",
            "rerun_required": (
                "Y" if page_status in {"failed", "incomplete_response"} else "N"
            ),
            "review_status": "candidate_unverified",
            "runtime_score_change": "none",
            "pipeline_version": PIPELINE_VERSION,
        }
        query_rows.append(row)
        write_csv(checkpoint_log, QUERY_LOG_FIELDS, query_rows)
        if index % 25 == 0 or index == len(cohort_rows):
            print(
                f"PubMed ESearch {index}/{len(cohort_rows)}; "
                f"errors={sum(value['request_status'] != 'success' for value in query_rows)}",
                file=sys.stderr,
                flush=True,
            )
    return query_rows, hit_map


def fetch_metadata(
    client: RateLimitedPubMedClient,
    hit_map: Mapping[str, Sequence[str]],
) -> tuple[dict[str, PubMedPaper], dict[str, str], int, int]:
    all_pmids = stable_unique(
        pmid for values in hit_map.values() for pmid in values if pmid.isdigit()
    )
    papers: dict[str, PubMedPaper] = {}
    errors: dict[str, str] = {}
    request_count = 0
    retry_count = 0
    for index, batch in enumerate(chunks(all_pmids, FETCH_BATCH_SIZE), start=1):
        try:
            fetched, result = client.fetch(batch)
            papers.update(fetched)
            request_count += result.attempt_count
            retry_count += result.retry_count
            for pmid in batch:
                if pmid not in fetched:
                    errors[pmid] = "PMID missing from successful EFetch response"
        except Exception as exc:
            message = f"{type(exc).__name__}: {str(exc)[:900]}"
            for pmid in batch:
                errors[pmid] = message
        if index % 20 == 0 or index * FETCH_BATCH_SIZE >= len(all_pmids):
            print(
                f"PubMed EFetch {min(index * FETCH_BATCH_SIZE, len(all_pmids))}/"
                f"{len(all_pmids)}; metadata_errors={len(errors)}",
                file=sys.stderr,
                flush=True,
            )
    return papers, errors, request_count, retry_count


def build_candidate_rows(
    query_rows: Sequence[Mapping[str, object]],
    hit_map: Mapping[str, Sequence[str]],
    papers: Mapping[str, PubMedPaper],
    metadata_errors: Mapping[str, str],
) -> list[dict[str, object]]:
    by_ingredient = {str(row["ingredient_id"]): row for row in query_rows}
    candidates: list[dict[str, object]] = []
    for ingredient_id, pmids in hit_map.items():
        query_row = by_ingredient[ingredient_id]
        for position, pmid in enumerate(pmids, start=1):
            paper = papers.get(pmid)
            metadata_status = "complete" if paper is not None else "fetch_error"
            candidates.append(
                {
                    "query_id": query_row["query_id"],
                    "source": "pubmed",
                    "ingredient_rank": query_row["ingredient_rank"],
                    "ingredient_id": ingredient_id,
                    "name_ko": query_row["name_ko"],
                    "canonical_name_en": query_row["canonical_name_en"],
                    "result_position": position,
                    "pmid": pmid,
                    "doi": paper.doi if paper else "",
                    "title": paper.title if paper else "",
                    "journal": paper.journal if paper else "",
                    "publication_date": paper.publication_date if paper else "",
                    "publication_types": "|".join(paper.publication_types) if paper else "",
                    "authors": "|".join(paper.authors) if paper else "",
                    "abstract": paper.abstract if paper else "",
                    "metadata_status": metadata_status,
                    "metadata_error": metadata_errors.get(pmid, ""),
                    "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "search_query": query_row["search_query"],
                    "query_sha256": query_row["query_sha256"],
                    "searched_at_utc": query_row["completed_at_utc"],
                    "searched_at": query_row["completed_at_utc"],
                    "query_contract_status": "approved_terms_only",
                    "review_status": "candidate_unverified",
                    "runtime_score_change": "none",
                    "pipeline_version": PIPELINE_VERSION,
                }
            )
    return candidates


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
        "--output-dir",
        type=Path,
        default=Path("data/reconciliation/v1_1_fresh"),
    )
    parser.add_argument("--retmax", type=int, default=DEFAULT_RETMAX)
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""))
    parser.add_argument("--tool", default=DEFAULT_TOOL)
    parser.add_argument("--request-interval-seconds", type=float, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.retmax < 1 or args.retmax > 9999:
        raise PubMedSearchError("--retmax must be between 1 and 9999")

    output_dir: Path = args.output_dir
    query_log_path = output_dir / "pubmed_query_log_466_v1_1_fresh.csv"
    candidate_path = output_dir / "pubmed_candidates_466_v1_1_fresh.csv"
    summary_path = output_dir / "pubmed_search_summary_466_v1_1_fresh.json"
    existing = [path for path in (query_log_path, candidate_path, summary_path) if path.exists()]
    if existing and not args.overwrite:
        raise PubMedSearchError(
            "Fresh PubMed output already exists; pass --overwrite to replace it: "
            + ", ".join(str(path) for path in existing)
        )

    cohort_rows = read_csv(args.cohort)
    validate_frozen_cohort(cohort_rows)
    ingredient_ids = {row["ingredient_id"].strip() for row in cohort_rows}
    terms_by_id = build_approved_terms(
        ingredient_ids,
        read_csv(args.ingredients),
        read_csv(args.aliases),
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    run_started_at = utc_now()
    client = RateLimitedPubMedClient(
        email=args.email,
        api_key=args.api_key,
        tool=args.tool,
        request_interval_seconds=args.request_interval_seconds,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    query_rows, hit_map = run_search(
        cohort_rows=cohort_rows,
        terms_by_id=terms_by_id,
        client=client,
        retmax=args.retmax,
        checkpoint_log=query_log_path,
    )
    papers, metadata_errors, fetch_requests, fetch_retries = fetch_metadata(client, hit_map)
    candidate_rows = build_candidate_rows(
        query_rows, hit_map, papers, metadata_errors
    )
    write_csv(query_log_path, QUERY_LOG_FIELDS, query_rows)
    write_csv(candidate_path, CANDIDATE_FIELDS, candidate_rows)

    query_errors = [row for row in query_rows if row["request_status"] != "success"]
    pagination_counts: dict[str, int] = {}
    for row in query_rows:
        key = str(row["pagination_status"])
        pagination_counts[key] = pagination_counts.get(key, 0) + 1
    unique_pmids = {str(row["pmid"]) for row in candidate_rows}
    summary = {
        "pipeline_version": PIPELINE_VERSION,
        "query_version": QUERY_VERSION,
        "source": "pubmed",
        "run_started_at_utc": run_started_at,
        "run_completed_at_utc": utc_now(),
        "frozen_cohort_row_count": len(cohort_rows),
        "frozen_cohort_unique_ingredient_count": len(ingredient_ids),
        "query_log_row_count": len(query_rows),
        "successful_query_count": len(query_rows) - len(query_errors),
        "failed_query_count": len(query_errors),
        "pagination_status_counts": pagination_counts,
        "total_reported_hits_sum": sum(int(row["total_hit_count"]) for row in query_rows),
        "retrieved_ingredient_pmid_row_count": len(candidate_rows),
        "unique_retrieved_pmid_count": len(unique_pmids),
        "metadata_complete_row_count": sum(
            row["metadata_status"] == "complete" for row in candidate_rows
        ),
        "metadata_error_row_count": sum(
            row["metadata_status"] != "complete" for row in candidate_rows
        ),
        "unique_metadata_paper_count": len(papers),
        "retrieval_cap_per_ingredient": args.retmax,
        "effect_terms_in_query": False,
        "ingredient_id_fallback_used": False,
        "approved_alias_types": sorted(ALLOWED_ALIAS_TYPES),
        "skin_context_terms": list(SKIN_CONTEXT_TERMS),
        "request_interval_seconds": client.request_interval_seconds,
        "esearch_and_efetch_request_count": client.request_count,
        "esearch_and_efetch_retry_count": client.retry_count,
        "efetch_attempt_count": fetch_requests,
        "efetch_retry_count": fetch_retries,
        "input_sha256": {
            str(args.cohort): file_sha256(args.cohort),
            str(args.ingredients): file_sha256(args.ingredients),
            str(args.aliases): file_sha256(args.aliases),
        },
        "output_sha256": {
            query_log_path.name: file_sha256(query_log_path),
            candidate_path.name: file_sha256(candidate_path),
        },
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if len(query_rows) != 466 or len({row["ingredient_id"] for row in query_rows}) != 466:
        raise PubMedSearchError("Final PubMed query log failed the 466-row invariant")
    if query_errors:
        raise PubMedSearchError(
            f"{len(query_errors)} PubMed ingredient queries failed; inspect {query_log_path}"
        )
    if metadata_errors:
        raise PubMedSearchError(
            f"{len(metadata_errors)} PubMed PMIDs lack metadata; inspect {candidate_path}"
        )

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
