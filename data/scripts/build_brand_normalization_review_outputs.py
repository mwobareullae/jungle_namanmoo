#!/usr/bin/env python3
"""Create Korean review outputs from brand normalization report."""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter
from pathlib import Path


CORRECTION_FIELDS = [
    "product_code",
    "source_prefix",
    "current_brand",
    "corrected_brand",
    "product_name",
    "confidence",
    "basis",
    "note",
]

ALIAS_FIELDS = [
    "canonical_brand",
    "alias_brand",
    "source_row_count",
    "source_prefixes",
    "sample_product_codes",
    "confidence",
    "basis",
    "note",
]

CORRECTION_HEADERS = [
    ("product_code", "상품 ID"),
    ("source_prefix", "수집처"),
    ("current_brand", "현재 브랜드"),
    ("corrected_brand", "수정할 브랜드"),
    ("product_name", "상품명"),
    ("confidence", "신뢰도"),
    ("basis", "판단 기준"),
    ("note", "비고"),
]

ALIAS_HEADERS = [
    ("canonical_brand", "대표 브랜드"),
    ("alias_brand", "같은 브랜드 표기"),
    ("source_row_count", "대상 row 수"),
    ("source_prefixes", "수집처 분포"),
    ("sample_product_codes", "예시 상품 ID"),
    ("confidence", "신뢰도"),
    ("basis", "판단 기준"),
    ("note", "비고"),
]

MANUAL_HEADERS = [
    ("product_code", "상품 ID"),
    ("source_prefix", "수집처"),
    ("current_brand", "현재 브랜드"),
    ("suspected_brand", "추정 브랜드"),
    ("product_name", "상품명"),
    ("note", "비고"),
]

BASIS_MAP = {
    "product_name_prefix_match": "상품명이 수정할 브랜드명으로 시작함",
    "known_display_alias": "같은 브랜드의 다른 영문 표기",
    "korean_english_display_alias": "한글/영문 브랜드 표기 차이",
}

NOTE_PREFIX_MAP = {
    "same product_name appears under multiple brands; brands=": "같은 상품명이 여러 브랜드에 연결됨; 브랜드 목록=",
}

VALUE_MAP = {
    "product_name starts with a different known brand token": "상품명이 현재 브랜드가 아닌 다른 브랜드명으로 시작함",
    "same brand family; alias only, not brand pollution": "같은 브랜드 계열의 표기 차이이며, 브랜드 오염은 아님",
    "Korean/English brand display alias": "한글/영문 브랜드 표기 차이",
    "known_display_alias": "같은 브랜드의 다른 영문 표기",
    "korean_english_display_alias": "한글/영문 브랜드 표기 차이",
    "product_name_prefix_match": "상품명이 수정할 브랜드명으로 시작함",
    "cultbeauty": "컬트뷰티",
    "lookfantastic": "룩판타스틱",
    "sephora": "세포라",
    "ulta": "얼타",
    "dermstore": "덤스토어",
    "oliveyoung": "올리브영",
}


