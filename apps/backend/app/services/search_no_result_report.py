import csv
import io
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.recommendation import RecommendationRun


DEFAULT_SCAN_LIMIT = 500
DEFAULT_TOP_N = 20


@dataclass(frozen=True)
class SearchNoResultReportEntry:
    recommendation_code: str
    concern_text: str
    created_at: datetime | None
    no_result_reason: str | None
    candidate_count: int
    join_document_count: int
    positive_search_match_count: int
    search_terms: tuple[str, ...]
    unmatched_terms: tuple[str, ...]
    alias_candidate_terms: tuple[str, ...]
    needs_alias_review: bool


@dataclass(frozen=True)
class SearchNoResultTermSummary:
    term: str
    count: int


@dataclass(frozen=True)
class SearchNoResultReport:
    scanned_run_count: int
    diagnostic_run_count: int
    alias_review_run_count: int
    reason_counts: dict[str, int]
    top_alias_candidate_terms: tuple[SearchNoResultTermSummary, ...]
    entries: tuple[SearchNoResultReportEntry, ...]


def build_search_no_result_report(
    session: Session,
    *,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
    top_n: int = DEFAULT_TOP_N,
) -> SearchNoResultReport:
    runs = list(
        session.execute(
            select(RecommendationRun)
            .order_by(desc(RecommendationRun.created_at), desc(RecommendationRun.id))
            .limit(max(0, scan_limit))
        ).scalars()
    )

    entries: list[SearchNoResultReportEntry] = []
    reason_counts: Counter[str] = Counter()
    alias_candidate_counts: Counter[str] = Counter()

    for run in runs:
        diagnostics = _search_no_result_diagnostics(run)
        if diagnostics is None:
            continue

        entry = _entry_from_run(run, diagnostics)
        if entry.no_result_reason:
            reason_counts[entry.no_result_reason] += 1
        alias_candidate_counts.update(entry.alias_candidate_terms)

        if entry.no_result_reason or entry.needs_alias_review:
            entries.append(entry)

    return SearchNoResultReport(
        scanned_run_count=len(runs),
        diagnostic_run_count=sum(1 for run in runs if _search_no_result_diagnostics(run) is not None),
        alias_review_run_count=sum(1 for entry in entries if entry.needs_alias_review),
        reason_counts=dict(reason_counts),
        top_alias_candidate_terms=tuple(
            SearchNoResultTermSummary(term=term, count=count)
            for term, count in alias_candidate_counts.most_common(max(0, top_n))
        ),
        entries=tuple(entries),
    )


