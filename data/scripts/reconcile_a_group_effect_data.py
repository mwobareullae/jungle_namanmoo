#!/usr/bin/env python3
"""Import the reviewed A-group effect matrix export into repo CSV schemas.

The source export is the human-reviewed A-group matrix:

- a_group_ingredient_effect.csv: canonical_id/effect_id/score/status rows
- a_group_ingredient_evidence.csv: canonical_id/effect_id/evidence text rows
- a_group_ingredient_effect_ranges.csv: ingredient-level concentration notes

The backend schema does not currently have role/tier/status columns, so those
review fields are preserved in evidence summaries and in a review CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


EFFECT_FILE = "a_group_ingredient_effect.csv"
EVIDENCE_FILE = "a_group_ingredient_evidence.csv"
RANGE_FILE = "a_group_ingredient_effect_ranges.csv"

EFFECT_NAMES = {
    "effect_brightening": "미백·톤",
    "effect_wrinkle": "주름·탄력",
    "effect_acne_sebum": "여드름·피지",
    "effect_moisture_barrier": "보습·장벽",
    "effect_calming": "진정",
    "effect_exfoliation": "각질",
}

REVIEW_FIELDS = [
    "canonical_id",
    "effect_id",
    "role",
    "tier",
    "status",
    "effect_score",
    "evidence_score",
    "evidence",
    "summary",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def materialize_export(source: Path, work_dir: Path) -> Path:
    if source.is_dir():
        return source

    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        archive.extractall(work_dir)

    nested_zip = work_dir / "a_group_matrix_export.zip"
    if nested_zip.exists():
        with zipfile.ZipFile(nested_zip) as archive:
            archive.extractall(work_dir)
    return work_dir


def load_export(export_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    effects = read_csv(export_dir / EFFECT_FILE)
    evidence = read_csv(export_dir / EVIDENCE_FILE)
    ranges = read_csv(export_dir / RANGE_FILE)

    require_fields(EFFECT_FILE, effects, {"canonical_id", "effect_id", "role", "tier", "effect_score", "evidence_score", "status"})
    require_fields(EVIDENCE_FILE, evidence, {"canonical_id", "effect_id", "evidence", "summary"})
    require_fields(RANGE_FILE, ranges, {"canonical_id", "name_ko", "concentration_range_text", "confidence"})
    return effects, evidence, ranges


def require_fields(file_name: str, rows: list[dict[str, str]], required: set[str]) -> None:
    if not rows:
        raise ValueError(f"{file_name} is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{file_name} missing columns: {', '.join(missing)}")


def repo_ingredient_ids(data_dir: Path) -> set[str]:
    return {row["ingredient_id"] for row in read_csv(data_dir / "ingredients.csv")}


def build_effect_rows(effects: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in effects:
        effect_id = row["effect_id"]
        if effect_id not in EFFECT_NAMES:
            raise ValueError(f"unknown effect_id: {effect_id}")
        rows.append(
            {
                "ingredient_id": row["canonical_id"],
                "effect_id": effect_id,
                "effect_name": EFFECT_NAMES[effect_id],
                "effect_score": row["effect_score"],
            }
        )
    return rows


def build_evidence_rows(
    effects: list[dict[str, str]],
    evidence: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    effect_by_key = {(row["canonical_id"], row["effect_id"]): row for row in effects}
    evidence_rows = []
    review_rows = []

    for row in evidence:
        key = (row["canonical_id"], row["effect_id"])
        effect = effect_by_key.get(key)
        if effect is None:
            raise ValueError(f"evidence row without effect row: {key}")

        evidence_score = int(effect["evidence_score"])
        source_title = compact_source_title(row["evidence"])
        summary = row["summary"].strip()
        metadata = f"role={effect['role']}; tier={effect['tier']}; status={effect['status']}"
        evidence_rows.append(
            {
                "ingredient_id": row["canonical_id"],
                "effect_id": row["effect_id"],
                "evidence_level": evidence_level(evidence_score),
                "evidence_score": str(evidence_score),
                "source_title": source_title,
                "source_url": source_url(row["evidence"]),
                "summary": f"{summary} ({metadata})" if summary else metadata,
                "source_type": source_type(row["evidence"]),
                "pmid": pmid(row["evidence"]),
                "doi": doi(row["evidence"]),
                "source_authority_score": source_authority_score(evidence_score),
            }
        )
        review_rows.append(
            {
                "canonical_id": row["canonical_id"],
                "effect_id": row["effect_id"],
                "role": effect["role"],
                "tier": effect["tier"],
                "status": effect["status"],
                "effect_score": effect["effect_score"],
                "evidence_score": effect["evidence_score"],
                "evidence": row["evidence"],
                "summary": row["summary"],
            }
        )
    return evidence_rows, review_rows


def build_range_rows(
    effects: list[dict[str, str]],
    ranges: list[dict[str, str]],
) -> list[dict[str, str]]:
    ranges_by_id = {row["canonical_id"]: row for row in ranges}
    rows = []
    for effect in effects:
        canonical_id = effect["canonical_id"]
        source = ranges_by_id.get(canonical_id)
        if source is None:
            raise ValueError(f"range row missing for canonical_id: {canonical_id}")
        parsed = parse_concentration_range(source["concentration_range_text"])
        source_confidence = normalize_confidence(source["confidence"])
        range_confidence = source_confidence if parsed else "unknown"
        rows.append(
            {
                "ingredient_id": canonical_id,
                "effect_id": effect["effect_id"],
                "unit": parsed["unit"] if parsed else "unknown",
                "meaningful_min": parsed["meaningful_min"] if parsed else "",
                "optimal_min": parsed["optimal_min"] if parsed else "",
                "optimal_max": parsed["optimal_max"] if parsed else "",
                "excessive_min": parsed["excessive_min"] if parsed else "",
                "range_confidence": range_confidence,
                "source_type": "unknown",
                "source_url": "",
                "note": f"source_confidence={source['confidence']}; {source['concentration_range_text']}",
            }
        )
    return rows


def parse_concentration_range(text: str) -> dict[str, str] | None:
    normalized = text.replace("％", "%")
    simple_range = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[~～]\s*(\d+(?:\.\d+)?)\s*%", normalized)
    if simple_range:
        low, high = simple_range.groups()
        return {
            "unit": "%",
            "meaningful_min": low,
            "optimal_min": low,
            "optimal_max": high,
            "excessive_min": "",
        }

    single_percent = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", normalized)
    if single_percent and any(token in normalized for token in ("고시", "임상", "통상", "사용")):
        value = single_percent.group(1)
        return {
            "unit": "%",
            "meaningful_min": value,
            "optimal_min": value,
            "optimal_max": value,
            "excessive_min": "",
        }

    return None


def normalize_confidence(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"med", "medium", "med-high"}:
        return "medium"
    if normalized in {"high", "low"}:
        return normalized
    return "unknown"


def evidence_level(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def compact_source_title(evidence: str) -> str:
    source = evidence.strip()
    return source if len(source) <= 240 else source[:237] + "..."


def source_url(evidence: str) -> str:
    found_pmid = pmid(evidence)
    if found_pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{found_pmid}/"
    if "식약처" in evidence or "고시" in evidence:
        return "https://www.mfds.go.kr/"
    return ""


def source_type(evidence: str) -> str:
    lowered = evidence.lower()
    if "pmid" in lowered or "rct" in lowered or "논문" in evidence:
        return "paper"
    if "식약처" in evidence or "고시" in evidence:
        return "mfds"
    return "unknown"


def pmid(evidence: str) -> str:
    match = re.search(r"PMID\s*:?\s*(\d{6,9})", evidence, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def doi(evidence: str) -> str:
    match = re.search(r"10\.\d{4,9}/[^\s,;]+", evidence)
    return match.group(0) if match else ""


def source_authority_score(score: int) -> str:
    if score >= 80:
        return "0.9"
    if score >= 60:
        return "0.7"
    return "0.5"


def validate(
    effects: list[dict[str, str]],
    evidence: list[dict[str, str]],
    ranges: list[dict[str, str]],
    ingredient_ids: set[str],
) -> None:
    effect_keys = [(row["ingredient_id"], row["effect_id"]) for row in effects]
    if len(effect_keys) != len(set(effect_keys)):
        raise ValueError("duplicate ingredient_effect keys")

    evidence_keys = [(row["ingredient_id"], row["effect_id"]) for row in evidence]
    if Counter(evidence_keys) != Counter(effect_keys):
        raise ValueError("evidence keys do not match effect keys")

    range_keys = [(row["ingredient_id"], row["effect_id"], row["unit"]) for row in ranges]
    if len(range_keys) != len(set(range_keys)):
        raise ValueError("duplicate ingredient_effect_range keys")

    orphans = sorted({row["ingredient_id"] for row in effects + evidence + ranges} - ingredient_ids)
    if orphans:
        raise ValueError(f"unknown canonical ids: {', '.join(orphans)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/Users/robertkim/Downloads/files.zip"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/a_group_matrix_export"))
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("data/reconciliation/a_group_effect_matrix_review.csv"),
    )
    parser.add_argument("--write", action="store_true", help="rewrite repo CSV files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_dir = materialize_export(args.source, args.work_dir)
    source_effects, source_evidence, source_ranges = load_export(export_dir)

    effect_rows = build_effect_rows(source_effects)
    evidence_rows, review_rows = build_evidence_rows(source_effects, source_evidence)
    range_rows = build_range_rows(source_effects, source_ranges)
    validate(effect_rows, evidence_rows, range_rows, repo_ingredient_ids(args.data_dir))

    status_counts = Counter(row["status"] for row in source_effects)
    ingredient_count = len({row["canonical_id"] for row in source_effects})
    unknown_ranges = sum(1 for row in range_rows if row["range_confidence"] == "unknown")
    print(f"effect rows: {len(effect_rows)}")
    print(f"evidence rows: {len(evidence_rows)}")
    print(f"range rows: {len(range_rows)} ({unknown_ranges} unknown numeric ranges)")
    print(f"ingredients: {ingredient_count}")
    print(f"status: {dict(status_counts)}")

    if args.write:
        write_csv(
            args.data_dir / "ingredient_effect.csv",
            ["ingredient_id", "effect_id", "effect_name", "effect_score"],
            effect_rows,
        )
        write_csv(
            args.data_dir / "ingredient_evidence.csv",
            [
                "ingredient_id",
                "effect_id",
                "evidence_level",
                "evidence_score",
                "source_title",
                "source_url",
                "summary",
                "source_type",
                "pmid",
                "doi",
                "source_authority_score",
            ],
            evidence_rows,
        )
        write_csv(
            args.data_dir / "ingredient_effect_ranges.csv",
            [
                "ingredient_id",
                "effect_id",
                "unit",
                "meaningful_min",
                "optimal_min",
                "optimal_max",
                "excessive_min",
                "range_confidence",
                "source_type",
                "source_url",
                "note",
            ],
            range_rows,
        )
        args.review_output.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.review_output, REVIEW_FIELDS, review_rows)
        print(f"wrote review: {args.review_output}")


if __name__ == "__main__":
    main()
