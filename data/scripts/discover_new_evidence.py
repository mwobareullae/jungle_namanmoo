#!/usr/bin/env python3
"""Discover newly indexed PubMed papers for canonical ingredient/effect pairs.

This collector only creates review candidates. It never updates runtime evidence,
review status, representative papers, or recommendation scores.
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
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence


NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
QUERY_VERSION = "mwbl-pair-discovery-v1"
DEFAULT_TOOL_NAME = "mwbl_evidence_discovery"
DEFAULT_LOOKBACK_DAYS = 8
DEFAULT_RETMAX_PER_PAIR = 50
DEFAULT_REQUEST_DELAY_SECONDS = 0.5
MAX_ABSTRACT_EXCERPT_LENGTH = 500

EFFECT_TERMS: dict[str, tuple[str, ...]] = {
    "effect_brightening": (
        "hyperpigmentation",
        "melasma",
        "skin pigmentation",
        "skin lightening",
        "melanin index",
    ),
    "effect_acne_sebum": (
        "acne",
        "sebum",
        "sebaceous",
    ),
    "effect_wrinkle": (
        "wrinkle",
        "photoaging",
        "skin elasticity",
        "dermal collagen",
    ),
    "effect_moisture_barrier": (
        "skin hydration",
        "skin barrier",
        "transepidermal water loss",
        "TEWL",
    ),
    "effect_calming": (
        "erythema",
        "skin irritation",
        "cutaneous inflammation",
        "pruritus",
        "dermatitis",
    ),
    "effect_exfoliation": (
        "exfoliation",
        "desquamation",
        "stratum corneum",
        "skin roughness",
        "keratinization",
    ),
}

SKIN_CONTEXT_TERMS: tuple[str, ...] = (
    "skin",
    "topical",
    "cutaneous",
    "dermatologic",
)

CANDIDATE_FIELDS: tuple[str, ...] = (
    "discovery_key",
    "ingredient_id",
    "effect_id",
    "effect_name",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "authors",
    "abstract_available",
    "abstract_excerpt",
    "source_url",
    "discovery_scope",
    "review_status",
    "score_eligible",
    "search_window_start",
    "search_window_end",
    "search_query",
)


class DiscoveryError(RuntimeError):
    """Raised when discovery input or a PubMed request is invalid."""


class DiscoveryClient(Protocol):
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

    def fetch(self, pmids: Sequence[str]) -> dict[str, "PaperMetadata"]: ...


@dataclass(frozen=True)
class PaperMetadata:
    pmid: str
    doi: str = ""
    title: str = ""
    journal: str = ""
    publication_date: str = ""
    publication_types: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    abstract: str = ""


@dataclass
class KnownEvidence:
    pair_pmids: dict[tuple[str, str], set[str]]
    pair_dois: dict[tuple[str, str], set[str]]
    global_pmids: set[str]
    global_dois: set[str]


@dataclass(frozen=True)
class DiscoveryStats:
    pair_count: int
    query_count: int
    raw_pair_matches: int
    fetched_paper_count: int
    known_pair_duplicates: int
    candidate_pair_count: int
    unique_candidate_papers: int
    request_count: int
    retry_count: int


class PubMedClient:
    def __init__(
        self,
        *,
        email: str = "",
        api_key: str = "",
        tool: str = DEFAULT_TOOL_NAME,
        request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.email = email.strip()
        self.api_key = api_key.strip()
        self.tool = tool.strip() or DEFAULT_TOOL_NAME
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.opener = opener or urllib.request.build_opener()
        self.request_count = 0
        self.retry_count = 0
        self._last_request_at = 0.0

    def search(
        self,
        query: str,
        *,
        window_start: date,
        window_end: date,
        retmax: int,
    ) -> list[str]:
        payload = self._request(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "sort": "pub_date",
                "retmax": str(retmax),
                "datetype": "edat",
                "mindate": window_start.strftime("%Y/%m/%d"),
                "maxdate": window_end.strftime("%Y/%m/%d"),
            },
        )
        try:
            decoded = json.loads(payload.decode("utf-8"))
            values = decoded["esearchresult"]["idlist"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DiscoveryError("PubMed ESearch returned an unexpected response") from exc
        return stable_unique(str(value) for value in values if str(value).isdigit())

    def fetch(self, pmids: Sequence[str]) -> dict[str, PaperMetadata]:
        papers: dict[str, PaperMetadata] = {}
        for batch in chunks(stable_unique(pmids), 200):
            payload = self._request(
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "retmode": "xml",
                },
            )
            papers.update(parse_pubmed_xml(payload))
        return papers

    def _request(self, endpoint: str, params: Mapping[str, str]) -> bytes:
        request_params = dict(params)
        request_params["tool"] = self.tool
        if self.email:
            request_params["email"] = self.email
        if self.api_key:
            request_params["api_key"] = self.api_key

        url = f"{NCBI_EUTILS_BASE_URL}/{endpoint}?{urllib.parse.urlencode(request_params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"{self.tool}/1.0"},
        )

        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.request_count += 1
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise DiscoveryError(f"PubMed request failed with HTTP {exc.code}") from exc
                if attempt >= self.max_retries:
                    raise DiscoveryError(
                        f"PubMed request failed after {self.max_retries + 1} attempts"
                    ) from exc
                retry_after = parse_retry_after(exc.headers.get("Retry-After"))
            except urllib.error.URLError as exc:
                if attempt >= self.max_retries:
                    raise DiscoveryError(
                        f"PubMed request failed after {self.max_retries + 1} attempts"
                    ) from exc
                retry_after = 0.0

            self.retry_count += 1
            time.sleep(max(retry_after, min(8.0, 2.0**attempt)))

        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def normalize_doi(raw_value: str) -> str:
    value = raw_value.strip().casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.strip().rstrip(".,;:)]}")


def extract_pmids(raw_value: str) -> set[str]:
    return set(re.findall(r"(?<!\d)\d{6,9}(?!\d)", raw_value or ""))


def load_known_evidence(rows: Sequence[Mapping[str, str]]) -> KnownEvidence:
    pair_pmids: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_dois: dict[tuple[str, str], set[str]] = defaultdict(set)
    global_pmids: set[str] = set()
    global_dois: set[str] = set()

    for row in rows:
        pair = (row.get("ingredient_id", "").strip(), row.get("effect_id", "").strip())
        for pmid in extract_pmids(row.get("pmid", "")):
            pair_pmids[pair].add(pmid)
            global_pmids.add(pmid)
        doi = normalize_doi(row.get("doi", ""))
        if doi:
            pair_dois[pair].add(doi)
            global_dois.add(doi)

    return KnownEvidence(
        pair_pmids=dict(pair_pmids),
        pair_dois=dict(pair_dois),
        global_pmids=global_pmids,
        global_dois=global_dois,
    )


def load_ingredient_terms(
    ingredient_rows: Sequence[Mapping[str, str]],
    alias_rows: Sequence[Mapping[str, str]],
    ingredient_ids: set[str],
) -> dict[str, list[str]]:
    terms: dict[str, list[str]] = defaultdict(list)

    for row in ingredient_rows:
        ingredient_id = row.get("ingredient_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        name_en = row.get("name_en", "").strip()
        if name_en:
            terms[ingredient_id].extend(split_english_name(name_en))

    allowed_alias_types = {"inci", "synonym", "en"}
    for row in alias_rows:
        ingredient_id = row.get("canonical_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        if row.get("confidence", "").strip().casefold() != "high":
            continue
        if row.get("alias_type", "").strip().casefold() not in allowed_alias_types:
            continue
        alias = row.get("alias", "").strip()
        if is_usable_english_term(alias):
            terms[ingredient_id].append(alias)

    for ingredient_id in ingredient_ids:
        fallback = ingredient_id.replace("_", " ")
        selected = stable_unique(terms.get(ingredient_id, []) + [fallback])
        terms[ingredient_id] = selected[:16]
    return dict(terms)


def split_english_name(name: str) -> list[str]:
    # A slash is often part of one exact INCI name (for example Flower/Leaf
    # Extract or a copolymer). Splitting on it creates broad false terms such
    # as "Leaf Extract". A pipe is the explicit alternative-name separator
    # used by this dataset.
    values = [part.strip() for part in name.split("|")]
    return [value for value in values if is_usable_english_term(value)]


def is_usable_english_term(value: str) -> bool:
    return value.isascii() and bool(re.search(r"[A-Za-z]", value)) and len(value) >= 4


def pubmed_title_abstract_term(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.replace('"', " ")).strip()
    return f'"{cleaned}"[Title/Abstract]'


def build_pair_query(ingredient_terms: Sequence[str], effect_id: str) -> str:
    effect_terms = EFFECT_TERMS.get(effect_id)
    if not effect_terms:
        raise DiscoveryError(f"Unsupported effect_id: {effect_id}")
    if not ingredient_terms:
        raise DiscoveryError("At least one ingredient search term is required")

    ingredient_clause = " OR ".join(pubmed_title_abstract_term(term) for term in ingredient_terms)
    effect_clause = " OR ".join(pubmed_title_abstract_term(term) for term in effect_terms)
    context_clause = " OR ".join(pubmed_title_abstract_term(term) for term in SKIN_CONTEXT_TERMS)
    return f"({ingredient_clause}) AND ({effect_clause}) AND ({context_clause})"


def discover_candidates(
    *,
    pair_rows: Sequence[Mapping[str, str]],
    ingredient_terms: Mapping[str, Sequence[str]],
    known: KnownEvidence,
    client: DiscoveryClient,
    window_start: date,
    window_end: date,
    retmax_per_pair: int,
) -> tuple[list[dict[str, str]], DiscoveryStats, dict[str, str]]:
    pair_to_pmids: dict[tuple[str, str], list[str]] = {}
    pair_queries: dict[str, str] = {}
    raw_pair_matches = 0
    known_pair_duplicates = 0
    fetch_pmids: set[str] = set()

    for row in pair_rows:
        ingredient_id = row["ingredient_id"].strip()
        effect_id = row["effect_id"].strip()
        pair = (ingredient_id, effect_id)
        query = build_pair_query(ingredient_terms[ingredient_id], effect_id)
        pair_queries[f"{ingredient_id}|{effect_id}"] = query
        found_pmids = client.search(
            query,
            window_start=window_start,
            window_end=window_end,
            retmax=retmax_per_pair,
        )
        raw_pair_matches += len(found_pmids)

        unseen_pmids: list[str] = []
        known_pmids = known.pair_pmids.get(pair, set())
        for pmid in found_pmids:
            if pmid in known_pmids:
                known_pair_duplicates += 1
                continue
            unseen_pmids.append(pmid)
            fetch_pmids.add(pmid)
        pair_to_pmids[pair] = unseen_pmids

    papers = client.fetch(sorted(fetch_pmids, key=int)) if fetch_pmids else {}
    pair_rows_by_key = {
        (row["ingredient_id"].strip(), row["effect_id"].strip()): row for row in pair_rows
    }
    candidates: list[dict[str, str]] = []

    for pair, pmids in pair_to_pmids.items():
        ingredient_id, effect_id = pair
        known_dois = known.pair_dois.get(pair, set())
        source_row = pair_rows_by_key[pair]
        query = pair_queries[f"{ingredient_id}|{effect_id}"]
        for pmid in pmids:
            paper = papers.get(pmid, PaperMetadata(pmid=pmid))
            doi = normalize_doi(paper.doi)
            if doi and doi in known_dois:
                known_pair_duplicates += 1
                continue
            known_elsewhere = pmid in known.global_pmids or bool(doi and doi in known.global_dois)
            abstract = collapse_whitespace(paper.abstract)
            candidates.append(
                {
                    "discovery_key": f"PMID:{pmid}:{ingredient_id}:{effect_id}",
                    "ingredient_id": ingredient_id,
                    "effect_id": effect_id,
                    "effect_name": source_row.get("effect_name", "").strip(),
                    "pmid": pmid,
                    "doi": doi,
                    "title": collapse_whitespace(paper.title),
                    "journal": collapse_whitespace(paper.journal),
                    "publication_date": paper.publication_date,
                    "publication_types": "; ".join(paper.publication_types),
                    "authors": "; ".join(paper.authors),
                    "abstract_available": str(bool(abstract)).lower(),
                    "abstract_excerpt": truncate(abstract, MAX_ABSTRACT_EXCERPT_LENGTH),
                    "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "discovery_scope": (
                        "known_paper_new_pair" if known_elsewhere else "new_paper"
                    ),
                    "review_status": "candidate_unverified",
                    "score_eligible": "false",
                    "search_window_start": window_start.isoformat(),
                    "search_window_end": window_end.isoformat(),
                    "search_query": query,
                }
            )

    candidates.sort(key=lambda row: (row["ingredient_id"], row["effect_id"], int(row["pmid"])))
    stats = DiscoveryStats(
        pair_count=len(pair_rows),
        query_count=len(pair_queries),
        raw_pair_matches=raw_pair_matches,
        fetched_paper_count=len(papers),
        known_pair_duplicates=known_pair_duplicates,
        candidate_pair_count=len(candidates),
        unique_candidate_papers=len({row["pmid"] for row in candidates}),
        request_count=client.request_count,
        retry_count=client.retry_count,
    )
    return candidates, stats, pair_queries


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def parse_retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return collapse_whitespace("".join(element.itertext()))


def parse_pubmed_xml(payload: bytes) -> dict[str, PaperMetadata]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DiscoveryError("PubMed EFetch returned invalid XML") from exc

    papers: dict[str, PaperMetadata] = {}
    for node in root.findall(".//PubmedArticle"):
        pmid = element_text(node.find("./MedlineCitation/PMID"))
        if not pmid:
            continue
        article = node.find("./MedlineCitation/Article")
        if article is None:
            papers[pmid] = PaperMetadata(pmid=pmid)
            continue

        doi = ""
        for article_id in node.findall("./PubmedData/ArticleIdList/ArticleId"):
            if article_id.attrib.get("IdType", "").casefold() == "doi":
                doi = element_text(article_id)
                break
        if not doi:
            for location_id in article.findall("./ELocationID"):
                if location_id.attrib.get("EIdType", "").casefold() == "doi":
                    doi = element_text(location_id)
                    break

        abstract_parts: list[str] = []
        for abstract_node in article.findall("./Abstract/AbstractText"):
            text = element_text(abstract_node)
            if not text:
                continue
            label = abstract_node.attrib.get("Label", "").strip()
            abstract_parts.append(f"{label}: {text}" if label else text)

        authors: list[str] = []
        for author in article.findall("./AuthorList/Author"):
            collective = element_text(author.find("./CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            name = " ".join(
                part
                for part in (
                    element_text(author.find("./ForeName")),
                    element_text(author.find("./LastName")),
                )
                if part
            )
            if name:
                authors.append(name)

        publication_types = stable_unique(
            element_text(value) for value in article.findall("./PublicationTypeList/PublicationType")
        )
        journal = element_text(article.find("./Journal/Title"))
        papers[pmid] = PaperMetadata(
            pmid=pmid,
            doi=normalize_doi(doi),
            title=element_text(article.find("./ArticleTitle")),
            journal=journal,
            publication_date=parse_publication_date(article),
            publication_types=tuple(publication_types),
            authors=tuple(authors),
            abstract=" ".join(abstract_parts),
        )
    return papers


def parse_publication_date(article: ET.Element) -> str:
    article_date = article.find("./ArticleDate")
    if article_date is not None:
        values = [element_text(article_date.find(f"./{part}")) for part in ("Year", "Month", "Day")]
        return "-".join(value for value in values if value)

    pub_date = article.find("./Journal/JournalIssue/PubDate")
    if pub_date is None:
        return ""
    medline_date = element_text(pub_date.find("./MedlineDate"))
    if medline_date:
        return medline_date
    values = [element_text(pub_date.find(f"./{part}")) for part in ("Year", "Month", "Day")]
    return "-".join(value for value in values if value)


def write_candidates(path: Path, candidates: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)


def build_summary(
    *,
    stats: DiscoveryStats,
    candidates: Sequence[Mapping[str, str]],
    window_start: date,
    window_end: date,
) -> str:
    effect_counts = Counter(row["effect_name"] or row["effect_id"] for row in candidates)
    lines = [
        "# 주간 신규 논문 후보",
        "",
        f"- 검색 기간(Entrez 등록일): `{window_start.isoformat()}` ~ `{window_end.isoformat()}`",
        f"- 검색한 성분×효능 쌍: **{stats.pair_count}개**",
        f"- 새 후보 연결: **{stats.candidate_pair_count}개** / 고유 논문 **{stats.unique_candidate_papers}편**",
        f"- 기존 동일 성분×효능 근거와 중복되어 제외: **{stats.known_pair_duplicates}개**",
        f"- NCBI 요청: **{stats.request_count}회** (재시도 {stats.retry_count}회)",
        "- 자동 점수 반영: **0건** (`candidate_unverified`, `score_eligible=false`)",
        "",
    ]

    if effect_counts:
        lines.extend(["## 효능축별 후보", ""])
        for effect_name, count in sorted(effect_counts.items()):
            lines.append(f"- {effect_name}: {count}개")
        lines.append("")

    lines.extend(["## 검수 대기 목록", ""])
    if not candidates:
        lines.append("이번 검색 기간에 새 후보가 없습니다.")
    else:
        lines.extend(
            [
                "| 성분 | 효능 | 논문 | 구분 |",
                "|---|---|---|---|",
            ]
        )
        for row in candidates[:30]:
            title = row["title"] or f"PMID {row['pmid']}"
            title = title.replace("|", "\\|")
            lines.append(
                f"| `{row['ingredient_id']}` | {row['effect_name']} | "
                f"[{title}]({row['source_url']}) | `{row['discovery_scope']}` |"
            )
        if len(candidates) > 30:
            lines.append("")
            lines.append(f"나머지 {len(candidates) - 30}개는 CSV에서 확인합니다.")

    lines.extend(
        [
            "",
            "> 이 결과는 발견 후보입니다. 사람이 논문 범위와 결과를 검수해 `accepted`로 바꾸기 전에는 추천 점수에 사용할 수 없습니다.",
            "",
        ]
    )
    return "\n".join(lines)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(
    path: Path,
    *,
    input_paths: Mapping[str, Path],
    output_paths: Mapping[str, Path],
    stats: DiscoveryStats,
    window_start: date,
    window_end: date,
    pair_queries: Mapping[str, str],
    contact_email_configured: bool,
) -> None:
    manifest = {
        "schema_version": 1,
        "query_version": QUERY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "search_window": {
            "date_type": "entrez_date",
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "source": {
            "provider": "NCBI PubMed E-utilities",
            "base_url": NCBI_EUTILS_BASE_URL,
            "contact_email_configured": contact_email_configured,
        },
        "invariants": {
            "review_status": "candidate_unverified",
            "score_eligible": False,
            "runtime_data_modified": False,
        },
        "stats": stats.__dict__,
        "inputs": {
            name: {"path": str(value), "sha256": sha256_file(value)}
            for name, value in input_paths.items()
        },
        "outputs": {
            name: {"path": str(value), "sha256": sha256_file(value)}
            for name, value in output_paths.items()
        },
        "pair_queries": dict(sorted(pair_queries.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def select_pairs(
    rows: Sequence[dict[str, str]],
    ingredient_ids: Sequence[str],
    effect_ids: Sequence[str],
) -> list[dict[str, str]]:
    ingredient_filter = set(ingredient_ids)
    effect_filter = set(effect_ids)
    selected = [
        row
        for row in rows
        if (not ingredient_filter or row["ingredient_id"] in ingredient_filter)
        and (not effect_filter or row["effect_id"] in effect_filter)
    ]
    if not selected:
        raise DiscoveryError("No ingredient/effect pairs matched the requested filters")
    return selected


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingredient-effect", type=Path, default=Path("data/ingredient_effect.csv"))
    parser.add_argument("--ingredient-evidence", type=Path, default=Path("data/ingredient_evidence.csv"))
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--aliases", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence-discovery"))
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--retmax-per-pair", type=int, default=DEFAULT_RETMAX_PER_PAIR)
    parser.add_argument("--ingredient-id", action="append", default=[])
    parser.add_argument("--effect-id", action="append", default=[])
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""))
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.days < 1:
        raise DiscoveryError("--days must be at least 1")
    if args.retmax_per_pair < 1:
        raise DiscoveryError("--retmax-per-pair must be at least 1")

    pair_rows = select_pairs(
        read_csv_rows(args.ingredient_effect),
        args.ingredient_id,
        args.effect_id,
    )
    ingredient_ids = {row["ingredient_id"] for row in pair_rows}
    terms = load_ingredient_terms(
        read_csv_rows(args.ingredients),
        read_csv_rows(args.aliases),
        ingredient_ids,
    )
    known = load_known_evidence(read_csv_rows(args.ingredient_evidence))
    window_end = args.as_of
    window_start = window_end - timedelta(days=args.days - 1)
    client = PubMedClient(
        email=args.email,
        api_key=args.api_key,
        request_delay_seconds=args.request_delay,
    )

    candidates, stats, pair_queries = discover_candidates(
        pair_rows=pair_rows,
        ingredient_terms=terms,
        known=known,
        client=client,
        window_start=window_start,
        window_end=window_end,
        retmax_per_pair=args.retmax_per_pair,
    )

    candidates_path = args.output_dir / "new_evidence_candidates.csv"
    summary_path = args.output_dir / "summary.md"
    manifest_path = args.output_dir / "run_manifest.json"
    write_candidates(candidates_path, candidates)
    summary = build_summary(
        stats=stats,
        candidates=candidates,
        window_start=window_start,
        window_end=window_end,
    )
    summary_path.write_text(summary, encoding="utf-8")
    write_manifest(
        manifest_path,
        input_paths={
            "ingredient_effect": args.ingredient_effect,
            "ingredient_evidence": args.ingredient_evidence,
            "ingredients": args.ingredients,
            "aliases": args.aliases,
            "collector": Path(__file__),
        },
        output_paths={
            "candidates": candidates_path,
            "summary": summary_path,
        },
        stats=stats,
        window_start=window_start,
        window_end=window_end,
        pair_queries=pair_queries,
        contact_email_configured=bool(args.email),
    )
    print(summary)
    print(f"Artifacts: {args.output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DiscoveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
