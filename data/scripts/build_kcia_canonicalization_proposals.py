#!/usr/bin/env python3
"""Match pending ingredient ids to the official KCIA standard-name list.

This script creates a review proposal only. It never edits ingredients.csv,
ingredient_aliases.csv, product ingredient shards, or runtime scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


PROPOSAL_FIELDS = [
    "rank",
    "source_ingredient_id",
    "dominant_name",
    "row_count",
    "product_count",
    "kcia_ingredient_code",
    "kcia_standard_name_ko",
    "kcia_standard_name_en",
    "kcia_old_names_ko",
    "kcia_old_names_en",
    "official_match_status",
    "official_matched_row_count",
    "official_match_ratio",
    "official_conflict_codes",
    "proposed_action",
    "proposed_canonical_id",
    "related_scoring_family_ids",
    "selected_for_target",
    "proposal_confidence",
    "review_status",
    "proposal_note",
    "source_document_date",
    "source_document_sha256",
]

HEADER_CODE = "성분코드"
SOURCE_DOCUMENT_DATE = "2026-06-30"
SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_CANONICAL_ID_LENGTH = 64
MIN_AUTOMATIC_MATCH_RATIO = 0.90


@dataclass(frozen=True)
class KciaIngredient:
    code: str
    standard_name_ko: str
    standard_name_en: str
    old_names_ko: str
    old_names_en: str

    def aliases(self) -> tuple[str, ...]:
        values = [self.standard_name_ko, self.standard_name_en]
        values.extend(split_aliases(self.old_names_ko))
        values.extend(split_aliases(self.old_names_en))
        return tuple(value for value in values if value)


def clean_cell(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def split_aliases(value: str) -> list[str]:
    return [clean_cell(part) for part in value.split("|") if clean_cell(part)]


def normalize_match(value: str) -> str:
    normalized = clean_cell(value).casefold()
    return "".join(normalized.split())


def parse_kcia_pdf(path: Path) -> list[KciaIngredient]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - depends on local data tooling
        raise RuntimeError("KCIA PDF parsing requires pdfplumber") from exc

    records: list[KciaIngredient] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 5:
                        continue
                    code = clean_cell(row[0])
                    if code == HEADER_CODE or not code.isdigit():
                        continue
                    records.append(
                        KciaIngredient(
                            code=code,
                            standard_name_ko=clean_cell(row[1]),
                            standard_name_en=clean_cell(row[2]),
                            old_names_ko=clean_cell(row[3]),
                            old_names_en=clean_cell(row[4]),
                        )
                    )

    codes = [record.code for record in records]
    if len(records) < 20_000:
        raise ValueError(f"KCIA 표준 목록 추출 건수가 비정상적으로 적습니다: {len(records)}")
    if len(codes) != len(set(codes)):
        raise ValueError("KCIA 표준 목록에 중복 성분코드가 있습니다")
    return records


def build_official_index(
    records: list[KciaIngredient],
) -> dict[str, tuple[KciaIngredient, ...]]:
    index: dict[str, list[KciaIngredient]] = defaultdict(list)
    for record in records:
        for alias in record.aliases():
            key = normalize_match(alias)
            if key and record not in index[key]:
                index[key].append(record)
    return {key: tuple(values) for key, values in index.items()}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build_existing_indexes(
    ingredient_rows: list[dict[str, str]],
    alias_rows: list[dict[str, str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str], int]:
    identity_index: dict[str, set[str]] = defaultdict(set)
    alias_index: dict[str, set[str]] = defaultdict(set)
    canonical_ids: set[str] = set()
    for row in ingredient_rows:
        ingredient_id = row["ingredient_id"].strip()
        if ingredient_id.startswith("ing_pending_"):
            continue
        canonical_ids.add(ingredient_id)
        for field in ("name_ko", "name_en"):
            key = normalize_match(row.get(field, ""))
            if key:
                identity_index[key].add(ingredient_id)
        if "순수" in row.get("description", ""):
            for part in row.get("name_en", "").split("/"):
                key = normalize_match(part)
                if key:
                    identity_index[key].add(ingredient_id)
    for row in alias_rows:
        canonical_id = row["canonical_id"].strip()
        if canonical_id not in canonical_ids:
            continue
        key = normalize_match(row.get("alias", ""))
        if key:
            alias_index[key].add(canonical_id)
    return identity_index, alias_index, canonical_ids, len(canonical_ids)


def slugify(record: KciaIngredient) -> str:
    source = record.standard_name_en.casefold()
    ascii_source = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode()
    slug = SLUG_RE.sub("_", ascii_source).strip("_")
    if not slug:
        return f"kcia_{record.code}"
    if len(slug) <= MAX_CANONICAL_ID_LENGTH:
        return slug
    suffix = f"_kcia_{record.code}"
    return f"{slug[: MAX_CANONICAL_ID_LENGTH - len(suffix)].rstrip('_')}{suffix}"


def disambiguate_canonical_id(candidate_id: str, record: KciaIngredient) -> str:
    suffix = f"_kcia_{record.code}"
    prefix = candidate_id[: MAX_CANONICAL_ID_LENGTH - len(suffix)].rstrip("_")
    return f"{prefix}{suffix}"


def match_existing_canonical(
    record: KciaIngredient,
    existing_name_index: dict[str, set[str]],
) -> set[str]:
    matches: set[str] = set()
    for alias in record.aliases():
        matches.update(existing_name_index.get(normalize_match(alias), set()))
    return matches


def analyze_inventory_matches(
    row: dict[str, str],
    official_index: dict[str, tuple[KciaIngredient, ...]],
) -> tuple[KciaIngredient | None, int, float, set[str], bool]:
    raw_variants = row.get("observed_names_json", "").strip()
    if raw_variants:
        variants = json.loads(raw_variants)
    else:
        variants = [{"name": row["dominant_name"], "count": int(row["row_count"])}]

    matched_rows = 0
    matched_codes: Counter[str] = Counter()
    ambiguous_codes: set[str] = set()
    record_by_code: dict[str, KciaIngredient] = {}
    for variant in variants:
        count = int(variant["count"])
        matches = official_index.get(normalize_match(variant["name"]), ())
        if len(matches) == 1:
            record = matches[0]
            matched_rows += count
            matched_codes[record.code] += count
            record_by_code[record.code] = record
        elif len(matches) > 1:
            ambiguous_codes.update(record.code for record in matches)

    dominant_matches = official_index.get(normalize_match(row["dominant_name"]), ())
    dominant_ambiguous = len(dominant_matches) > 1
    conflict_codes = set(matched_codes) | ambiguous_codes
    record = dominant_matches[0] if len(dominant_matches) == 1 else None
    row_count = max(int(row["row_count"]), 1)
    match_ratio = matched_rows / row_count
    if record is not None:
        conflict_codes.discard(record.code)
    return record, matched_rows, match_ratio, conflict_codes, dominant_ambiguous


def build_proposals(
    inventory_rows: list[dict[str, str]],
    records: list[KciaIngredient],
    ingredient_rows: list[dict[str, str]],
    alias_rows: list[dict[str, str]],
    *,
    target_canonical_count: int,
    source_sha256: str,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    official_index = build_official_index(records)
    identity_index, alias_index, existing_ids, current_count = build_existing_indexes(
        ingredient_rows, alias_rows
    )
    needed_new = max(target_canonical_count - current_count, 0)
    selected_codes: set[str] = set()
    proposed_id_by_code: dict[str, str] = {}
    used_ids = set(existing_ids)
    output: list[dict[str, str]] = []

    for row in inventory_rows:
        dominant_name = row["dominant_name"].strip()
        record, matched_rows, match_ratio, conflict_codes, dominant_ambiguous = (
            analyze_inventory_matches(row, official_index)
        )
        existing_id = row.get("existing_canonical_id", "").strip()
        selected = "N"
        proposed_id = ""
        related_family_ids: set[str] = set()

        if row.get("triage_status") == "reject_noise_candidate":
            match_status = "not_applicable"
            action = "reject_noise_candidate"
            confidence = "high"
            note = row.get("triage_note", "")
        elif dominant_ambiguous:
            match_status = "official_exact_ambiguous"
            action = "manual_review"
            confidence = "low"
            note = "같은 표기가 둘 이상의 KCIA 성분코드와 일치"
        elif conflict_codes:
            match_status = "official_variant_conflict"
            action = "manual_review"
            confidence = "low"
            note = "한 source ingredient ID 안에서 서로 다른 KCIA 성분코드가 발견됨"
        elif record is None:
            match_status = "no_official_exact_match"
            action = "manual_review"
            confidence = "low"
            note = "표준명·영문명·구명칭 exact 일치 없음; 기존 alias도 identity 병합 근거로 사용하지 않음"
        elif match_ratio < MIN_AUTOMATIC_MATCH_RATIO:
            match_status = "official_exact_low_variant_coverage"
            action = "manual_review"
            confidence = "medium"
            note = (
                "대표명은 KCIA와 일치하지만 전체 원문 표기의 exact 일치율이 "
                f"{match_ratio:.2%}로 자동 적용 기준 미달"
            )
        else:
            existing_matches = match_existing_canonical(record, identity_index)
            related_family_ids = match_existing_canonical(record, alias_index)
            if existing_id:
                related_family_ids.add(existing_id)
            match_status = "official_exact"
            if len(existing_matches) == 1:
                action = "merge_existing"
                proposed_id = next(iter(existing_matches))
                related_family_ids.discard(proposed_id)
                selected = "Y"
                confidence = "high"
                note = "KCIA 성분코드가 기존 canonical 자체 명칭과 일치"
            elif len(existing_matches) > 1:
                action = "manual_review"
                confidence = "low"
                note = "KCIA 성분코드가 둘 이상의 기존 canonical과 충돌"
            else:
                action = "create_canonical"
                if record.code not in proposed_id_by_code:
                    candidate_id = slugify(record)
                    if candidate_id in used_ids:
                        candidate_id = disambiguate_canonical_id(candidate_id, record)
                    proposed_id_by_code[record.code] = candidate_id
                    used_ids.add(candidate_id)
                proposed_id = proposed_id_by_code[record.code]
                if record.code in selected_codes or len(selected_codes) < needed_new:
                    selected_codes.add(record.code)
                    selected = "Y"
                confidence = "high"
                note = "dominant_name이 KCIA 표준명·영문명·구명칭 중 하나와 exact 일치"

        output.append(
            {
                "rank": row["rank"],
                "source_ingredient_id": row["source_ingredient_id"],
                "dominant_name": dominant_name,
                "row_count": row["row_count"],
                "product_count": row["product_count"],
                "kcia_ingredient_code": record.code if record else "",
                "kcia_standard_name_ko": record.standard_name_ko if record else "",
                "kcia_standard_name_en": record.standard_name_en if record else "",
                "kcia_old_names_ko": record.old_names_ko if record else "",
                "kcia_old_names_en": record.old_names_en if record else "",
                "official_match_status": match_status,
                "official_matched_row_count": str(matched_rows),
                "official_match_ratio": f"{match_ratio:.6f}",
                "official_conflict_codes": "|".join(sorted(conflict_codes, key=int)),
                "proposed_action": action,
                "proposed_canonical_id": proposed_id,
                "related_scoring_family_ids": "|".join(sorted(related_family_ids)),
                "selected_for_target": selected,
                "proposal_confidence": confidence,
                "review_status": (
                    "accepted_auto_exact"
                    if selected == "Y"
                    else "rejected_noise"
                    if action == "reject_noise_candidate"
                    else "candidate_unverified"
                ),
                "proposal_note": note,
                "source_document_date": SOURCE_DOCUMENT_DATE,
                "source_document_sha256": source_sha256,
            }
        )

    stats = {
        "current_canonical_count": current_count,
        "target_canonical_count": target_canonical_count,
        "needed_new_canonical": needed_new,
        "selected_new_canonical": len(selected_codes),
        "projected_canonical_count": current_count + len(selected_codes),
        "official_exact_rows": sum(
            row["official_match_status"] == "official_exact" for row in output
        ),
        "manual_review_rows": sum(row["proposed_action"] == "manual_review" for row in output),
    }
    return output, stats


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_proposals(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROPOSAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--kcia-pdf", type=Path, required=True)
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--aliases", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonicalization_proposals.csv"),
    )
    parser.add_argument("--target-canonical-count", type=int, default=500)
    args = parser.parse_args()

    source_sha256 = sha256_file(args.kcia_pdf)
    records = parse_kcia_pdf(args.kcia_pdf)
    rows, stats = build_proposals(
        load_csv(args.inventory),
        records,
        load_csv(args.ingredients),
        load_csv(args.aliases),
        target_canonical_count=args.target_canonical_count,
        source_sha256=source_sha256,
    )
    write_proposals(args.output, rows)
    print(
        "KCIA canonicalization proposals: "
        f"official_records={len(records)} current={stats['current_canonical_count']} "
        f"selected_new={stats['selected_new_canonical']} "
        f"projected={stats['projected_canonical_count']}/"
        f"{stats['target_canonical_count']} manual_review={stats['manual_review_rows']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
