#!/usr/bin/env python3
"""Measure accepted-only evidence impact without changing runtime scoring."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from statistics import mean, median


TOP_INGREDIENT_DECAYS = (1.0, 0.5, 0.25)
DEFAULT_INGREDIENT_EVIDENCE_WEIGHT = 0.23


def main() -> None:
    args = _parse_args()
    source_files = _source_files(args.data_dir)
    manifest = _build_manifest(source_files, root=args.data_dir.parent)
    report, details = analyze(args.data_dir, manifest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    if args.details is not None:
        args.details.parent.mkdir(parents=True, exist_ok=True)
        _write_details(args.details, details)
    print(args.report)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare current evidence components with the accepted-only gate.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/scoring/evidence-gate-impact-20260711.md"),
    )
    parser.add_argument(
        "--details",
        type=Path,
        default=None,
        help="Optional product×effect CSV output. This can be several MB.",
    )
    return parser.parse_args()


def analyze(
    data_dir: Path,
    manifest: tuple[tuple[str, str], ...],
) -> tuple[str, list[dict[str, object]]]:
    products = _load_recommendable_products(data_dir)
    effects_by_ingredient = _load_ingredient_effects(data_dir)
    current_evidence, accepted_evidence, accepted_pairs = _load_evidence(data_dir)
    top_ingredients, ingredient_product_counts = _load_top_ingredients(
        data_dir,
        products,
        effects_by_ingredient,
    )
    effect_names = {
        effect_id: effect_name
        for rows in effects_by_ingredient.values()
        for effect_id, effect_name, _score in rows
    }
    details = _build_details(
        products,
        top_ingredients,
        effect_names,
        current_evidence,
        accepted_evidence,
    )
    report = _build_report(
        products=products,
        details=details,
        effect_names=effect_names,
        accepted_pairs=accepted_pairs,
        ingredient_product_counts=ingredient_product_counts,
        manifest=manifest,
    )
    return report, details


def _load_recommendable_products(data_dir: Path) -> dict[str, tuple[str, str]]:
    products: dict[str, tuple[str, str]] = {}
    for row in _read_rows(sorted((data_dir / "products").glob("products_*.csv"))):
        if row.get("is_recommendable", "").casefold() == "true":
            products[row["product_id"]] = (row["brand"], row["name"])
    return products


def _load_ingredient_effects(
    data_dir: Path,
) -> dict[str, list[tuple[str, str, float]]]:
    effects_by_ingredient: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in _read_rows([data_dir / "ingredient_effect.csv"]):
        effects_by_ingredient[row["ingredient_id"]].append(
            (row["effect_id"], row["effect_name"], float(row["effect_score"]))
        )
    return effects_by_ingredient


def _load_evidence(
    data_dir: Path,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], list[tuple[str, str]]]:
    current_evidence: dict[tuple[str, str], float] = {}
    accepted_evidence: dict[tuple[str, str], float] = {}
    accepted_pairs: list[tuple[str, str]] = []
    for row in _read_rows([data_dir / "ingredient_evidence.csv"]):
        key = (row["ingredient_id"], row["effect_id"])
        authority = float(row["source_authority_score"] or 1.0)
        effective = float(row["evidence_score"]) * min(1.0, max(0.0, authority))
        current_evidence[key] = max(current_evidence.get(key, 0.0), effective)
        if _score_eligible(row):
            accepted_evidence[key] = max(accepted_evidence.get(key, 0.0), effective)
            accepted_pairs.append(key)
    return current_evidence, accepted_evidence, accepted_pairs


def _score_eligible(row: dict[str, str]) -> bool:
    return (
        row["review_status"] == "accepted"
        and row["is_current"] == "true"
        and row["result_direction"] == "positive"
        and row["score_use_level"] in {"primary", "supporting"}
    )


def _load_top_ingredients(
    data_dir: Path,
    products: dict[str, tuple[str, str]],
    effects_by_ingredient: dict[str, list[tuple[str, str, float]]],
) -> tuple[
    dict[tuple[str, str], list[tuple[float, int, str]]],
    dict[str, set[str]],
]:
    top_ingredients: dict[tuple[str, str], list[tuple[float, int, str]]] = {}
    ingredient_product_counts: dict[str, set[str]] = defaultdict(set)
    shards = sorted((data_dir / "product_ingredients").glob("product_ingredients_*.csv"))
    for row in _read_rows(shards):
        product_id = row["product_id"]
        if product_id not in products:
            continue
        ingredient_id = row["ingredient_id"]
        effect_rows = effects_by_ingredient.get(ingredient_id)
        if not effect_rows:
            continue
        ingredient_product_counts[ingredient_id].add(product_id)
        display_order = int(row["display_order"] or 999)
        for effect_id, _effect_name, effect_score in effect_rows:
            values = top_ingredients.setdefault((product_id, effect_id), [])
            if any(existing[2] == ingredient_id for existing in values):
                continue
            values.append((effect_score, display_order, ingredient_id))
            values.sort(key=lambda value: (-value[0], value[1]))
            del values[3:]
    return top_ingredients, ingredient_product_counts


def _build_details(
    products: dict[str, tuple[str, str]],
    top_ingredients: dict[tuple[str, str], list[tuple[float, int, str]]],
    effect_names: dict[str, str],
    current_evidence: dict[tuple[str, str], float],
    accepted_evidence: dict[tuple[str, str], float],
) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for (product_id, effect_id), ingredients in top_ingredients.items():
        current = _evidence_component(ingredients, effect_id, current_evidence)
        accepted = _evidence_component(ingredients, effect_id, accepted_evidence)
        brand, name = products[product_id]
        details.append(
            {
                "product_id": product_id,
                "brand": brand,
                "name": name,
                "effect_id": effect_id,
                "effect_name": effect_names[effect_id],
                "current_evidence_component": round(current, 6),
                "accepted_evidence_component": round(accepted, 6),
                "component_delta": round(current - accepted, 6),
                "default_total_score_delta_points": round(
                    (current - accepted) * DEFAULT_INGREDIENT_EVIDENCE_WEIGHT * 100,
                    3,
                ),
                "top_ingredients": ";".join(value[2] for value in ingredients),
            }
        )
    details.sort(
        key=lambda row: (
            -float(row["component_delta"]),
            str(row["effect_id"]),
            str(row["product_id"]),
        )
    )
    return details


def _evidence_component(
    ingredients: list[tuple[float, int, str]],
    effect_id: str,
    evidence_map: dict[tuple[str, str], float],
) -> float:
    total = sum(
        evidence_map.get((ingredient_id, effect_id), 0.0) / 100 * decay
        for (_effect_score, _display_order, ingredient_id), decay in zip(
            ingredients,
            TOP_INGREDIENT_DECAYS,
            strict=False,
        )
    )
    return min(1.0, max(0.0, total))


def _build_report(
    *,
    products: dict[str, tuple[str, str]],
    details: list[dict[str, object]],
    effect_names: dict[str, str],
    accepted_pairs: list[tuple[str, str]],
    ingredient_product_counts: dict[str, set[str]],
    manifest: tuple[tuple[str, str], ...],
) -> str:
    by_effect: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in details:
        by_effect[str(row["effect_id"])].append(row)
    current_products = {
        str(row["product_id"])
        for row in details
        if float(row["current_evidence_component"]) > 0
    }
    accepted_products = {
        str(row["product_id"])
        for row in details
        if float(row["accepted_evidence_component"]) > 0
    }
    delta_values = [float(row["default_total_score_delta_points"]) for row in details]
    manifest_digest = sha256(
        "\n".join(f"{path}:{digest}" for path, digest in manifest).encode()
    ).hexdigest()

    lines = [
        "# accepted-only 근거 게이트 영향 측정",
        "",
        "> 작성일: 2026-07-11",
        ">",
        "> 상태: 읽기 전용 분석. scoring 코드와 DB는 변경하지 않았다.",
        "",
        "## 재현 방법",
        "",
        "```bash",
        "python data/scripts/analyze_evidence_gate_impact.py",
        "```",
        "",
        f"Source manifest SHA256: `{manifest_digest}`",
        "",
        "## 전체 요약",
        "",
        f"- 추천 가능 상품: {len(products):,}개",
        f"- 현재 근거점수가 하나라도 있는 상품: {len(current_products):,}개",
        f"- accepted-only 후 근거점수가 남는 상품: {len(accepted_products):,}개",
        f"- accepted 근거쌍: {len(accepted_pairs)}개",
        f"- 상품×효능 조합: {len(details):,}개",
        "",
        "## 효능축별 영향",
        "",
        "| 효능축 | 상품×축 | 현재 근거 있음 | 게이트 후 근거 있음 | 평균 근거점수 현재→후 | 평균 총점 감소 추정 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for effect_id in sorted(by_effect, key=lambda value: effect_names[value]):
        rows = by_effect[effect_id]
        current_values = [float(row["current_evidence_component"]) for row in rows]
        accepted_values = [float(row["accepted_evidence_component"]) for row in rows]
        delta_points = [float(row["default_total_score_delta_points"]) for row in rows]
        lines.append(
            f"| {effect_names[effect_id]} | {len(rows):,} | "
            f"{sum(value > 0 for value in current_values):,} | "
            f"{sum(value > 0 for value in accepted_values):,} | "
            f"{mean(current_values):.3f}→{mean(accepted_values):.3f} | "
            f"{mean(delta_points):.2f}점 |"
        )

    lines.extend(
        [
            "",
            "## accepted 4쌍의 상품 범위",
            "",
            "| 성분×효능 | 해당 성분 포함 추천상품 | top 3에 들어 게이트 후 점수에 기여 |",
            "| --- | ---: | ---: |",
        ]
    )
    for ingredient_id, effect_id in sorted(accepted_pairs):
        contribution_count = sum(
            float(row["accepted_evidence_component"]) > 0
            and str(row["effect_id"]) == effect_id
            and ingredient_id in str(row["top_ingredients"]).split(";")
            for row in details
        )
        lines.append(
            f"| {ingredient_id} × {effect_names[effect_id]} | "
            f"{len(ingredient_product_counts[ingredient_id]):,} | {contribution_count:,} |"
        )

    lines.extend(
        [
            "",
            "## 판정",
            "",
            f"- 단일 효능 질의 기준 총점 감소 추정 중앙값은 {median(delta_values):.2f}점, 평균은 {mean(delta_values):.2f}점이다.",
            "- 이 값은 기본 가중치에서 근거점수 항목만 바꾼 추정치이며 검색·가격·피부 적합 등 다른 점수는 유지한 값이다.",
            "- 미백·주름·각질 축에는 accepted 근거가 아직 없어 게이트를 즉시 켜면 해당 축의 근거점수가 전부 0이 된다.",
            "- 따라서 PR #434에서는 상태를 저장하되 accepted-only 점수 게이트는 활성화하지 않는다.",
            "",
            "## Source manifest",
            "",
            "| 파일 | SHA256 |",
            "| --- | --- |",
        ]
    )
    lines.extend(f"| `{path}` | `{digest}` |" for path, digest in manifest)
    return "\n".join(lines) + "\n"


def _source_files(data_dir: Path) -> list[Path]:
    return [
        *sorted((data_dir / "products").glob("products_*.csv")),
        *sorted((data_dir / "product_ingredients").glob("product_ingredients_*.csv")),
        data_dir / "ingredient_effect.csv",
        data_dir / "ingredient_evidence.csv",
    ]


def _build_manifest(
    paths: list[Path],
    *,
    root: Path,
) -> tuple[tuple[str, str], ...]:
    manifest = []
    for path in paths:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest.append((path.relative_to(root).as_posix(), digest.hexdigest()))
    return tuple(manifest)


def _read_rows(paths: list[Path]):
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as source:
            yield from csv.DictReader(source)


def _write_details(path: Path, details: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)


if __name__ == "__main__":
    main()
