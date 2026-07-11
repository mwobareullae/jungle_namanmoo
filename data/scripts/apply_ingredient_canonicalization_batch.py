#!/usr/bin/env python3
"""Apply accepted KCIA canonicalization proposals without rewriting product rows."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


INGREDIENT_FIELDS = ["ingredient_id", "name_ko", "name_en", "description", "source_url"]
MAPPING_FIELDS = [
    "source_ingredient_id",
    "source_ingredient_name",
    "canonical_id",
    "mapping_type",
    "confidence",
    "source",
]
ALIAS_FIELDS = ["alias", "canonical_id", "alias_type", "confidence", "source"]
ALIAS_CHANGE_FIELDS = [
    "alias",
    "normalized_alias",
    "previous_canonical_id",
    "new_canonical_id",
    "action",
    "note",
]
KCIA_SOURCE_URL = "https://kcia.or.kr/cid/main/"


@dataclass(frozen=True)
class ApplyStats:
    canonical_before: int
    canonical_added: int
    canonical_after: int
    mapping_rows: int
    aliases_added: int
    aliases_reassigned: int
    alias_conflicts: int


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(normalized.split())


def split_aliases(value: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in value.split("|") if part.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def selected_rows(proposal_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [row for row in proposal_rows if row.get("selected_for_target") == "Y"]
    invalid = [
        row["source_ingredient_id"]
        for row in rows
        if row.get("review_status") != "accepted_auto_exact"
        or row.get("proposal_confidence") != "high"
        or row.get("proposed_action") not in {"create_canonical", "merge_existing"}
    ]
    if invalid:
        raise ValueError(f"자동 적용할 수 없는 proposal 행이 있습니다: {', '.join(invalid[:10])}")
    return rows


def append_ingredients(
    path: Path,
    selected: list[dict[str, str]],
) -> tuple[int, int, int]:
    existing_rows = read_csv(path)
    existing_by_id = {row["ingredient_id"]: row for row in existing_rows}
    canonical_before = sum(not ingredient_id.startswith("ing_pending_") for ingredient_id in existing_by_id)
    records_by_id: dict[str, dict[str, str]] = {}
    for row in selected:
        if row["proposed_action"] != "create_canonical":
            continue
        ingredient_id = row["proposed_canonical_id"]
        record = {
            "ingredient_id": ingredient_id,
            "name_ko": row["kcia_standard_name_ko"],
            "name_en": row["kcia_standard_name_en"],
            "description": (
                "KCIA 2026-06-30 표준화명칭목록 성분코드 "
                f"{row['kcia_ingredient_code']}. 상품 원문 exact match canonical."
            ),
            "source_url": KCIA_SOURCE_URL,
        }
        prior = records_by_id.get(ingredient_id)
        if prior is not None and prior != record:
            raise ValueError(f"같은 canonical_id에 서로 다른 KCIA 성분이 매핑됩니다: {ingredient_id}")
        records_by_id[ingredient_id] = record

    missing_records: list[dict[str, str]] = []
    for ingredient_id, record in records_by_id.items():
        existing = existing_by_id.get(ingredient_id)
        if existing is None:
            missing_records.append(record)
            continue
        if existing.get("name_ko") != record["name_ko"] or existing.get("name_en") != record["name_en"]:
            raise ValueError(f"기존 canonical_id 명칭이 KCIA proposal과 다릅니다: {ingredient_id}")

    if missing_records:
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=INGREDIENT_FIELDS, lineterminator="\n")
            writer.writerows(sorted(missing_records, key=lambda row: row["ingredient_id"]))
    canonical_added = len(missing_records)
    return canonical_before, canonical_added, canonical_before + canonical_added


def build_mapping_rows(selected: list[dict[str, str]]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for row in sorted(selected, key=lambda item: int(item["rank"])):
        source_id = row["source_ingredient_id"]
        if source_id in seen_sources:
            raise ValueError(f"proposal source_ingredient_id가 중복됩니다: {source_id}")
        seen_sources.add(source_id)
        mappings.append(
            {
                "source_ingredient_id": source_id,
                "source_ingredient_name": "",
                "canonical_id": row["proposed_canonical_id"],
                "mapping_type": (
                    "existing_identity"
                    if row["proposed_action"] == "merge_existing"
                    else "official_exact"
                ),
                "confidence": "high",
                "source": (
                    "KCIA 표준화명칭목록 2026-06-30 "
                    f"code={row['kcia_ingredient_code']} sha256={row['source_document_sha256'][:12]}"
                ),
            }
        )
    return mappings


def build_exact_name_override_rows(selected: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in selected:
        if row["proposed_action"] != "create_canonical":
            continue
        family_ids = [value for value in row.get("related_scoring_family_ids", "").split("|") if value]
        if not family_ids:
            continue
        aliases: list[tuple[str, str]] = [
            (row["kcia_standard_name_ko"], "standard_name"),
            (row["kcia_standard_name_en"], "standard_name"),
        ]
        aliases.extend(
            (alias, "legacy_name") for alias in split_aliases(row["kcia_old_names_ko"])
        )
        aliases.extend(
            (alias, "legacy_name") for alias in split_aliases(row["kcia_old_names_en"])
        )
        for family_id in family_ids:
            for alias, alias_basis in aliases:
                key = (family_id, normalize(alias))
                if not key[1]:
                    continue
                mapping = {
                    "source_ingredient_id": family_id,
                    "source_ingredient_name": alias,
                    "canonical_id": row["proposed_canonical_id"],
                    "mapping_type": "exact_name_override",
                    "confidence": "high",
                    "source": (
                        "KCIA 표준화명칭목록 2026-06-30 "
                        f"code={row['kcia_ingredient_code']} alias_basis={alias_basis} "
                        f"sha256={row['source_document_sha256'][:12]}"
                    ),
                }
                prior = rows_by_key.get(key)
                if prior is not None and prior["canonical_id"] != mapping["canonical_id"]:
                    raise ValueError(
                        "같은 broad source/name이 둘 이상의 exact canonical과 충돌합니다: "
                        f"{family_id}/{alias}"
                    )
                rows_by_key[key] = mapping
    return list(rows_by_key.values())


def official_alias_candidates(
    selected: list[dict[str, str]],
) -> dict[str, list[tuple[str, str, str]]]:
    candidates: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    seen_records: set[tuple[str, str]] = set()
    for row in selected:
        canonical_id = row["proposed_canonical_id"]
        record_key = (row["kcia_ingredient_code"], canonical_id)
        if record_key in seen_records:
            continue
        seen_records.add(record_key)
        values: list[tuple[str, str]] = [
            (row["kcia_standard_name_ko"], "ko"),
            (row["kcia_standard_name_en"], "inci"),
        ]
        values.extend((alias, "synonym") for alias in split_aliases(row["kcia_old_names_ko"]))
        values.extend((alias, "synonym") for alias in split_aliases(row["kcia_old_names_en"]))
        for alias, alias_type in values:
            key = normalize(alias)
            candidate = (alias, canonical_id, alias_type)
            if key and candidate not in candidates[key]:
                candidates[key].append(candidate)
    return candidates


def update_aliases(
    aliases_path: Path,
    changes_path: Path,
    selected: list[dict[str, str]],
) -> tuple[int, int, int]:
    rows = read_csv(aliases_path)
    row_by_key = {normalize(row["alias"]): row for row in rows}
    changes: list[dict[str, str]] = []
    added = 0
    reassigned = 0
    conflicts = 0
    for key, candidates in sorted(official_alias_candidates(selected).items()):
        owners = {canonical_id for _, canonical_id, _ in candidates}
        alias = candidates[0][0]
        if len(owners) != 1:
            conflicts += 1
            changes.append(
                {
                    "alias": alias,
                    "normalized_alias": key,
                    "previous_canonical_id": row_by_key.get(key, {}).get("canonical_id", ""),
                    "new_canonical_id": "|".join(sorted(owners)),
                    "action": "skipped_conflict",
                    "note": "KCIA alias가 둘 이상의 선택 canonical에 연결됨",
                }
            )
            continue

        _, canonical_id, alias_type = candidates[0]
        existing = row_by_key.get(key)
        if existing is None:
            new_row = {
                "alias": alias,
                "canonical_id": canonical_id,
                "alias_type": alias_type,
                "confidence": "high",
                "source": "KCIA 표준화명칭목록 2026-06-30",
            }
            rows.append(new_row)
            row_by_key[key] = new_row
            added += 1
            action = "added"
            previous = ""
        elif existing["canonical_id"] != canonical_id:
            previous = existing["canonical_id"]
            existing.update(
                {
                    "alias": alias,
                    "canonical_id": canonical_id,
                    "alias_type": alias_type,
                    "confidence": "high",
                    "source": "KCIA 표준화명칭목록 2026-06-30",
                }
            )
            reassigned += 1
            action = "reassigned_exact_identity"
        else:
            continue
        changes.append(
            {
                "alias": alias,
                "normalized_alias": key,
                "previous_canonical_id": previous,
                "new_canonical_id": canonical_id,
                "action": action,
                "note": "공식 exact identity alias",
            }
        )

    write_csv(aliases_path, ALIAS_FIELDS, rows)
    write_csv(changes_path, ALIAS_CHANGE_FIELDS, changes)
    return added, reassigned, conflicts


def apply_batch(
    *,
    proposals_path: Path,
    ingredients_path: Path,
    aliases_path: Path,
    mappings_path: Path,
    alias_changes_path: Path,
) -> ApplyStats:
    selected = selected_rows(read_csv(proposals_path))
    before, added, after = append_ingredients(ingredients_path, selected)
    mapping_rows = build_mapping_rows(selected)
    mapping_rows.extend(build_exact_name_override_rows(selected))
    mapping_rows.sort(
        key=lambda row: (
            row["source_ingredient_id"],
            normalize(row["source_ingredient_name"]),
        )
    )
    write_csv(mappings_path, MAPPING_FIELDS, mapping_rows)
    aliases_added, aliases_reassigned, conflicts = update_aliases(
        aliases_path, alias_changes_path, selected
    )
    return ApplyStats(
        canonical_before=before,
        canonical_added=added,
        canonical_after=after,
        mapping_rows=len(mapping_rows),
        aliases_added=aliases_added,
        aliases_reassigned=aliases_reassigned,
        alias_conflicts=conflicts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonicalization_proposals_500.csv"),
    )
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--aliases", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument(
        "--mappings",
        type=Path,
        default=Path("data/ingredient_canonical_mappings.csv"),
    )
    parser.add_argument(
        "--alias-changes",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonicalization_alias_changes.csv"),
    )
    args = parser.parse_args()
    stats = apply_batch(
        proposals_path=args.proposals,
        ingredients_path=args.ingredients,
        aliases_path=args.aliases,
        mappings_path=args.mappings,
        alias_changes_path=args.alias_changes,
    )
    print(
        "Ingredient canonicalization applied: "
        f"canonical={stats.canonical_before}+{stats.canonical_added}={stats.canonical_after} "
        f"mappings={stats.mapping_rows} aliases_added={stats.aliases_added} "
        f"aliases_reassigned={stats.aliases_reassigned} conflicts={stats.alias_conflicts}"
    )


if __name__ == "__main__":
    main()
