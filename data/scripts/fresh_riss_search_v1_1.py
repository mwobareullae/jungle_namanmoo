#!/usr/bin/env python3
"""Robots-compliant fresh RISS search for the frozen 466-ingredient cohort."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping, Sequence

from fresh_pubmed_search_v1_1 import (
    TermProvenance,
    build_approved_terms,
    file_sha256,
    read_csv,
    stable_unique,
    text_sha256,
    utc_now,
    write_csv,
)


PIPELINE_VERSION = "mwbl-ingredient-evidence-filter-v1.1-fresh-riss"
QUERY_VERSION = "mwbl-riss-approved-term-skin-v1.1"
RISS_ROBOTS_URL = "https://www.riss.kr/robots.txt"
RISS_SEARCH_URL = "https://www.riss.kr/search/Search.do"
USER_AGENT = "mwbl-evidence-research/1.1"
PAGE_SCALE = 20
MIN_CRAWL_DELAY_SECONDS = 10.0

EXECUTION_FIELDS = (
    "execution_query_id", "source", "ingredient_rank", "ingredient_id", "name_ko",
    "canonical_name_en", "approved_search_term", "term_origin", "alias_type",
    "term_source", "search_query", "query_url", "query_version", "started_at_utc",
    "query_sha256",
    "completed_at_utc", "raw_hit_count", "returned_count", "retrieval_cap",
    "pagination_complete", "pagination_status", "request_status",
    "request_attempt_count", "retry_count", "http_status", "final_url", "searched_at",
    "query_contract_status", "rerun_required", "error_type", "error_message",
    "robots_url", "robots_fetched_at_utc", "robots_sha256", "review_status",
    "runtime_score_change", "pipeline_version",
)
HIT_FIELDS = (
    "execution_query_id", "query_sha256", "ingredient_rank", "ingredient_id", "name_ko",
    "canonical_name_en", "approved_search_term", "result_position", "control_no",
    "material_type", "title", "pre_abstract", "authors", "journal",
    "publication_year", "source_url", "retrieved_at_utc", "review_status",
    "runtime_score_change", "pipeline_version",
)
QUERY_FIELDS = (
    "query_id", "source", "ingredient_rank", "ingredient_id", "name_ko",
    "canonical_name_en", "approved_search_terms", "search_query", "query_sha256",
    "query_version", "execution_count",
    "successful_execution_count", "failed_execution_count", "capped_execution_count",
    "request_status", "total_hit_count", "raw_hit_count", "retrieval_cap",
    "retrieved_count", "returned_count", "pagination_complete",
    "pagination_status", "searched_at", "query_contract_status", "rerun_required",
    "error_type", "error_message", "robots_url", "robots_fetched_at_utc",
    "robots_sha256", "review_status", "runtime_score_change", "pipeline_version",
)
CANDIDATE_FIELDS = (
    "query_id", "query_sha256", "source", "ingredient_rank", "ingredient_id",
    "name_ko", "canonical_name_en",
    "source_id", "control_no", "title", "pre_abstract", "authors", "journal",
    "abstract", "publication_year", "source_url", "best_result_position", "matched_search_terms",
    "execution_query_ids", "metadata_status", "retrieved_at_utc", "review_status",
    "runtime_score_change", "pipeline_version",
)


class RissSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class RissPaper:
    control_no: str
    material_type: str
    title: str
    pre_abstract: str
    authors: str
    journal: str
    publication_year: str
    source_url: str


@dataclass(frozen=True)
class HttpResult:
    body: str
    status: int
    final_url: str
    attempts: int
    retries: int


def clean_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", cleaned)


class RissResultParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.container_depth: int | None = None
        self.current: dict[str, object] | None = None
        self.li_depth = 0
        self.capture_title: tuple[int, list[str]] | None = None
        self.capture_abstract: tuple[int, list[str]] | None = None
        self.etc_depth: int | None = None
        self.capture_span: dict[str, object] | None = None
        self.papers: list[RissPaper] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        is_void = tag in self.VOID
        if not is_void:
            self.depth += 1
        here = self.depth
        classes = set(attrs.get("class", "").split())
        if tag == "div" and "srchResultListW" in classes:
            self.container_depth = here
        if self.container_depth is not None and tag == "li":
            if self.current is None:
                self.current = {"spans": [], "p_control_no": ""}
                self.li_depth = 1
            else:
                self.li_depth += 1
        if self.current is None:
            return
        if tag == "input" and attrs.get("name") == "p_control_no":
            self.current["p_control_no"] = attrs.get("value", "")
        if tag == "p" and "title" in classes:
            self.capture_title = (here, [])
        elif tag == "p" and "preAbstract" in classes:
            self.capture_abstract = (here, [])
        elif tag == "p" and "etc" in classes:
            self.etc_depth = here
        if tag == "span" and self.etc_depth is not None and self.capture_span is None:
            self.capture_span = {"depth": here, "class": attrs.get("class", ""), "parts": [], "hrefs": []}
        if tag == "a" and self.capture_span is not None:
            self.capture_span["hrefs"].append(attrs.get("href", ""))

    def handle_data(self, data: str) -> None:
        if self.capture_title is not None:
            self.capture_title[1].append(data)
        if self.capture_abstract is not None:
            self.capture_abstract[1].append(data)
        if self.capture_span is not None:
            self.capture_span["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        here = self.depth
        if self.current is not None:
            if tag == "span" and self.capture_span is not None and self.capture_span["depth"] == here:
                self.capture_span["text"] = clean_text("".join(self.capture_span["parts"]))
                self.current["spans"].append(self.capture_span)
                self.capture_span = None
            if tag == "p" and self.capture_title is not None and self.capture_title[0] == here:
                self.current["title"] = clean_text("".join(self.capture_title[1]))
                self.capture_title = None
            if tag == "p" and self.capture_abstract is not None and self.capture_abstract[0] == here:
                self.current["pre_abstract"] = clean_text("".join(self.capture_abstract[1]))
                self.capture_abstract = None
            if tag == "p" and self.etc_depth == here:
                self.etc_depth = None
            if tag == "li":
                self.li_depth -= 1
                if self.li_depth == 0:
                    self._finish_current()
        if tag == "div" and self.container_depth == here:
            self.container_depth = None
        if tag not in self.VOID:
            self.depth = max(0, self.depth - 1)

    def _finish_current(self) -> None:
        assert self.current is not None
        raw_control = str(self.current.get("p_control_no", ""))
        values = raw_control.split("|", 1)
        control_no = values[0].strip()
        material_type = values[1].strip() if len(values) == 2 else "1a0202e37d52c72d"
        spans = list(self.current.get("spans", []))
        authors = next((str(x.get("text", "")) for x in spans if "writer" in str(x.get("class", "")).split()), "")
        publication_year = next((str(x.get("text", "")) for x in spans if re.fullmatch(r"(?:19|20)\d{2}", str(x.get("text", "")))), "")
        journal = ""
        for span in spans:
            hrefs = [str(value) for value in span.get("hrefs", [])]
            if any("p_mat_type=3a11008f85f7c51d" in value and "v_control_no=" not in value for value in hrefs):
                journal = str(span.get("text", ""))
                break
        source_url = ""
        if control_no:
            source_url = RISS_SEARCH_URL.rsplit("/search/", 1)[0] + "/search/detail/DetailView.do?" + urllib.parse.urlencode({"p_mat_type": material_type, "control_no": control_no})
            self.papers.append(RissPaper(control_no, material_type, str(self.current.get("title", "")), str(self.current.get("pre_abstract", "")), authors, journal, publication_year, source_url))
        self.current = None
        self.capture_title = self.capture_abstract = None
        self.capture_span = None
        self.etc_depth = None


def parse_riss_html(value: str) -> tuple[int, list[RissPaper]]:
    match = re.search(r"검색결과\s*<span[^>]*class=[\"']num[\"'][^>]*>\s*([\d,]+)\s*</span>\s*건", value, re.I)
    if not match:
        if re.search(r"검색결과가\s*없습니다", clean_text(value)):
            total = 0
        else:
            raise RissSearchError("RISS response did not expose a search-result count")
    else:
        total = int(match.group(1).replace(",", ""))
    parser = RissResultParser()
    parser.feed(value)
    expected = min(total, PAGE_SCALE)
    if len(parser.papers) != expected:
        raise RissSearchError(f"RISS returned {total} hits but parser extracted {len(parser.papers)}/{expected} first-page records")
    return total, parser.papers


def parse_riss_robots_policy(text: str, path: str = "/search/Search.do") -> tuple[bool, float]:
    """Apply RFC-style longest-path matching to the User-agent: * group."""
    active = False
    rules: list[tuple[str, bool]] = []
    delay = 0.0
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.casefold()
        if key == "user-agent":
            active = value == "*"
        elif active and key in {"allow", "disallow"} and value:
            rules.append((value, key == "allow"))
        elif active and key == "crawl-delay":
            try:
                delay = float(value)
            except ValueError:
                pass
    matched = [(len(pattern), allowed) for pattern, allowed in rules if path.startswith(pattern)]
    if not matched:
        return True, delay
    longest = max(length for length, _ in matched)
    # An Allow wins a same-length tie, per the standard matching behavior.
    allowed = any(value for length, value in matched if length == longest)
    return allowed, delay


def fetch_robots(timeout: float = 45.0) -> tuple[str, str, float, float]:
    req = urllib.request.Request(RISS_ROBOTS_URL, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    fetched_monotonic = time.monotonic()
    allowed, delay = parse_riss_robots_policy(text)
    if not allowed:
        raise RissSearchError("RISS robots.txt does not allow /search for this collector")
    if delay < MIN_CRAWL_DELAY_SECONDS:
        raise RissSearchError(f"RISS crawl-delay unexpectedly below required 10 seconds: {delay}")
    return text, utc_now(), fetched_monotonic, delay


class RissClient:
    def __init__(self, *, delay: float, last_request_at: float, timeout: float = 60.0, max_retries: int = 3) -> None:
        self.delay = max(MIN_CRAWL_DELAY_SECONDS, delay); self.last_request_at = last_request_at
        self.timeout = timeout; self.max_retries = max_retries; self.request_count = 0; self.retry_count = 0

    def get(self, url: str) -> HttpResult:
        attempts = retries = 0
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
        for attempt in range(self.max_retries + 1):
            remaining = self.delay - (time.monotonic() - self.last_request_at)
            if remaining > 0: time.sleep(remaining)
            self.last_request_at = time.monotonic(); attempts += 1; self.request_count += 1
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return HttpResult(response.read().decode("utf-8", "replace"), response.status, response.url, attempts, retries)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in {403, 429, 500, 502, 503, 504}
                if not retryable or attempt >= self.max_retries: raise RissSearchError(f"RISS HTTP {exc.code} after {attempts} attempt(s)") from exc
                retry_after = float(exc.headers.get("Retry-After") or 0)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries: raise RissSearchError(f"RISS request failed after {attempts} attempt(s): {type(exc).__name__}") from exc
                retry_after = 0.0
            retries += 1; self.retry_count += 1
            if retry_after > self.delay: time.sleep(retry_after - self.delay)
        raise AssertionError("unreachable")


def query_url(term: str) -> tuple[str, str]:
    query = f'"{term}" skin'
    params = {"isDetailSearch": "N", "searchGubun": "true", "viewYn": "OP", "query": query, "colName": "re_a_kor", "strSort": "RANK", "pageScale": str(PAGE_SCALE), "iStartCount": "0"}
    return query, RISS_SEARCH_URL + "?" + urllib.parse.urlencode(params)


def build_plan(cohort: Sequence[Mapping[str, str]], terms: Mapping[str, Sequence[TermProvenance]]) -> list[dict[str, object]]:
    plan = []
    for row in cohort:
        iid = row["ingredient_id"].strip()
        for value in terms[iid]:
            query, url = query_url(value.term)
            query_sha = text_sha256(query)
            eid = f"riss:{iid}:{query_sha[:16]}"
            plan.append({"execution_query_id": eid, "query_sha256": query_sha, "ingredient_rank": row.get("ingredient_rank", ""), "ingredient_id": iid, "name_ko": row.get("name_ko", ""), "canonical_name_en": terms[iid][0].term, "approved_search_term": value.term, "term_origin": value.origin, "alias_type": value.alias_type, "term_source": value.source, "search_query": query, "query_url": url})
    return plan


def execute_one(item: Mapping[str, object], client: RissClient, robots_text: str, robots_at: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    started = utc_now(); before_req = client.request_count; before_retry = client.retry_count
    result: HttpResult | None = None; papers: list[RissPaper] = []
    try:
        result = client.get(str(item["query_url"])); total, papers = parse_riss_html(result.body)
        returned = len(papers); status = "capped_at_page_scale" if total > PAGE_SCALE else "complete"
        complete = "N" if total > PAGE_SCALE else "Y"; request_status = "success"; rerun = "N"; etype = emsg = ""
    except Exception as exc:
        total = returned = 0; status = "failed"; complete = "N"; request_status = "error"; rerun = "Y"; etype = type(exc).__name__; emsg = str(exc)[:1000]
    completed = utc_now(); robots_sha = text_sha256(robots_text)
    row = {**item, "source": "riss", "query_version": QUERY_VERSION, "started_at_utc": started, "completed_at_utc": completed, "raw_hit_count": total, "returned_count": returned, "retrieval_cap": PAGE_SCALE, "pagination_complete": complete, "pagination_status": status, "request_status": request_status, "request_attempt_count": result.attempts if result else client.request_count-before_req, "retry_count": result.retries if result else client.retry_count-before_retry, "http_status": result.status if result else "", "final_url": result.final_url if result else "", "searched_at": completed, "query_contract_status": "approved_terms_only", "rerun_required": rerun, "error_type": etype, "error_message": emsg, "robots_url": RISS_ROBOTS_URL, "robots_fetched_at_utc": robots_at, "robots_sha256": robots_sha, "review_status": "candidate_unverified", "runtime_score_change": "none", "pipeline_version": PIPELINE_VERSION}
    hits = [{"execution_query_id": item["execution_query_id"], "query_sha256": item["query_sha256"], "ingredient_rank": item["ingredient_rank"], "ingredient_id": item["ingredient_id"], "name_ko": item["name_ko"], "canonical_name_en": item["canonical_name_en"], "approved_search_term": item["approved_search_term"], "result_position": i, "control_no": p.control_no, "material_type": p.material_type, "title": p.title, "pre_abstract": p.pre_abstract, "authors": p.authors, "journal": p.journal, "publication_year": p.publication_year, "source_url": p.source_url, "retrieved_at_utc": completed, "review_status": "candidate_unverified", "runtime_score_change": "none", "pipeline_version": PIPELINE_VERSION} for i, p in enumerate(papers, 1)]
    return row, hits


def dedupe_candidates(hits: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in hits: groups[(row["ingredient_id"], row["control_no"])].append(row)
    output = []
    for _, rows in sorted(groups.items(), key=lambda x: (int(x[1][0]["ingredient_rank"]), min(int(r["result_position"]) for r in x[1]), x[0][1])):
        best = max(rows, key=lambda r: (len(r.get("pre_abstract", "")), -int(r["result_position"])))
        output.append({"source": "riss", "ingredient_rank": best["ingredient_rank"], "ingredient_id": best["ingredient_id"], "name_ko": best["name_ko"], "canonical_name_en": best["canonical_name_en"], "source_id": best["control_no"], "control_no": best["control_no"], "title": best["title"], "pre_abstract": best["pre_abstract"], "authors": best["authors"], "journal": best["journal"], "publication_year": best["publication_year"], "source_url": best["source_url"], "best_result_position": min(int(r["result_position"]) for r in rows), "matched_search_terms": "|".join(stable_unique(r["approved_search_term"] for r in rows)), "execution_query_ids": "|".join(stable_unique(r["execution_query_id"] for r in rows)), "metadata_status": "complete" if best["title"] else "partial", "retrieved_at_utc": max(r["retrieved_at_utc"] for r in rows), "review_status": "candidate_unverified", "runtime_score_change": "none", "pipeline_version": PIPELINE_VERSION})
    return output


def rollup(cohort: Sequence[Mapping[str, str]], terms: Mapping[str, Sequence[TermProvenance]], executions: Sequence[Mapping[str, str]], candidates: Sequence[Mapping[str, object]], robots_text: str, robots_at: str) -> list[dict[str, object]]:
    by_iid: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    candidate_counts = Counter(str(r["ingredient_id"]) for r in candidates)
    for row in executions: by_iid[row["ingredient_id"]].append(row)
    output=[]; rsha=text_sha256(robots_text)
    for row in cohort:
        iid=row["ingredient_id"].strip(); ex=by_iid[iid]; failed=[x for x in ex if x["request_status"]!="success"]; capped=[x for x in ex if x["pagination_status"]=="capped_at_page_scale"]
        status="error" if failed else "success"; page="failed" if failed else ("capped_at_page_scale" if capped else "complete")
        search_query=json.dumps([f'"{v.term}" skin' for v in terms[iid]],ensure_ascii=False,separators=(",",":")); query_sha=text_sha256(search_query); raw_hits=sum(int(x["raw_hit_count"] or 0) for x in ex); returned=candidate_counts[iid]
        output.append({"query_id":f"riss:{iid}:{query_sha[:16]}", "source":"riss", "ingredient_rank":row.get("ingredient_rank",""), "ingredient_id":iid, "name_ko":row.get("name_ko",""), "canonical_name_en":terms[iid][0].term, "approved_search_terms":"|".join(v.term for v in terms[iid]), "search_query":search_query, "query_sha256":query_sha, "query_version":QUERY_VERSION, "execution_count":len(ex), "successful_execution_count":len(ex)-len(failed), "failed_execution_count":len(failed), "capped_execution_count":len(capped), "request_status":status, "total_hit_count":raw_hits, "raw_hit_count":raw_hits, "retrieval_cap":PAGE_SCALE*len(ex), "retrieved_count":returned, "returned_count":returned, "pagination_complete":"Y" if page=="complete" else "N", "pagination_status":page, "searched_at":max((x["searched_at"] for x in ex),default=robots_at), "query_contract_status":"approved_terms_only", "rerun_required":"Y" if failed else "N", "error_type":"execution_failure" if failed else "", "error_message":" | ".join(f'{x["approved_search_term"]}: {x["error_message"]}' for x in failed)[:1000], "robots_url":RISS_ROBOTS_URL, "robots_fetched_at_utc":robots_at, "robots_sha256":rsha, "review_status":"candidate_unverified", "runtime_score_change":"none", "pipeline_version":PIPELINE_VERSION})
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--cohort",type=Path,default=Path("data/reconciliation/ingredient_evidence_adjudication_466.csv"));p.add_argument("--ingredients",type=Path,default=Path("data/ingredients.csv"));p.add_argument("--aliases",type=Path,default=Path("data/ingredient_aliases.csv"));p.add_argument("--output-dir",type=Path,default=Path("data/reconciliation/v1_1_fresh"));p.add_argument("--timeout-seconds",type=float,default=60);p.add_argument("--max-retries",type=int,default=3);p.add_argument("--final-retry-rounds",type=int,default=2);p.add_argument("--overwrite",action="store_true");return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a=parse_args(argv); out=a.output_dir; out.mkdir(parents=True,exist_ok=True)
    ep=out/"riss_execution_log_466_v1_1_fresh.csv"; hp=out/"riss_execution_hits_466_v1_1_fresh.csv"; qp=out/"riss_query_log_466_v1_1_fresh.csv"; cp=out/"riss_candidates_466_v1_1_fresh.csv"; sp=out/"riss_search_summary_466_v1_1_fresh.json"
    if a.overwrite:
        for p in (ep,hp,qp,cp,sp):
            if p.exists(): p.unlink()
    cohort=read_csv(a.cohort); ids={r["ingredient_id"].strip() for r in cohort}
    if len(cohort)!=466 or len(ids)!=466: raise RissSearchError("Frozen RISS cohort must contain 466 unique ingredients")
    terms=build_approved_terms(ids,read_csv(a.ingredients),read_csv(a.aliases)); plan=build_plan(cohort,terms)
    if len(plan)!=477: raise RissSearchError(f"Expected 477 approved-term RISS executions, found {len(plan)}")
    robots,robots_at,robots_mono,delay=fetch_robots(a.timeout_seconds); client=RissClient(delay=delay,last_request_at=robots_mono,timeout=a.timeout_seconds,max_retries=a.max_retries)
    existing={r["execution_query_id"]:r for r in read_csv(ep)} if ep.exists() else {}; hits=read_csv(hp) if hp.exists() else []
    plan_order={str(x["execution_query_id"]):i for i,x in enumerate(plan)}
    def checkpoint() -> None:
        write_csv(ep,EXECUTION_FIELDS,sorted(existing.values(),key=lambda r:plan_order[r["execution_query_id"]]));write_csv(hp,HIT_FIELDS,hits)
    run_started=utc_now()
    for index,item in enumerate(plan,1):
        eid=str(item["execution_query_id"])
        if existing.get(eid,{}).get("request_status")=="success": continue
        row,new_hits=execute_one(item,client,robots,robots_at); existing[eid]=row; hits[:]=[x for x in hits if x["execution_query_id"]!=eid]+new_hits; checkpoint()
        if index%5==0: print(f"RISS {index}/477 success={sum(r['request_status']=='success' for r in existing.values())} errors={sum(r['request_status']!='success' for r in existing.values())}",file=sys.stderr,flush=True)
    for retry_round in range(1,a.final_retry_rounds+1):
        failed=[item for item in plan if existing.get(str(item["execution_query_id"]),{}).get("request_status")!="success"]
        if not failed: break
        print(f"RISS final retry round {retry_round}: {len(failed)} execution(s)",file=sys.stderr,flush=True)
        for item in failed:
            eid=str(item["execution_query_id"]);row,new_hits=execute_one(item,client,robots,robots_at);existing[eid]=row;hits[:]=[x for x in hits if x["execution_query_id"]!=eid]+new_hits;checkpoint()
    executions=sorted(existing.values(),key=lambda r:plan_order[r["execution_query_id"]]); candidates=dedupe_candidates(hits); queries=rollup(cohort,terms,executions,candidates,robots,robots_at)
    queries_by_ingredient={str(row["ingredient_id"]):row for row in queries}
    for candidate in candidates:
        query_row=queries_by_ingredient[str(candidate["ingredient_id"])]
        candidate["query_id"]=query_row["query_id"]
        candidate["query_sha256"]=query_row["query_sha256"]
        candidate["abstract"]=candidate["pre_abstract"]
    write_csv(qp,QUERY_FIELDS,queries);write_csv(cp,CANDIDATE_FIELDS,candidates);checkpoint()
    failures=[r for r in executions if r["request_status"]!="success"]
    summary={"source":"riss","pipeline_version":PIPELINE_VERSION,"query_version":QUERY_VERSION,"run_started_at_utc":run_started,"run_completed_at_utc":utc_now(),"frozen_cohort_row_count":len(cohort),"rollup_query_log_row_count":len(queries),"approved_term_execution_count":len(plan),"successful_execution_count":len(executions)-len(failures),"failed_execution_count":len(failures),"execution_pagination_status_counts":dict(Counter(r["pagination_status"] for r in executions)),"execution_raw_hit_sum":sum(int(r["raw_hit_count"] or 0) for r in executions),"execution_hit_row_count":len(hits),"deduplicated_candidate_row_count":len(candidates),"ingredients_with_candidates":len({r["ingredient_id"] for r in candidates}),"robots_url":RISS_ROBOTS_URL,"robots_fetched_at_utc":robots_at,"robots_sha256":text_sha256(robots),"robots_evidence_text":robots,"robots_crawl_delay_seconds":delay,"request_count":client.request_count,"retry_count":client.retry_count,"page_scale":PAGE_SCALE,"sort_order":"RANK","collection":"re_a_kor","input_sha256":{str(a.cohort):file_sha256(a.cohort),str(a.ingredients):file_sha256(a.ingredients),str(a.aliases):file_sha256(a.aliases)},"output_sha256":{p.name:file_sha256(p) for p in (ep,hp,qp,cp)},"review_status":"candidate_unverified","runtime_score_change":"none"}
    sp.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if len(executions)!=477 or len(queries)!=466 or failures: raise RissSearchError(f"RISS final invariant failed: executions={len(executions)} rollups={len(queries)} failures={len(failures)}")
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True));return 0


if __name__=="__main__": raise SystemExit(main())