def format_markdown_report(report: SearchNoResultReport) -> str:
    lines = [
        "# 검색 무결과/동의어 후보 리포트",
        "",
        f"- scanned_run_count: {report.scanned_run_count}",
        f"- diagnostic_run_count: {report.diagnostic_run_count}",
        f"- alias_review_run_count: {report.alias_review_run_count}",
        "",
        "## no_result_reason",
        "",
    ]

    if report.reason_counts:
        for reason, count in sorted(report.reason_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- 없음")

    lines.extend(["", "## alias 후보 상위", ""])
    if report.top_alias_candidate_terms:
        lines.extend(
            f"- {summary.term}: {summary.count}"
            for summary in report.top_alias_candidate_terms
        )
    else:
        lines.append("- 없음")

    lines.extend(
        [
            "",
            "## 상세",
            "",
            "| recommendation_id | reason | alias 후보 | unmatched | search_terms | input |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if report.entries:
        lines.extend(_entry_markdown_row(entry) for entry in report.entries)
    else:
        lines.append("| - | - | - | - | - | 진단 대상 없음 |")

    return "\n".join(lines)


def format_json_report(report: SearchNoResultReport) -> str:
    return json.dumps(
        {
            "scanned_run_count": report.scanned_run_count,
            "diagnostic_run_count": report.diagnostic_run_count,
            "alias_review_run_count": report.alias_review_run_count,
            "reason_counts": report.reason_counts,
            "top_alias_candidate_terms": [
                {"term": summary.term, "count": summary.count}
                for summary in report.top_alias_candidate_terms
            ],
            "entries": [
                {
                    "recommendation_id": entry.recommendation_code,
                    "concern_text": entry.concern_text,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                    "no_result_reason": entry.no_result_reason,
                    "candidate_count": entry.candidate_count,
                    "join_document_count": entry.join_document_count,
                    "positive_search_match_count": entry.positive_search_match_count,
                    "search_terms": list(entry.search_terms),
                    "unmatched_terms": list(entry.unmatched_terms),
                    "alias_candidate_terms": list(entry.alias_candidate_terms),
                    "needs_alias_review": entry.needs_alias_review,
                }
                for entry in report.entries
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def format_alias_candidates_csv(report: SearchNoResultReport) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "alias",
        "candidate_count",
        "no_result_reasons",
        "sample_recommendation_ids",
        "sample_inputs",
        "canonical_id",
        "review_status",
        "review_note",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for summary in report.top_alias_candidate_terms:
        related_entries = [
            entry
            for entry in report.entries
            if summary.term in entry.alias_candidate_terms
        ]
        writer.writerow(
            {
                "alias": summary.term,
                "candidate_count": summary.count,
                "no_result_reasons": _csv_join(
                    _dedupe(
                        [
                            entry.no_result_reason or ""
                            for entry in related_entries
                        ]
                    )
                ),
                "sample_recommendation_ids": _csv_join(
                    _dedupe(
                        [
                            entry.recommendation_code
                            for entry in related_entries
                        ]
                    )[:5]
                ),
                "sample_inputs": _csv_join(
                    _dedupe(
                        [
                            entry.concern_text
                            for entry in related_entries
                        ]
                    )[:3]
                ),
                "canonical_id": "",
                "review_status": "candidate",
                "review_note": "",
            }
        )

    return buffer.getvalue()


def _search_no_result_diagnostics(run: RecommendationRun) -> dict | None:
    request_context = run.request_context or {}
    if not isinstance(request_context, dict):
        return None
    diagnostics = request_context.get("search_no_result_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return diagnostics


def _entry_from_run(
    run: RecommendationRun,
    diagnostics: dict,
) -> SearchNoResultReportEntry:
    return SearchNoResultReportEntry(
        recommendation_code=run.recommendation_code,
        concern_text=run.concern_text,
        created_at=run.created_at,
        no_result_reason=_optional_str(diagnostics.get("no_result_reason")),
        candidate_count=_int_value(diagnostics.get("candidate_count")),
        join_document_count=_int_value(diagnostics.get("join_document_count")),
        positive_search_match_count=_int_value(diagnostics.get("positive_search_match_count")),
        search_terms=_string_items(diagnostics.get("search_terms")),
        unmatched_terms=_string_items(diagnostics.get("unmatched_terms")),
        alias_candidate_terms=_string_items(diagnostics.get("alias_candidate_terms")),
        needs_alias_review=bool(diagnostics.get("needs_alias_review")),
    )


def _entry_markdown_row(entry: SearchNoResultReportEntry) -> str:
    return (
        f"| {_clean_cell(entry.recommendation_code)} "
        f"| {_clean_cell(entry.no_result_reason or '-')} "
        f"| {_join_or_dash(entry.alias_candidate_terms)} "
        f"| {_join_or_dash(entry.unmatched_terms)} "
        f"| {_join_or_dash(entry.search_terms)} "
        f"| {_clean_cell(entry.concern_text)} |"
    )


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()

    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return tuple(items)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _join_or_dash(values: tuple[str, ...]) -> str:
    if not values:
        return "-"
    return ", ".join(_clean_cell(value) for value in values)


def _clean_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _csv_join(values: list[str]) -> str:
    return "; ".join(value for value in values if value)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped
