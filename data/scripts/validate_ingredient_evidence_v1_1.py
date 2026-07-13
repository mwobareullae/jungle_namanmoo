#!/usr/bin/env python3
"""Validate the completed v1.1 evidence-search and screening package.

The validator independently rebuilds the approved ingredient-term dictionary
and every source query.  It does not trust a source ledger merely because the
ledger labels its own terms or query as approved.  It also verifies raw-source
candidate linkage, pagination/access semantics, source summaries and hashes,
then checks the normalized screening ledgers.  It never changes runtime
evidence or scores; the only write performed by ``main`` is the QA JSON report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence


SOURCES = ("pubmed", "europe_pmc", "crossref", "openalex", "kci", "riss")
REQUIRED_RAW_SOURCES = ("pubmed", "europe_pmc", "crossref", "openalex", "kci")
OPTIONAL_RAW_SOURCES = ("riss",)
ALLOWED_ALIAS_TYPES = {"inci", "synonym", "en"}
PUBMED_SKIN_CONTEXT_TERMS = (
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
PROHIBITED_EFFECT_QUERY_RE = re.compile(
    r"\b(melanin(?: index)?|masi|wrinkl(?:e|es)|tewl|transepidermal water loss|"
    r"sebum|comedones?|lesion count|erythema index|corneometer|tewameter|"
    r"cutometer|hydration|moistur(?:e|ization)|elasticity|firmness|roughness|"
    r"desquamation|whitening|brightening)\b|미백|여드름|피지|주름|보습|진정|각질",
    re.IGNORECASE,
)
ALLOWED_PRIMARY_STATUSES = {
    "score_candidate_positive",
    "score_candidate_supporting",
    "negative_or_null",
    "new_effect_candidate",
    "abstract_insufficient",
    "formulation_only",
    "reject_wrong_scope",
}
COMMON_QUERY_FIELDS = {
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
    "review_status",
    "runtime_score_change",
    "pipeline_version",
}
COMMON_CANDIDATE_FIELDS = {
    "source",
    "ingredient_id",
    "review_status",
    "runtime_score_change",
    "pipeline_version",
}
STANDARD_LINKED_CANDIDATE_SOURCES = {
    "pubmed",
    "europe_pmc",
    "crossref",
    "openalex",
}
STANDARD_LINKED_CANDIDATE_FIELDS = {
    "query_id",
    "result_position",
    "query_sha256",
    "search_query",
    "canonical_name_en",
    "query_contract_status",
}


class ValidationError(RuntimeError):
    """Raised when one or more v1.1 invariants fail."""


def read_csv_with_fields(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def read_csv(path: Path) -> list[dict[str, str]]:
    return read_csv_with_fields(path)[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_true(
    checks: list[dict[str, object]],
    name: str,
    condition: bool,
    detail: object,
) -> None:
    checks.append({"check": name, "passed": bool(condition), "detail": detail})


def _is_approved_english_term(value: str) -> bool:
    value = value.strip()
    return value.isascii() and bool(re.search(r"[A-Za-z]", value)) and len(value) >= 2


def build_approved_term_bundle(
    ingredient_rows: Sequence[Mapping[str, str]],
    alias_rows: Sequence[Mapping[str, str]],
    ingredient_ids: Sequence[str] | set[str],
) -> tuple[dict[str, list[str]], dict[str, list[dict[str, str]]]]:
    """Rebuild approved terms independently from the two source dictionaries."""

    requested_ids = set(ingredient_ids)
    terms: dict[str, list[dict[str, str]]] = {
        ingredient_id: [] for ingredient_id in requested_ids
    }
    master_seen: set[str] = set()
    for row in ingredient_rows:
        ingredient_id = row.get("ingredient_id", "").strip()
        if ingredient_id not in requested_ids:
            continue
        master_seen.add(ingredient_id)
        for raw_term in row.get("name_en", "").split("|"):
            term = re.sub(r"\s+", " ", raw_term.strip())
            if not _is_approved_english_term(term):
                continue
            terms[ingredient_id].append(
                {
                    "term": term,
                    "origin": "canonical_name_en",
                    "alias_type": "",
                    "source": row.get("source_url", "").strip(),
                }
            )

    missing_master = sorted(requested_ids - master_seen)
    if missing_master:
        raise ValidationError(
            "Frozen cohort ingredient IDs are missing from data/ingredients.csv: "
            + "|".join(missing_master)
        )

    for row in alias_rows:
        ingredient_id = row.get("canonical_id", "").strip()
        if ingredient_id not in requested_ids:
            continue
        alias_type = row.get("alias_type", "").strip().casefold()
        if row.get("confidence", "").strip().casefold() != "high":
            continue
        if alias_type not in ALLOWED_ALIAS_TYPES:
            continue
        for raw_alias in row.get("alias", "").split("|"):
            alias = re.sub(r"\s+", " ", raw_alias.strip())
            if not _is_approved_english_term(alias):
                continue
            terms[ingredient_id].append(
                {
                    "term": alias,
                    "origin": "approved_alias",
                    "alias_type": alias_type,
                    "source": row.get("source", "").strip(),
                }
            )

    approved: dict[str, list[str]] = {}
    provenance: dict[str, list[dict[str, str]]] = {}
    for ingredient_id in requested_ids:
        selected: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in terms[ingredient_id]:
            key = value["term"].casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(value)
        if not selected:
            raise ValidationError(
                "No canonical or approved high-confidence English term for "
                f"{ingredient_id}; ingredient_id fallback is forbidden"
            )
        provenance[ingredient_id] = selected
        approved[ingredient_id] = [value["term"] for value in selected]
    return approved, provenance


def _clean_quoted_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('"', " ")).strip()


def expected_source_query(source: str, terms: Sequence[str]) -> str:
    """Return the exact v1.1 query serialized by each source collector."""

    cleaned = [_clean_quoted_term(term) for term in terms]
    if not cleaned or any(not value for value in cleaned):
        raise ValidationError(f"Cannot build {source} query from empty approved term")
    if source == "pubmed":
        ingredient_clause = " OR ".join(
            f'"{term}"[Title/Abstract]' for term in cleaned
        )
        context_clause = " OR ".join(
            f'"{term}"[Title/Abstract]' for term in PUBMED_SKIN_CONTEXT_TERMS
        )
        return f"({ingredient_clause}) AND ({context_clause})"
    if source == "europe_pmc":
        ingredient_clause = " OR ".join(
            f'TITLE_ABS:"{term}"' for term in cleaned
        )
        context_clause = 'TITLE_ABS:"skin" OR TITLE_ABS:"topical"'
        return (
            f"({ingredient_clause}) AND ({context_clause}) "
            "AND NOT SRC:MED AND NOT SRC:PAT"
        )
    if source in {"crossref", "openalex"}:
        ingredient_clause = " OR ".join(f'"{term}"' for term in cleaned)
        return f"({ingredient_clause}) skin topical"
    if source in {"kci", "riss"}:
        planned_queries = [f'"{term}" skin' for term in cleaned]
        return json.dumps(
            planned_queries,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    raise ValidationError(f"Unsupported source query contract: {source}")


def _decode_approved_terms(value: str) -> list[str]:
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return [item.strip() for item in raw.split("|") if item.strip()]


def _strip_expected_terms(query: str, expected_terms: Sequence[str]) -> str:
    stripped = query
    for term in sorted(set(expected_terms), key=len, reverse=True):
        stripped = re.sub(re.escape(term), "", stripped, flags=re.IGNORECASE)
    return stripped


def _integer(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _first_integer(mapping: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        if key in mapping:
            value = _integer(mapping.get(key))
            if value is not None:
                return value
    return None


def _log_semantic_errors(row: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    status = row.get("request_status", "").strip().casefold()
    pagination = row.get("pagination_status", "").strip().casefold()
    pagination_complete = row.get("pagination_complete", "").strip().upper()
    retrieval_complete = row.get("retrieval_complete", "").strip().upper()
    rerun = row.get("rerun_required", "").strip().upper()
    total = _first_integer(row, "total_hit_count", "raw_hit_count")
    raw = _integer(row.get("raw_hit_count"))
    retrieved = _first_integer(row, "retrieved_count", "returned_count")
    returned = _integer(row.get("returned_count"))
    cap = _integer(row.get("retrieval_cap"))

    if total is not None and raw is not None and total != raw:
        errors.append("total_hit_count != raw_hit_count")
    if retrieved is not None and returned is not None and retrieved != returned:
        errors.append("retrieved_count != returned_count")
    if returned is not None and returned < 0:
        errors.append("returned_count is negative")
    if cap is not None and returned is not None and returned > cap:
        errors.append("returned_count exceeds retrieval_cap")

    if status in {"success", "ok", "completed", "zero_results"}:
        if rerun != "N":
            errors.append("settled success/cap row must have rerun_required=N")
        if pagination == "complete":
            if pagination_complete != "Y":
                errors.append("complete row must have pagination_complete=Y")
            if retrieval_complete and retrieval_complete != "Y":
                errors.append("complete row must have retrieval_complete=Y")
            if total is None or returned is None or total != returned:
                errors.append("complete row must return all reported hits")
        elif "cap" in pagination:
            if pagination_complete != "N":
                errors.append("capped row must have pagination_complete=N")
            if retrieval_complete and retrieval_complete != "N":
                errors.append("capped row must have retrieval_complete=N")
            if total is None or returned is None or total <= returned:
                errors.append("capped row must report more hits than returned")
            if cap is None or returned is None or returned != cap:
                errors.append("capped row must return the declared retrieval cap")
        else:
            errors.append("successful row has neither complete nor capped pagination")
    elif status in {
        "access_unavailable",
        "blocked_by_robots",
        "credentials_unavailable",
    }:
        if rerun != "N":
            errors.append("structural access row must have rerun_required=N")
        if not (pagination == "not_applicable" or pagination.startswith("not_run")):
            errors.append("access row pagination_status must be not_applicable/not_run")
        if pagination_complete not in {"N", "NOT_APPLICABLE"}:
            errors.append("access row pagination_complete must be N/not_applicable")
        if total not in {None, 0} or raw not in {None, 0}:
            errors.append("access row must not claim source hits")
        if retrieved not in {None, 0} or returned not in {None, 0}:
            errors.append("access row must not claim retrieved candidates")
        if not row.get("error_type", "").strip() or not row.get(
            "error_message", ""
        ).strip():
            errors.append("access row must preserve error evidence")
    else:
        if rerun != "Y":
            errors.append("unsettled request error must have rerun_required=Y")
    return errors


def _source_paths(fresh_dir: Path, source: str) -> dict[str, Path]:
    return {
        "query_log": fresh_dir / f"{source}_query_log_466_v1_1_fresh.csv",
        "candidates": fresh_dir / f"{source}_candidates_466_v1_1_fresh.csv",
        "summary": fresh_dir / f"{source}_search_summary_466_v1_1_fresh.json",
    }


def _summary_declared_sha(
    summary: Mapping[str, object],
    path: Path,
    *,
    kind: str,
) -> str:
    output_sha = summary.get("output_sha256")
    if isinstance(output_sha, Mapping):
        value = output_sha.get(path.name)
        if value:
            return str(value)
    direct_key = (
        "search_log_file_sha256" if kind == "query_log" else "candidate_file_sha256"
    )
    return str(summary.get(direct_key) or "")


def _summary_count(
    summary: Mapping[str, object],
    *,
    kind: str,
) -> int | None:
    if kind == "query_log":
        return _first_integer(
            summary,
            "query_log_row_count",
            "logged_ingredient_count",
            "frozen_cohort_row_count",
        )
    return _first_integer(
        summary,
        "candidate_row_count",
        "retrieved_ingredient_pmid_row_count",
    )


def validate_source_package(
    *,
    source: str,
    fresh_dir: Path,
    manifest_rows: Sequence[Mapping[str, str]],
    approved_terms: Mapping[str, Sequence[str]],
    approved_provenance: Mapping[str, Sequence[Mapping[str, str]]],
    checks: list[dict[str, object]],
    raw_sha256: dict[str, str],
    optional: bool = False,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    paths = _source_paths(fresh_dir, source)
    existence = {name: path.exists() for name, path in paths.items()}
    if optional and not any(existence.values()):
        assert_true(
            checks,
            f"{source}_raw_package_optional_absent",
            True,
            existence,
        )
        return {"present": False}, []
    package_complete = all(existence.values())
    assert_true(
        checks,
        f"{source}_raw_package_present",
        package_complete,
        existence,
    )
    if not package_complete:
        for path in paths.values():
            if path.exists():
                raw_sha256[str(path)] = sha256(path)
        return {"present": False, "partial": True}, []

    query_fields, query_rows = read_csv_with_fields(paths["query_log"])
    candidate_fields, candidate_rows = read_csv_with_fields(paths["candidates"])
    raw_sha256.update(
        {
            str(paths["query_log"]): sha256(paths["query_log"]),
            str(paths["candidates"]): sha256(paths["candidates"]),
            str(paths["summary"]): sha256(paths["summary"]),
        }
    )
    try:
        summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        assert_true(checks, f"{source}_summary_valid_json", False, str(exc))
        summary = {}
    if not isinstance(summary, Mapping):
        assert_true(
            checks,
            f"{source}_summary_json_object",
            False,
            type(summary).__name__,
        )
        summary = {}

    missing_query_fields = sorted(COMMON_QUERY_FIELDS - set(query_fields))
    assert_true(
        checks,
        f"{source}_query_schema",
        not missing_query_fields,
        {"missing": missing_query_fields, "fields": query_fields},
    )
    missing_candidate_fields = sorted(COMMON_CANDIDATE_FIELDS - set(candidate_fields))
    if source in STANDARD_LINKED_CANDIDATE_SOURCES:
        missing_candidate_fields.extend(
            sorted(STANDARD_LINKED_CANDIDATE_FIELDS - set(candidate_fields))
        )
    assert_true(
        checks,
        f"{source}_candidate_schema",
        not missing_candidate_fields,
        {"missing": sorted(set(missing_candidate_fields)), "fields": candidate_fields},
    )

    manifest_ids = [row.get("ingredient_id", "") for row in manifest_rows]
    manifest_by_id = {row.get("ingredient_id", ""): row for row in manifest_rows}
    source_ids = [row.get("ingredient_id", "") for row in query_rows]
    assert_true(
        checks,
        f"{source}_query_log_manifest_order",
        len(query_rows) == len(manifest_ids) and source_ids == manifest_ids,
        {
            "rows": len(query_rows),
            "expected": len(manifest_ids),
            "ordered_manifest_match": source_ids == manifest_ids,
        },
    )
    query_ids = [row.get("query_id", "") for row in query_rows]
    assert_true(
        checks,
        f"{source}_query_ids_nonblank_unique",
        all(query_ids) and len(query_ids) == len(set(query_ids)),
        {"rows": len(query_ids), "unique": len(set(query_ids))},
    )

    term_violations: list[dict[str, object]] = []
    query_violations: list[dict[str, object]] = []
    state_violations: list[dict[str, object]] = []
    query_by_id: dict[str, Mapping[str, str]] = {}
    for row in query_rows:
        ingredient_id = row.get("ingredient_id", "")
        query_id = row.get("query_id", "")
        if query_id:
            query_by_id[query_id] = row
        if ingredient_id not in approved_terms or ingredient_id not in manifest_by_id:
            term_violations.append(
                {"ingredient_id": ingredient_id, "reason": "outside_manifest_or_dictionary"}
            )
            continue
        expected_terms = list(approved_terms[ingredient_id])
        declared_terms = _decode_approved_terms(row.get("approved_search_terms", ""))
        if declared_terms != expected_terms:
            term_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "declared": declared_terms,
                    "expected": expected_terms,
                }
            )
        if row.get("canonical_name_en", "") != expected_terms[0]:
            term_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "canonical_name_en": row.get("canonical_name_en", ""),
                    "expected_canonical": expected_terms[0],
                }
            )
        if row.get("term_provenance_json", ""):
            try:
                declared_provenance = json.loads(row["term_provenance_json"])
            except json.JSONDecodeError:
                declared_provenance = "invalid_json"
            if declared_provenance != list(approved_provenance[ingredient_id]):
                term_violations.append(
                    {
                        "ingredient_id": ingredient_id,
                        "reason": "term_provenance_mismatch",
                    }
                )
        elif source in STANDARD_LINKED_CANDIDATE_SOURCES:
            term_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "reason": "term_provenance_json_missing",
                }
            )

        expected_query = expected_source_query(source, expected_terms)
        expected_sha = text_sha256(expected_query)
        expected_query_id = f"{source}:{ingredient_id}:{expected_sha[:16]}"
        if row.get("search_query", "") != expected_query:
            query_violations.append(
                {"ingredient_id": ingredient_id, "reason": "query_mismatch"}
            )
        if row.get("query_sha256", "") != expected_sha:
            query_violations.append(
                {"ingredient_id": ingredient_id, "reason": "query_sha256_mismatch"}
            )
        if row.get("query_id", "") != expected_query_id:
            query_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "reason": "query_id_not_source_ingredient_sha_prefix",
                    "actual": row.get("query_id", ""),
                    "expected": expected_query_id,
                }
            )
        context_only = _strip_expected_terms(expected_query, expected_terms)
        effect_match = PROHIBITED_EFFECT_QUERY_RE.search(context_only)
        if effect_match:
            query_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "reason": "prohibited_effect_term",
                    "term": effect_match.group(0),
                }
            )
        for reason in _log_semantic_errors(row):
            state_violations.append(
                {"ingredient_id": ingredient_id, "reason": reason}
            )
        if row.get("source", "") != source:
            state_violations.append(
                {"ingredient_id": ingredient_id, "reason": "source_mismatch"}
            )
        if row.get("query_contract_status", "") != "approved_terms_only":
            state_violations.append(
                {"ingredient_id": ingredient_id, "reason": "query_contract_not_approved"}
            )
        if row.get("review_status", "") != "candidate_unverified":
            state_violations.append(
                {"ingredient_id": ingredient_id, "reason": "review_status_changed"}
            )
        if row.get("runtime_score_change", "") != "none":
            state_violations.append(
                {"ingredient_id": ingredient_id, "reason": "runtime_score_changed"}
            )

    assert_true(
        checks,
        f"{source}_approved_terms_match_dictionary",
        not term_violations,
        term_violations[:20],
    )
    assert_true(
        checks,
        f"{source}_query_reconstruction_and_sha",
        not query_violations,
        query_violations[:20],
    )
    assert_true(
        checks,
        f"{source}_access_cap_rerun_truth_table",
        not state_violations,
        state_violations[:20],
    )

    candidate_violations: list[dict[str, object]] = []
    candidate_counts: Counter[str] = Counter()
    candidate_positions: dict[str, list[int]] = defaultdict(list)
    for row in candidate_rows:
        ingredient_id = row.get("ingredient_id", "")
        candidate_counts[ingredient_id] += 1
        if row.get("source", "") != source:
            candidate_violations.append(
                {"ingredient_id": ingredient_id, "reason": "source_mismatch"}
            )
        if ingredient_id not in manifest_by_id:
            candidate_violations.append(
                {"ingredient_id": ingredient_id, "reason": "outside_manifest"}
            )
        if row.get("review_status", "") != "candidate_unverified":
            candidate_violations.append(
                {"ingredient_id": ingredient_id, "reason": "review_status_changed"}
            )
        if row.get("runtime_score_change", "") != "none":
            candidate_violations.append(
                {"ingredient_id": ingredient_id, "reason": "runtime_score_changed"}
            )
        if source in STANDARD_LINKED_CANDIDATE_SOURCES:
            query = query_by_id.get(row.get("query_id", ""))
            if query is None:
                candidate_violations.append(
                    {"ingredient_id": ingredient_id, "reason": "unknown_query_id"}
                )
                continue
            for field in (
                "source",
                "ingredient_id",
                "canonical_name_en",
                "search_query",
                "query_sha256",
            ):
                if row.get(field, "") != query.get(field, ""):
                    candidate_violations.append(
                        {
                            "ingredient_id": ingredient_id,
                            "reason": f"candidate_query_{field}_mismatch",
                        }
                    )
            if row.get("query_contract_status", "") != "approved_terms_only":
                candidate_violations.append(
                    {
                        "ingredient_id": ingredient_id,
                        "reason": "candidate_query_contract_not_approved",
                    }
                )
            position = _integer(row.get("result_position"))
            if position is None or position <= 0:
                candidate_violations.append(
                    {"ingredient_id": ingredient_id, "reason": "invalid_result_position"}
                )
            else:
                candidate_positions[ingredient_id].append(position)
        elif candidate_rows:
            execution_ids = [
                value
                for value in row.get("execution_query_ids", "").split("|")
                if value
            ]
            if not execution_ids or any(value not in query_by_id for value in execution_ids):
                candidate_violations.append(
                    {
                        "ingredient_id": ingredient_id,
                        "reason": "regional_candidate_query_link_missing",
                    }
                )

    for row in query_rows:
        ingredient_id = row.get("ingredient_id", "")
        returned = _integer(row.get("returned_count"))
        if returned is None:
            candidate_violations.append(
                {"ingredient_id": ingredient_id, "reason": "returned_count_not_integer"}
            )
        elif source in STANDARD_LINKED_CANDIDATE_SOURCES or not candidate_rows:
            if candidate_counts[ingredient_id] != returned:
                candidate_violations.append(
                    {
                        "ingredient_id": ingredient_id,
                        "reason": "candidate_count_not_returned_count",
                        "candidate_count": candidate_counts[ingredient_id],
                        "returned_count": returned,
                    }
                )
        positions = sorted(candidate_positions.get(ingredient_id, []))
        if positions and positions != list(range(1, len(positions) + 1)):
            candidate_violations.append(
                {
                    "ingredient_id": ingredient_id,
                    "reason": "result_positions_not_contiguous",
                }
            )
    assert_true(
        checks,
        f"{source}_candidate_query_linkage_and_counts",
        not candidate_violations,
        candidate_violations[:20],
    )

    summary_violations: list[dict[str, object]] = []
    if summary.get("source") != source:
        summary_violations.append(
            {"reason": "summary_source_mismatch", "actual": summary.get("source")}
        )
    if summary.get("review_status") != "candidate_unverified":
        summary_violations.append({"reason": "summary_review_status_changed"})
    if summary.get("runtime_score_change") != "none":
        summary_violations.append({"reason": "summary_runtime_score_changed"})
    for kind in ("query_log", "candidates"):
        path = paths[kind]
        declared_sha = _summary_declared_sha(summary, path, kind=kind)
        actual_sha = raw_sha256[str(path)]
        if declared_sha != actual_sha:
            summary_violations.append(
                {
                    "reason": f"{kind}_sha_mismatch",
                    "declared": declared_sha,
                    "actual": actual_sha,
                }
            )
        declared_count = _summary_count(summary, kind=kind)
        actual_count = len(query_rows) if kind == "query_log" else len(candidate_rows)
        if declared_count != actual_count:
            summary_violations.append(
                {
                    "reason": f"{kind}_count_mismatch",
                    "declared": declared_count,
                    "actual": actual_count,
                }
            )
    assert_true(
        checks,
        f"{source}_summary_counts_and_sha",
        not summary_violations,
        summary_violations[:20],
    )

    return (
        {
            "present": True,
            "query_log_rows": len(query_rows),
            "candidate_rows": len(candidate_rows),
            "request_statuses": dict(
                Counter(row.get("request_status", "") for row in query_rows)
            ),
            "pagination_statuses": dict(
                Counter(row.get("pagination_status", "") for row in query_rows)
            ),
        },
        query_rows,
    )


def _expected_normalized_search_status(row: Mapping[str, str]) -> str:
    status = row.get("request_status", "").strip().casefold()
    pagination = row.get("pagination_status", "").strip().casefold()
    total = _first_integer(row, "total_hit_count", "raw_hit_count") or 0
    if status in {
        "access_unavailable",
        "blocked_by_robots",
        "credentials_unavailable",
    }:
        return "access_unavailable"
    if status not in {"success", "ok", "completed", "zero_results"}:
        return "technical_failure"
    if total == 0:
        return "zero_results"
    if "cap" in pagination:
        return "success_protocol_capped"
    if pagination == "complete":
        return "success"
    return "partial"


def validate(args: argparse.Namespace) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    manifest = read_csv(args.v1_manifest)
    ingredients = read_csv(args.ingredient_ledger)
    papers = read_csv(args.paper_ledger)
    outcomes = read_csv(args.outcome_ledger)
    searches = read_csv(args.search_ledger)

    manifest_ids = [row.get("ingredient_id", "") for row in manifest]
    ingredient_ids = [row.get("ingredient_id", "") for row in ingredients]
    assert_true(
        checks,
        "frozen_manifest_466_unique",
        len(manifest_ids) == 466 and len(set(manifest_ids)) == 466 and all(manifest_ids),
        {"rows": len(manifest_ids), "unique": len(set(manifest_ids))},
    )
    assert_true(
        checks,
        "ingredient_ledger_matches_frozen_manifest",
        ingredient_ids == manifest_ids,
        {"rows": len(ingredient_ids), "exact_order_match": ingredient_ids == manifest_ids},
    )

    approved_terms, approved_provenance = build_approved_term_bundle(
        read_csv(args.ingredients),
        read_csv(args.aliases),
        manifest_ids,
    )
    search_pairs = [(row.get("ingredient_id", ""), row.get("source", "")) for row in searches]
    expected_pairs = {(ingredient_id, source) for ingredient_id in manifest_ids for source in SOURCES}
    assert_true(
        checks,
        "search_ledger_466_by_6",
        len(searches) == 466 * 6 and set(search_pairs) == expected_pairs,
        {"rows": len(searches), "unique_pairs": len(set(search_pairs))},
    )
    assert_true(
        checks,
        "search_pairs_unique",
        len(search_pairs) == len(set(search_pairs)),
        {"duplicate_count": len(search_pairs) - len(set(search_pairs))},
    )
    assert_true(
        checks,
        "fresh_queries_use_approved_terms",
        all(row.get("query_contract_status") == "approved_terms_only" for row in searches),
        dict(Counter(row.get("query_contract_status", "") for row in searches)),
    )
    assert_true(
        checks,
        "no_source_retry_required",
        all(row.get("rerun_required") == "N" for row in searches),
        dict(Counter(row.get("rerun_required", "") for row in searches)),
    )

    raw_sha256: dict[str, str] = {
        str(args.ingredients): sha256(args.ingredients),
        str(args.aliases): sha256(args.aliases),
    }
    source_package_status: dict[str, dict[str, object]] = {}
    source_query_logs: dict[str, list[dict[str, str]]] = {}
    for source in SOURCES:
        status, rows = validate_source_package(
            source=source,
            fresh_dir=args.fresh_dir,
            manifest_rows=manifest,
            approved_terms=approved_terms,
            approved_provenance=approved_provenance,
            checks=checks,
            raw_sha256=raw_sha256,
            optional=source in OPTIONAL_RAW_SOURCES,
        )
        source_package_status[source] = status
        if rows:
            source_query_logs[source] = rows

    normalized_by_pair = {
        (row.get("ingredient_id", ""), row.get("source", "")): row
        for row in searches
    }
    normalized_violations: list[dict[str, object]] = []
    for source, rows in source_query_logs.items():
        for raw in rows:
            ingredient_id = raw.get("ingredient_id", "")
            normalized = normalized_by_pair.get((ingredient_id, source))
            if normalized is None:
                normalized_violations.append(
                    {"source": source, "ingredient_id": ingredient_id, "reason": "missing"}
                )
                continue
            expected_name = approved_terms[ingredient_id][0]
            expected_raw = _first_integer(raw, "raw_hit_count", "total_hit_count") or 0
            expected_retrieved = _first_integer(raw, "returned_count", "retrieved_count") or 0
            expected_status = _expected_normalized_search_status(raw)
            expected_pagination = (
                "not_applicable"
                if expected_status == "access_unavailable"
                else "false"
                if expected_status in {"success_protocol_capped", "partial"}
                else "true"
            )
            comparisons = {
                "searched_name": (normalized.get("searched_name", ""), expected_name),
                "query": (normalized.get("query", ""), raw.get("search_query", "")),
                "raw_count": (str(normalized.get("raw_count", "")), str(expected_raw)),
                "retrieved_count": (
                    str(normalized.get("retrieved_count", "")),
                    str(expected_retrieved),
                ),
                "pagination_complete": (
                    normalized.get("pagination_complete", ""),
                    expected_pagination,
                ),
                "search_status": (
                    normalized.get("search_status", ""),
                    expected_status,
                ),
                "query_contract_status": (
                    normalized.get("query_contract_status", ""),
                    "approved_terms_only",
                ),
                "rerun_required": (normalized.get("rerun_required", ""), "N"),
            }
            for field, (actual, expected) in comparisons.items():
                if actual != expected:
                    normalized_violations.append(
                        {
                            "source": source,
                            "ingredient_id": ingredient_id,
                            "field": field,
                            "actual": actual,
                            "expected": expected,
                        }
                    )
    assert_true(
        checks,
        "normalized_search_ledger_matches_raw_sources",
        not normalized_violations,
        normalized_violations[:30],
    )

    paper_counts = Counter(row.get("ingredient_id", "") for row in papers)
    assert_true(
        checks,
        "representative_limit_three_per_ingredient",
        all(count <= 3 for count in paper_counts.values()),
        {"max": max(paper_counts.values(), default=0), "rows": len(papers)},
    )
    paper_keys = [
        (row.get("ingredient_id", ""), row.get("paper_key", "")) for row in papers
    ]
    assert_true(
        checks,
        "representative_keys_unique_within_ingredient",
        len(paper_keys) == len(set(paper_keys)),
        {"duplicate_count": len(paper_keys) - len(set(paper_keys))},
    )
    outcome_ids = [row.get("outcome_result_id", "") for row in outcomes]
    assert_true(
        checks,
        "outcome_result_ids_nonblank_unique",
        bool(outcome_ids) and all(outcome_ids) and len(outcome_ids) == len(set(outcome_ids)),
        {"rows": len(outcome_ids), "unique": len(set(outcome_ids))},
    )
    assert_true(
        checks,
        "primary_status_domain",
        all(row.get("primary_status") in ALLOWED_PRIMARY_STATUSES for row in ingredients),
        dict(Counter(row.get("primary_status", "") for row in ingredients)),
    )

    output_sets: Sequence[tuple[str, Sequence[Mapping[str, str]]]] = (
        ("ingredient", ingredients),
        ("paper", papers),
        ("outcome", outcomes),
        ("search", searches),
    )
    for name, rows in output_sets:
        assert_true(
            checks,
            f"{name}_candidate_unverified",
            all(row.get("review_status") == "candidate_unverified" for row in rows),
            dict(Counter(row.get("review_status", "") for row in rows)),
        )
        assert_true(
            checks,
            f"{name}_runtime_unchanged",
            all(row.get("runtime_score_change") == "none" for row in rows),
            dict(Counter(row.get("runtime_score_change", "") for row in rows)),
        )
    assert_true(
        checks,
        "automatic_rows_not_scoreable",
        all(row.get("score_status") == "not_scoreable" for row in ingredients)
        and all(row.get("score_status") == "not_scoreable" for row in papers)
        and all(row.get("score_status") == "not_scoreable" for row in outcomes),
        {
            "ingredient": dict(Counter(row.get("score_status", "") for row in ingredients)),
            "paper": dict(Counter(row.get("score_status", "") for row in papers)),
            "outcome": dict(Counter(row.get("score_status", "") for row in outcomes)),
        },
    )

    core_sha256 = {
        str(args.v1_manifest): sha256(args.v1_manifest),
        str(args.ingredient_ledger): sha256(args.ingredient_ledger),
        str(args.paper_ledger): sha256(args.paper_ledger),
        str(args.outcome_ledger): sha256(args.outcome_ledger),
        str(args.search_ledger): sha256(args.search_ledger),
    }
    failed_checks = [row for row in checks if not row["passed"]]
    return {
        "validation_status": "pass" if not failed_checks else "fail",
        "check_count": len(checks),
        "passed_check_count": len(checks) - len(failed_checks),
        "failed_check_count": len(failed_checks),
        "checks": checks,
        "failed_checks": failed_checks,
        "source_packages": source_package_status,
        "row_counts": {
            "ingredients": len(ingredients),
            "representative_papers": len(papers),
            "outcome_results": len(outcomes),
            "search_runs": len(searches),
        },
        "input_sha256": {**core_sha256, **raw_sha256},
        "runtime_changed": False,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    reconciliation = Path("data/reconciliation")
    parser.add_argument(
        "--v1-manifest",
        type=Path,
        default=reconciliation / "ingredient_evidence_adjudication_466.csv",
    )
    parser.add_argument(
        "--ingredient-ledger",
        type=Path,
        default=reconciliation / "ingredient_evidence_adjudication_466_v1_1.csv",
    )
    parser.add_argument(
        "--paper-ledger",
        type=Path,
        default=reconciliation / "ingredient_evidence_representatives_466_v1_1.csv",
    )
    parser.add_argument(
        "--outcome-ledger",
        type=Path,
        default=reconciliation / "ingredient_evidence_outcome_results_466_v1_1.csv",
    )
    parser.add_argument(
        "--search-ledger",
        type=Path,
        default=reconciliation / "ingredient_evidence_search_runs_466_v1_1.csv",
    )
    parser.add_argument(
        "--fresh-dir",
        type=Path,
        default=reconciliation / "v1_1_fresh",
    )
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument(
        "--aliases", type=Path, default=Path("data/ingredient_aliases.csv")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=reconciliation / "ingredient_evidence_v1_1_validation.json",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    result = validate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["validation_status"] != "pass":
        raise ValidationError(
            f"v1.1 validation failed: {result['failed_check_count']} check(s); "
            f"inspect {args.output}"
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
