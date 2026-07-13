#!/usr/bin/env python3
"""Build the frozen 34+466 ingredient score expansion on the legacy runtime scale.

The historical 34-ingredient scores are preserved byte-for-byte at row level.
New scores use two non-blocking lanes:

1. official_function_prior
   Narrow CosIng functions already approved by ``build_ingredient_role_inventory``
   receive a conservative score at the floor of the matching legacy effect axis.
   Medium-strength moisture signals receive the legacy global floor. These rows do
   not create scientific evidence records.
2. ai_paper_override
   The v1.3 positive paper rescue rows are translated to the legacy 30-74 scale:
   primary=70, supporting=50, limited_medical=35. Their existing AI evidence grade
   remains the separate evidence score.

Neither full-text availability nor human approval is used as a runtime score gate.
Review fields remain provenance metadata only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


EFFECT_FIELDS = ["ingredient_id", "effect_id", "effect_name", "effect_score"]
EVIDENCE_FIELDS = [
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
    "canonical_evidence_key",
    "review_status",
    "result_direction",
    "score_use_level",
    "is_representative",
    "representative_rank",
    "is_current",
    "review_note",
    "reviewed_by",
    "reviewed_at",
]
PAIR_AUDIT_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "effect_score",
    "score_origin",
    "score_basis",
    "official_signal_strength",
    "official_signal_functions",
    "paper_evidence_class",
    "paper_key",
    "evidence_score",
    "runtime_score_active",
    "human_approval_gate_used",
    "full_text_gate_used",
]
INGREDIENT_AUDIT_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "cohort_source",
    "score_status",
    "active_effect_count",
    "active_effect_ids",
    "min_effect_score",
    "max_effect_score",
    "score_origins",
    "human_approval_gate_used",
    "full_text_gate_used",
]
PAPER_OVERRIDE_FIELDS = [
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "evidence_class",
    "legacy_effect_score",
    "evidence_score",
    "paper_key",
    "paper_title",
    "evidence_sentence",
    "reason_ko",
    "source_url",
    "screening_pass",
    "score_origin",
    "external_claim_use",
]

PAPER_EFFECT_SCORES = {
    "primary": 70,
    "supporting": 50,
    "limited_medical": 35,
}
PAPER_EVIDENCE_SCORES = {
    "primary": 50,
    "supporting": 35,
    "limited_medical": 25,
}
PAPER_SCREENING_PASSES = {"initial_164_ai", "full_43533_candidate_rescue"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_paper_overrides(
    source_json: Path,
    output_csv: Path,
) -> list[dict[str, str]]:
    payload = json.loads(source_json.read_text(encoding="utf-8"))
    rows = payload["score_pairs"]
    normalized: list[dict[str, str]] = []
    for row in rows:
        evidence_class = str(row["evidence_class"])
        normalized.append(
            {
                "ingredient_id": row["ingredient_id"],
                "name_ko": row["name_ko"],
                "name_en": row["name_en"],
                "effect_id": row["effect_id"],
                "effect_name": row["effect_name"],
                "evidence_class": evidence_class,
                "legacy_effect_score": PAPER_EFFECT_SCORES[evidence_class],
                "evidence_score": PAPER_EVIDENCE_SCORES[evidence_class],
                "paper_key": row["paper_key"],
                "paper_title": row["paper_title"],
                "evidence_sentence": row["evidence_sentence"],
                "reason_ko": row["reason_ko"],
                "source_url": row["source_url"],
                "screening_pass": row["screening_pass"],
                "score_origin": row["score_origin"],
                "external_claim_use": row["external_claim_use"],
            }
        )
    write_csv(output_csv, PAPER_OVERRIDE_FIELDS, normalized)
    return normalized


def legacy_axis_floors(current_effect_rows: list[dict[str, str]]) -> dict[str, int]:
    scores: dict[str, list[int]] = defaultdict(list)
    for row in current_effect_rows:
        scores[row["effect_id"]].append(int(row["effect_score"]))
    return {effect_id: min(values) for effect_id, values in scores.items()}


def official_prior_score(
    row: Mapping[str, str],
    *,
    axis_floors: Mapping[str, int],
    global_floor: int,
) -> int:
    effect_id = row["effect_id"]
    if effect_id not in axis_floors:
        raise ValueError(f"unknown effect axis: {effect_id}")
    strength = row.get("signal_strength", "")
    if strength == "high":
        return axis_floors[effect_id]
    if strength == "medium":
        return global_floor
    raise ValueError(f"unsupported new signal strength: {strength!r}")


def evidence_level(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def evidence_summary(row: Mapping[str, str]) -> str:
    name = row["name_ko"] or row["name_en"]
    effect_name = row["effect_name"]
    evidence_class = row["evidence_class"]
    if evidence_class == "primary":
        return f"{name}은(는) 공개된 대조 인체 적용 자료에서 {effect_name} 관련 개선 결과가 보고된 성분입니다."
    if evidence_class == "supporting":
        return f"{name}은(는) 공개된 인체 적용 자료에서 {effect_name} 관련 결과가 보고되어 보조 근거로 반영됩니다."
    return f"{name}은(는) 제한된 환자군 또는 적용 조건의 공개 자료에서 {effect_name} 관련 결과가 보고되어 보수적으로 반영됩니다."


def calculate_product_coverage(
    *,
    data_dir: Path,
    baseline_effect_rows: list[dict[str, str]],
    expanded_effect_rows: list[dict[str, object]],
) -> dict[str, object]:
    from build_ingredient_role_inventory import apply_mapping, load_mappings

    pairs_by_version: dict[str, dict[str, set[str]]] = {
        "baseline_34": defaultdict(set),
        "expanded": defaultdict(set),
    }
    for row in baseline_effect_rows:
        pairs_by_version["baseline_34"][row["ingredient_id"]].add(row["effect_id"])
    for row in expanded_effect_rows:
        pairs_by_version["expanded"][str(row["ingredient_id"])].add(str(row["effect_id"]))

    exact_mapping, wildcard_mapping = load_mappings(
        data_dir / "ingredient_canonical_mappings.csv"
    )
    all_products: set[str] = set()
    any_products: dict[str, set[str]] = defaultdict(set)
    axis_products: dict[str, dict[str, set[str]]] = {
        version: defaultdict(set) for version in pairs_by_version
    }
    for path in sorted((data_dir / "product_ingredients").glob("product_ingredients_*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = row["product_id"]
                all_products.add(product_id)
                ingredient_id = apply_mapping(
                    row["ingredient_id"],
                    row.get("ingredient_name", ""),
                    exact_mapping,
                    wildcard_mapping,
                )
                for version, pairs_by_ingredient in pairs_by_version.items():
                    if ingredient_id not in pairs_by_ingredient:
                        continue
                    any_products[version].add(product_id)
                    for effect_id in pairs_by_ingredient[ingredient_id]:
                        axis_products[version][effect_id].add(product_id)

    total = len(all_products)
    output: dict[str, object] = {"product_count": total, "versions": {}}
    versions = output["versions"]
    assert isinstance(versions, dict)
    for version in ("baseline_34", "expanded"):
        versions[version] = {
            "any_scored_ingredient_product_count": len(any_products[version]),
            "any_scored_ingredient_product_pct": round(
                len(any_products[version]) / total * 100, 2
            )
            if total
            else 0,
            "effect_product_coverage": {
                effect_id: {
                    "product_count": len(product_ids),
                    "product_pct": round(len(product_ids) / total * 100, 2) if total else 0,
                }
                for effect_id, product_ids in sorted(axis_products[version].items())
            },
        }
    return output


def build_paper_evidence(row: Mapping[str, str]) -> dict[str, object]:
    key = row["paper_key"]
    pmid = key.removeprefix("PMID:") if key.startswith("PMID:") else ""
    doi = key.removeprefix("DOI:") if key.startswith("DOI:") else ""
    evidence_class = row["evidence_class"]
    score_use_level = "primary" if evidence_class == "primary" else "supporting"
    score = int(row["evidence_score"])
    return {
        "ingredient_id": row["ingredient_id"],
        "effect_id": row["effect_id"],
        "evidence_level": evidence_level(score),
        "evidence_score": score,
        "source_title": row["paper_title"],
        "source_url": row["source_url"],
        "summary": evidence_summary(row),
        "source_type": "paper",
        "pmid": pmid,
        "doi": doi,
        "source_authority_score": "0.5",
        "canonical_evidence_key": key,
        "review_status": "candidate_unverified",
        "result_direction": "positive",
        "score_use_level": score_use_level,
        "is_representative": "false",
        "representative_rank": "",
        "is_current": "true",
        "review_note": (
            "legacy-scale runtime activation; human approval is not a score gate; "
            f"class={evidence_class}; {row['reason_ko']}; "
            f"external_claim_use={row['external_claim_use']}"
        ),
        "reviewed_by": "",
        "reviewed_at": "",
    }


def build_scoring(
    *,
    current_effect_rows: list[dict[str, str]],
    current_evidence_rows: list[dict[str, str]],
    cohort_rows: list[dict[str, str]],
    ingredient_metadata_rows: list[dict[str, str]],
    screening_rows: list[dict[str, str]],
    paper_override_rows: list[dict[str, str]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    existing_ids = {row["ingredient_id"] for row in current_effect_rows}
    new_ids = {row["ingredient_id"] for row in cohort_rows}
    if len(existing_ids) != 34:
        raise ValueError(f"expected 34 existing ingredients, got {len(existing_ids)}")
    if len(new_ids) != 466:
        raise ValueError(f"expected 466 new ingredients, got {len(new_ids)}")
    if existing_ids & new_ids:
        raise ValueError("the frozen 466 cohort overlaps existing runtime ingredients")

    cohort_by_id = {row["ingredient_id"]: row for row in cohort_rows}
    metadata_by_id = {row["ingredient_id"]: row for row in ingredient_metadata_rows}
    rank_by_id = {row["ingredient_id"]: int(row["ingredient_rank"]) for row in cohort_rows}
    current_keys = {(row["ingredient_id"], row["effect_id"]) for row in current_effect_rows}
    if len(current_keys) != len(current_effect_rows):
        raise ValueError("duplicate current ingredient-effect pairs")

    floors = legacy_axis_floors(current_effect_rows)
    global_floor = min(floors.values())
    new_pairs: dict[tuple[str, str], dict[str, object]] = {}

    for row in screening_rows:
        ingredient_id = row["ingredient_id"]
        if ingredient_id not in new_ids:
            continue
        if row.get("signal_strength") not in {"high", "medium"}:
            continue
        key = (ingredient_id, row["effect_id"])
        if key in current_keys or key in new_pairs:
            raise ValueError(f"duplicate official prior pair: {key}")
        cohort = cohort_by_id[ingredient_id]
        score = official_prior_score(row, axis_floors=floors, global_floor=global_floor)
        new_pairs[key] = {
            "ingredient_rank": rank_by_id[ingredient_id],
            "ingredient_id": ingredient_id,
            "name_ko": cohort["name_ko"],
            "name_en": cohort["name_en"],
            "effect_id": row["effect_id"],
            "effect_name": row["effect_name"],
            "effect_score": score,
            "score_origin": "official_function_prior",
            "score_basis": (
                f"legacy_axis_floor:{floors[row['effect_id']]}"
                if row["signal_strength"] == "high"
                else f"legacy_global_floor:{global_floor}"
            ),
            "official_signal_strength": row["signal_strength"],
            "official_signal_functions": row.get("signal_functions", ""),
            "paper_evidence_class": "",
            "paper_key": "",
            "evidence_score": 0,
        }

    paper_evidence_rows: list[dict[str, object]] = []
    for row in paper_override_rows:
        ingredient_id = row["ingredient_id"]
        if ingredient_id not in new_ids:
            raise ValueError(f"paper override is outside the frozen 466 cohort: {ingredient_id}")
        evidence_class = row["evidence_class"]
        if evidence_class not in PAPER_EFFECT_SCORES:
            raise ValueError(f"unsupported paper evidence class: {evidence_class!r}")
        if row.get("screening_pass") not in PAPER_SCREENING_PASSES:
            raise ValueError(f"unapproved paper screening pass: {row.get('screening_pass')!r}")
        if row.get("score_origin") != "AI_full_candidate_rescue_v1.3":
            raise ValueError(f"unapproved paper score origin: {row.get('score_origin')!r}")
        if row.get("external_claim_use") != "separate_from_runtime_score":
            raise ValueError("paper runtime score must remain separate from external claims")
        expected_effect_score = PAPER_EFFECT_SCORES[evidence_class]
        expected_evidence_score = PAPER_EVIDENCE_SCORES[evidence_class]
        if int(row["legacy_effect_score"]) != expected_effect_score:
            raise ValueError(f"unexpected paper effect score for {evidence_class}")
        if int(row["evidence_score"]) != expected_evidence_score:
            raise ValueError(f"unexpected paper evidence score for {evidence_class}")
        key = (ingredient_id, row["effect_id"])
        paper_score = expected_effect_score
        cohort = cohort_by_id[ingredient_id]
        if key in new_pairs:
            pair = new_pairs[key]
            prior_score = int(pair["effect_score"])
            pair["effect_score"] = max(prior_score, paper_score)
            pair["score_origin"] = "official_function_prior+ai_paper_override"
            pair["score_basis"] = (
                f"max(official_prior:{prior_score},paper_{row['evidence_class']}:{paper_score})"
            )
            pair["paper_evidence_class"] = row["evidence_class"]
            pair["paper_key"] = row["paper_key"]
            pair["evidence_score"] = int(row["evidence_score"])
        else:
            new_pairs[key] = {
                "ingredient_rank": rank_by_id[ingredient_id],
                "ingredient_id": ingredient_id,
                "name_ko": cohort["name_ko"],
                "name_en": cohort["name_en"],
                "effect_id": row["effect_id"],
                "effect_name": row["effect_name"],
                "effect_score": paper_score,
                "score_origin": "ai_paper_override",
                "score_basis": f"paper_{row['evidence_class']}:{paper_score}",
                "official_signal_strength": "",
                "official_signal_functions": "",
                "paper_evidence_class": row["evidence_class"],
                "paper_key": row["paper_key"],
                "evidence_score": int(row["evidence_score"]),
            }
        paper_evidence_rows.append(build_paper_evidence(row))

    sorted_new_pairs = sorted(
        new_pairs.values(),
        key=lambda row: (int(row["ingredient_rank"]), str(row["effect_id"])),
    )
    effect_rows: list[dict[str, object]] = [dict(row) for row in current_effect_rows]
    effect_rows.extend(
        {
            "ingredient_id": row["ingredient_id"],
            "effect_id": row["effect_id"],
            "effect_name": row["effect_name"],
            "effect_score": row["effect_score"],
        }
        for row in sorted_new_pairs
    )
    evidence_rows: list[dict[str, object]] = [dict(row) for row in current_evidence_rows]
    evidence_rows.extend(paper_evidence_rows)

    pair_audit: list[dict[str, object]] = []
    current_evidence_by_key = {
        (row["ingredient_id"], row["effect_id"]): row for row in current_evidence_rows
    }
    for row in current_effect_rows:
        key = (row["ingredient_id"], row["effect_id"])
        evidence = current_evidence_by_key.get(key, {})
        metadata = metadata_by_id.get(row["ingredient_id"], {})
        pair_audit.append(
            {
                "ingredient_rank": 0,
                "ingredient_id": row["ingredient_id"],
                "name_ko": metadata.get("name_ko", ""),
                "name_en": metadata.get("name_en", ""),
                "effect_id": row["effect_id"],
                "effect_name": row["effect_name"],
                "effect_score": row["effect_score"],
                "score_origin": "existing_34_unchanged",
                "score_basis": "historical_manual_score_preserved",
                "official_signal_strength": "",
                "official_signal_functions": "",
                "paper_evidence_class": "existing_runtime",
                "paper_key": evidence.get("canonical_evidence_key", ""),
                "evidence_score": evidence.get("evidence_score", ""),
                "runtime_score_active": "Y",
                "human_approval_gate_used": "N",
                "full_text_gate_used": "N",
            }
        )
    for row in sorted_new_pairs:
        pair_audit.append(
            {
                **{field: row.get(field, "") for field in PAIR_AUDIT_FIELDS[:15]},
                "runtime_score_active": "Y",
                "human_approval_gate_used": "N",
                "full_text_gate_used": "N",
            }
        )

    pairs_by_ingredient: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in pair_audit:
        pairs_by_ingredient[str(row["ingredient_id"])].append(row)

    ingredient_audit: list[dict[str, object]] = []
    for ingredient_id in sorted(existing_ids):
        pairs = pairs_by_ingredient[ingredient_id]
        scores = [int(row["effect_score"]) for row in pairs]
        metadata = metadata_by_id.get(ingredient_id, {})
        ingredient_audit.append(
            {
                "ingredient_rank": 0,
                "ingredient_id": ingredient_id,
                "name_ko": metadata.get("name_ko", ""),
                "name_en": metadata.get("name_en", ""),
                "product_count": metadata.get("product_count", ""),
                "cohort_source": "existing_34",
                "score_status": "score_active_existing",
                "active_effect_count": len(pairs),
                "active_effect_ids": "|".join(sorted(str(row["effect_id"]) for row in pairs)),
                "min_effect_score": min(scores),
                "max_effect_score": max(scores),
                "score_origins": "existing_34_unchanged",
                "human_approval_gate_used": "N",
                "full_text_gate_used": "N",
            }
        )
    for cohort in sorted(cohort_rows, key=lambda row: int(row["ingredient_rank"])):
        ingredient_id = cohort["ingredient_id"]
        pairs = pairs_by_ingredient.get(ingredient_id, [])
        scores = [int(row["effect_score"]) for row in pairs]
        ingredient_audit.append(
            {
                "ingredient_rank": int(cohort["ingredient_rank"]),
                "ingredient_id": ingredient_id,
                "name_ko": cohort["name_ko"],
                "name_en": cohort["name_en"],
                "product_count": cohort["product_count"],
                "cohort_source": "new_466",
                "score_status": "score_active_new" if pairs else "evaluated_no_six_axis_signal",
                "active_effect_count": len(pairs),
                "active_effect_ids": "|".join(sorted(str(row["effect_id"]) for row in pairs)),
                "min_effect_score": min(scores) if scores else 0,
                "max_effect_score": max(scores) if scores else 0,
                "score_origins": "|".join(sorted({str(row["score_origin"]) for row in pairs})),
                "human_approval_gate_used": "N",
                "full_text_gate_used": "N",
            }
        )

    effect_keys = {(str(row["ingredient_id"]), str(row["effect_id"])) for row in effect_rows}
    if len(effect_keys) != len(effect_rows):
        raise ValueError("duplicate output ingredient-effect pairs")
    current_output_evidence = [
        row for row in evidence_rows if str(row["is_current"]).casefold() == "true"
    ]
    evidence_keys = {
        (
            str(row["ingredient_id"]),
            str(row["effect_id"]),
            str(row["canonical_evidence_key"]),
        )
        for row in current_output_evidence
    }
    if len(evidence_keys) != len(current_output_evidence):
        raise ValueError("duplicate output evidence keys")

    summary = {
        "policy_version": "mwbl-legacy-scale-500-v1",
        "cohort_ingredient_count": len(existing_ids | new_ids),
        "existing_ingredient_count": len(existing_ids),
        "new_cohort_ingredient_count": len(new_ids),
        "score_active_ingredient_count": len({row["ingredient_id"] for row in effect_rows}),
        "new_score_active_ingredient_count": len(
            {row["ingredient_id"] for row in sorted_new_pairs}
        ),
        "evaluated_without_six_axis_signal_count": len(
            [row for row in ingredient_audit if row["score_status"] == "evaluated_no_six_axis_signal"]
        ),
        "effect_pair_count": len(effect_rows),
        "existing_effect_pair_count": len(current_effect_rows),
        "new_effect_pair_count": len(sorted_new_pairs),
        "evidence_row_count": len(evidence_rows),
        "existing_evidence_row_count": len(current_evidence_rows),
        "new_paper_evidence_row_count": len(paper_evidence_rows),
        "official_function_prior_pair_count": sum(
            "official_function_prior" in str(row["score_origin"]) for row in sorted_new_pairs
        ),
        "paper_override_pair_count": len(paper_override_rows),
        "effect_score_counts": dict(
            sorted(Counter(int(row["effect_score"]) for row in effect_rows).items())
        ),
        "effect_pair_counts": dict(
            sorted(Counter(str(row["effect_id"]) for row in effect_rows).items())
        ),
        "legacy_axis_floors": floors,
        "legacy_global_floor": global_floor,
        "paper_effect_score_mapping": PAPER_EFFECT_SCORES,
        "human_approval_gate_used": False,
        "full_text_gate_used": False,
        "existing_34_scores_changed": False,
    }
    return effect_rows, evidence_rows, pair_audit, ingredient_audit, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--baseline-effects",
        type=Path,
        default=Path("data/reconciliation/legacy_scale_500/baseline_ingredient_effect_34.csv"),
    )
    parser.add_argument(
        "--baseline-evidence",
        type=Path,
        default=Path("data/reconciliation/legacy_scale_500/baseline_ingredient_evidence_34.csv"),
    )
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466.csv"),
    )
    parser.add_argument(
        "--ingredient-metadata",
        type=Path,
        default=Path("data/reconciliation/ingredient_role_review.csv"),
    )
    parser.add_argument(
        "--screening",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_pubmed_screening.csv"),
    )
    parser.add_argument(
        "--paper-overrides",
        type=Path,
        default=Path("data/reconciliation/legacy_scale_500_paper_overrides.csv"),
    )
    parser.add_argument(
        "--import-v13-json",
        type=Path,
        help="Normalize score_pairs from a v1.3 workbook_data.json before building.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reconciliation/legacy_scale_500"),
    )
    parser.add_argument("--apply-runtime", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_effect_path = args.data_dir / "ingredient_effect.csv"
    runtime_evidence_path = args.data_dir / "ingredient_evidence.csv"
    if not args.baseline_effects.exists():
        baseline_effect_rows = read_csv(runtime_effect_path)
        if len(baseline_effect_rows) != 72:
            raise ValueError("cannot initialize the historical baseline from a non-72-row runtime")
        write_csv(args.baseline_effects, EFFECT_FIELDS, baseline_effect_rows)
    if not args.baseline_evidence.exists():
        baseline_evidence_rows = read_csv(runtime_evidence_path)
        if len(baseline_evidence_rows) != 72:
            raise ValueError("cannot initialize the historical evidence baseline from a non-72-row runtime")
        write_csv(args.baseline_evidence, EVIDENCE_FIELDS, baseline_evidence_rows)
    if args.import_v13_json:
        normalize_paper_overrides(args.import_v13_json, args.paper_overrides)

    inputs = {
        "baseline_effect": args.baseline_effects,
        "baseline_evidence": args.baseline_evidence,
        "cohort": args.cohort,
        "ingredient_metadata": args.ingredient_metadata,
        "screening": args.screening,
        "paper_overrides": args.paper_overrides,
    }
    effect_rows, evidence_rows, pair_audit, ingredient_audit, summary = build_scoring(
        current_effect_rows=read_csv(args.baseline_effects),
        current_evidence_rows=read_csv(args.baseline_evidence),
        cohort_rows=read_csv(args.cohort),
        ingredient_metadata_rows=read_csv(args.ingredient_metadata),
        screening_rows=read_csv(args.screening),
        paper_override_rows=read_csv(args.paper_overrides),
    )

    output_effect = args.output_dir / "ingredient_effect_500_legacy_scale.csv"
    output_evidence = args.output_dir / "ingredient_evidence_500_legacy_scale.csv"
    output_pair_audit = args.output_dir / "ingredient_effect_500_legacy_scale_audit.csv"
    output_ingredient_audit = args.output_dir / "ingredient_score_500_legacy_scale.csv"
    output_summary = args.output_dir / "ingredient_scoring_500_legacy_scale_summary.json"
    write_csv(output_effect, EFFECT_FIELDS, effect_rows)
    write_csv(output_evidence, EVIDENCE_FIELDS, evidence_rows)
    write_csv(output_pair_audit, PAIR_AUDIT_FIELDS, pair_audit)
    write_csv(output_ingredient_audit, INGREDIENT_AUDIT_FIELDS, ingredient_audit)

    summary["product_coverage"] = calculate_product_coverage(
        data_dir=args.data_dir,
        baseline_effect_rows=read_csv(args.baseline_effects),
        expanded_effect_rows=effect_rows,
    )

    summary["input_sha256"] = {name: file_sha256(path) for name, path in inputs.items()}
    summary["output_sha256"] = {
        output_effect.name: file_sha256(output_effect),
        output_evidence.name: file_sha256(output_evidence),
        output_pair_audit.name: file_sha256(output_pair_audit),
        output_ingredient_audit.name: file_sha256(output_ingredient_audit),
    }
    output_summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.apply_runtime:
        write_csv(runtime_effect_path, EFFECT_FIELDS, effect_rows)
        write_csv(runtime_evidence_path, EVIDENCE_FIELDS, evidence_rows)

    print(
        "Legacy-scale 500 scoring: "
        f"active_ingredients={summary['score_active_ingredient_count']}/500 "
        f"new_active={summary['new_score_active_ingredient_count']} "
        f"effect_pairs={summary['effect_pair_count']} "
        f"new_pairs={summary['new_effect_pair_count']} "
        f"evidence_rows={summary['evidence_row_count']} "
        f"runtime_applied={'Y' if args.apply_runtime else 'N'}"
    )


if __name__ == "__main__":
    main()