def main() -> None:
    args = parse_args()
    report_rows = read_csv(args.report)
    corrections = build_corrections(report_rows)
    aliases = build_alias_candidates(report_rows)
    manual_rows = [row for row in report_rows if row.get("recommended_action") == "manual_review"]

    write_csv(args.output_corrections, CORRECTION_FIELDS, corrections)
    write_csv(args.output_aliases, ALIAS_FIELDS, aliases)
    write_review_html(
        args.output_html,
        report_rows=report_rows,
        corrections=corrections,
        aliases=aliases,
        manual_rows=manual_rows,
    )
    print(
        "BrandReviewOutputs("
        f"report_rows={len(report_rows)}, "
        f"corrections={len(corrections)}, "
        f"aliases={len(aliases)}, "
        f"manual_rows={len(manual_rows)}, "
        f"html='{args.output_html}'"
        ")"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split brand normalization report into correction, alias, and Korean HTML review outputs."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reconciliation/brand_normalization_report.csv"),
    )
    parser.add_argument(
        "--output-corrections",
        type=Path,
        default=Path("data/reconciliation/brand_corrections.csv"),
    )
    parser.add_argument(
        "--output-aliases",
        type=Path,
        default=Path("data/reconciliation/brand_alias_candidates.csv"),
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=Path("data/reconciliation/brand_normalization_review.html"),
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_corrections(report_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in report_rows:
        if row.get("recommended_action") != "fix_brand":
            continue
        rows.append(
            {
                "product_code": row["product_code"],
                "source_prefix": row["source_prefix"],
                "current_brand": row["current_brand"],
                "corrected_brand": row["suspected_brand"],
                "product_name": row["product_name"],
                "confidence": row["confidence"],
                "basis": "product_name_prefix_match",
                "note": row["note"],
            }
        )
    return rows


def build_alias_candidates(report_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    alias_groups = {
        ("Dr Dennis Gross", "Dr. Dennis Gross Skincare"): {
            "canonical_brand": "Dr Dennis Gross",
            "alias_brand": "Dr. Dennis Gross Skincare",
            "basis": "known_display_alias",
            "confidence": "0.90",
            "note": "same brand family; alias only, not brand pollution",
        },
        ("Numbuzin", "넘버즈인"): {
            "canonical_brand": "Numbuzin",
            "alias_brand": "넘버즈인",
            "basis": "korean_english_display_alias",
            "confidence": "0.90",
            "note": "Korean/English brand display alias",
        },
    }
    stats: dict[tuple[str, str], dict[str, object]] = {}
    for key, meta in alias_groups.items():
        stats[key] = {
            **meta,
            "source_row_count": 0,
            "source_prefixes": Counter(),
            "sample_product_codes": [],
        }

    for row in report_rows:
        if row.get("recommended_action") != "add_brand_alias":
            continue
        key = alias_pair_key(row["current_brand"], row["suspected_brand"])
        if not key:
            continue
        stat = stats[key]
        stat["source_row_count"] = int(stat["source_row_count"]) + 1
        stat["source_prefixes"][row["source_prefix"]] += 1
        samples = stat["sample_product_codes"]
        if len(samples) < 10:
            samples.append(row["product_code"])

    rows: list[dict[str, str]] = []
    for stat in stats.values():
        rows.append(
            {
                "canonical_brand": str(stat["canonical_brand"]),
                "alias_brand": str(stat["alias_brand"]),
                "source_row_count": str(stat["source_row_count"]),
                "source_prefixes": "; ".join(
                    f"{translate_value(source)}:{count}"
                    for source, count in stat["source_prefixes"].most_common()
                ),
                "sample_product_codes": "; ".join(stat["sample_product_codes"]),
                "confidence": str(stat["confidence"]),
                "basis": str(stat["basis"]),
                "note": str(stat["note"]),
            }
        )
    return rows


def alias_pair_key(current_brand: str, suspected_brand: str) -> tuple[str, str] | None:
    pair = {current_brand, suspected_brand}
    if pair == {"Dr Dennis Gross", "Dr. Dennis Gross Skincare"}:
        return ("Dr Dennis Gross", "Dr. Dennis Gross Skincare")
    if pair == {"Numbuzin", "넘버즈인"}:
        return ("Numbuzin", "넘버즈인")
    return None


def write_review_html(
    path: Path,
    *,
    report_rows: list[dict[str, str]],
    corrections: list[dict[str, str]],
    aliases: list[dict[str, str]],
    manual_rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fix_source_counts = Counter(translate_value(row["source_prefix"]) for row in corrections)
    fix_brand_counts = Counter(row["corrected_brand"] for row in corrections)
    manual_html_rows = [
        {
            "product_code": row["product_code"],
            "source_prefix": row["source_prefix"],
            "current_brand": row["current_brand"],
            "suspected_brand": row["suspected_brand"],
            "product_name": row["product_name"],
            "note": row["note"],
        }
        for row in manual_rows
    ]

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>브랜드 정규화 검수 리포트</title>
<style>
body {{ margin: 0; padding: 32px; font-family: Arial, "Malgun Gothic", sans-serif; color: #172018; background: #f7f4ec; }}
h1 {{ margin: 0 0 10px; font-size: 30px; }}
h2 {{ margin: 34px 0 12px; font-size: 22px; }}
.lead {{ color: #5e675f; line-height: 1.55; }}
.grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }}
.card {{ background: #fffdf8; border: 1px solid #ded7c9; border-radius: 10px; padding: 16px; }}
.num {{ font-size: 28px; font-weight: 800; color: #28553d; }}
.label {{ margin-top: 6px; color: #636b64; font-size: 14px; }}
.note {{ background: #eef5ef; border-left: 4px solid #2f5d45; padding: 14px 16px; line-height: 1.65; }}
table {{ width: 100%; border-collapse: collapse; background: white; margin: 12px 0 24px; table-layout: fixed; }}
th, td {{ border: 1px solid #ddd5c8; padding: 9px 10px; vertical-align: top; word-break: break-word; font-size: 13px; }}
th {{ background: #e8efe8; color: #1f3529; text-align: left; }}
tr:nth-child(even) td {{ background: #fbfaf6; }}
.pill {{ display: inline-block; border: 1px solid #cbd7cd; border-radius: 999px; padding: 6px 10px; margin: 4px 6px 4px 0; background: #fffdf8; }}
.small {{ color: #6b746c; font-size: 13px; }}
code {{ background: #f0eadf; padding: 2px 5px; border-radius: 4px; }}
@media (max-width: 900px) {{ body {{ padding: 18px; }} .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
</style>
</head>
<body>
<h1>브랜드 정규화 검수 리포트</h1>
<p class="lead">추천 로직에서 예외 처리하지 않고, 데이터 정제 단계에서 처리하기 위한 브랜드 표기 차이와 브랜드 오염 후보입니다.</p>
<div class="grid">
  <div class="card"><div class="num">{len(report_rows):,}</div><div class="label">전체 검수 후보</div></div>
  <div class="card"><div class="num">{len(corrections):,}</div><div class="label">자동 수정 후보</div></div>
  <div class="card"><div class="num">{len(aliases):,}</div><div class="label">같은 브랜드 표기 후보</div></div>
  <div class="card"><div class="num">{len(manual_rows):,}</div><div class="label">사람 확인 필요</div></div>
</div>
<div class="note">
  <b>검수 방법</b><br />
  1. <b>자동 수정 후보 전체</b>에서 상품명이 정말 <b>수정할 브랜드</b>로 시작하는지만 확인합니다.<br />
  2. 맞으면 <code>brand_corrections.csv</code>를 데이터 적재 전처리에 반영하면 됩니다.<br />
  3. <b>같은 브랜드 표기 후보</b>는 브랜드를 바꾸는 게 아니라 별칭으로 묶는 후보입니다.<br />
  4. <b>사람 확인 필요</b>는 지금 바로 고치지 말고 나중에 우선순위를 정해 검수합니다.
</div>
<h2>자동 수정 후보 - 수집처별</h2>
{''.join(pill(label, count) for label, count in fix_source_counts.most_common())}
<h2>자동 수정 후보 - 수정할 브랜드별</h2>
{''.join(pill(label, count) for label, count in fix_brand_counts.most_common())}
<h2>같은 브랜드 표기 후보</h2>
{html_table(ALIAS_HEADERS, aliases)}
<h2>자동 수정 후보 전체</h2>
{html_table(CORRECTION_HEADERS, corrections)}
<h2>사람 확인 필요 샘플 200개</h2>
<p class="small">전체 사람 확인 필요 목록은 <code>brand_normalization_manual_review.csv</code>를 확인하세요.</p>
{html_table(MANUAL_HEADERS, manual_html_rows, limit=200)}
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def html_table(headers: list[tuple[str, str]], rows: list[dict[str, str]], limit: int | None = None) -> str:
    shown = rows if limit is None else rows[:limit]
    head = "".join(f"<th>{escape(label)}</th>" for _key, label in headers)
    body = []
    for row in shown:
        body.append(
            "<tr>"
            + "".join(f"<td>{escape(translate_value(row.get(key, '')))}</td>" for key, _label in headers)
            + "</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def pill(label: str, count: int) -> str:
    return f"<span class='pill'>{escape(label)}: {count}</span>"


def translate_value(value: object) -> str:
    text = str(value if value is not None else "")
    if text in VALUE_MAP:
        return VALUE_MAP[text]
    for prefix, replacement in NOTE_PREFIX_MAP.items():
        if text.startswith(prefix):
            return replacement + text[len(prefix):]
    return text


def escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


if __name__ == "__main__":
    main()
