from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


OUTPUT_FIELDS = [
    "action",
    "pending_code",
    "raw_name",
    "normalized_source_name",
    "expected_connection_count",
    "target_ingredient_code",
    "target_name_ko",
    "target_name_en",
    "decision_reason",
    "source_reference",
]
PENDING_PREFIXES = ("ing_pending_", "foreign_pending_")
MOJIBAKE_MARKERS = frozenset("ÃÂâìëð�")
BOILERPLATE_PATTERNS = (
    r"\s+[Tt]he list of ingredients\b",
    r"\s+[Ii]ngredients may change\b",
    r"\s+[Pp]lease (?:always )?(?:read|refer)\b",
    r"\s+[Pp]roduct [Dd]isclosures?\b",
    r"\s+[Tt]his [Ss]et [Cc]ontains\b",
    r"\s+[Dd]ermatologist tested\b",
    r"\s+[Ff]ormulated without\b",
    r"\s+[Nn]ut [Ff]ree\b",
    r"\s+\*{1,2}\s*(?:Natural|Organic|Certified)\b",
)
MARKETING_MARKERS = (
    "the list of ingredients",
    "ingredients may change",
    "please refer to the packaging",
    "please always read",
    "product disclosures",
    "dermatologist tested",
    "formulated without",
    "supplement facts",
    "servings per container",
    "visit ",
)
STRAY_CHOSEONG_TO_JONGSEONG = {
    "ᄀ": 1,
    "ᄁ": 2,
    "ᄂ": 4,
    "ᄃ": 7,
    "ᄅ": 8,
    "ᄆ": 16,
    "ᄇ": 17,
    "ᄉ": 19,
    "ᄊ": 20,
    "ᄋ": 21,
    "ᄌ": 22,
    "ᄎ": 23,
    "ᄏ": 24,
    "ᄐ": 25,
    "ᄑ": 26,
    "ᄒ": 27,
}


@dataclass(frozen=True)
class GenerationSummary:
    input_rows: int
    output_rows: int
    mapped_existing: int
    created_canonical: int
    excluded_rows: int


@dataclass(frozen=True)
class ExcludedRow:
    pending_code: str
    normalized_source_name: str
    raw_name: str
    risk_score: int
    reason: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def backend_normalize(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _mojibake_score(value: str) -> int:
    return sum(char in MOJIBAKE_MARKERS or 0x80 <= ord(char) <= 0x9F for char in value)


def repair_mojibake(value: str) -> str:
    """UTF-8 바이트를 latin-1/cp1252로 잘못 읽은 원문을 보수적으로 복구한다."""

    best = value
    for _ in range(2):
        best_score = _mojibake_score(best)
        improved = False
        for encoding in ("latin-1", "cp1252"):
            try:
                candidate = best.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            score = _mojibake_score(candidate)
            if score < best_score:
                best = candidate
                best_score = score
                improved = True
        if not improved:
            break
    return best


def _attach_stray_choseong(value: str) -> str:
    """NFKC 뒤 남은 초성 자모를 직전 완성형 음절의 종성으로 결합한다."""

    output: list[str] = []
    for char in value:
        jongseong = STRAY_CHOSEONG_TO_JONGSEONG.get(char)
        if jongseong is not None and output:
            previous = ord(output[-1])
            if 0xAC00 <= previous <= 0xD7A3 and (previous - 0xAC00) % 28 == 0:
                output[-1] = chr(previous + jongseong)
                continue
        output.append(char)
    return "".join(output)


def normalize_display_name(value: str | None) -> str:
    """신규 canonical 표시명에만 적용하는 복구/정리 규칙."""

    text = repair_mojibake(value or "")
    text = _attach_stray_choseong(unicodedata.normalize("NFKC", text))
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    text = re.sub(r"(?:\?|\ufffd){2,}\s*\d*\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    boilerplate_matches = [
        match
        for pattern in BOILERPLATE_PATTERNS
        if (match := re.search(pattern, text, flags=re.IGNORECASE)) is not None and match.start() >= 2
    ]
    if boilerplate_matches:
        text = text[: min(match.start() for match in boilerplate_matches)]
    return text.strip(" \t\r\n,;:|.-")


def _looks_latin(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and sum(ord(char) < 128 for char in letters) / len(letters) >= 0.85


def _new_target_code(pending_code: str) -> str:
    if pending_code.startswith("ing_pending_"):
        suffix = pending_code.removeprefix("ing_pending_")
    elif pending_code.startswith("foreign_pending_"):
        suffix = f"foreign_{pending_code.removeprefix('foreign_pending_')}"
    else:
        suffix = re.sub(r"[^a-z0-9]+", "_", pending_code.lower()).strip("_")
    return f"ing_generated_{suffix}"


def _risk(row: dict[str, str], cleaned_name: str, ambiguous: bool) -> tuple[int, str]:
    raw = row.get("raw_name", "")
    repaired_raw = repair_mojibake(raw)
    lowered = repaired_raw.casefold()
    reasons: list[str] = []
    score = 0
    if not cleaned_name:
        score += 10_000
        reasons.append("정규화 후 빈 값")
    if ambiguous:
        score += 4_000
        reasons.append("기존 canonical 정확 일치 충돌")
    marker_count = sum(marker in lowered for marker in MARKETING_MARKERS)
    boilerplate_recovered = (
        marker_count > 0
        and len(cleaned_name) >= 2
        and len(cleaned_name) <= max(2, int(len(repaired_raw) * 0.6))
    )
    if marker_count and not boilerplate_recovered:
        score += 1_000 + marker_count * 100
        reasons.append("마케팅/안내 문구 포함")
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        score += 900
        reasons.append("URL 포함")
    replacement_count = raw.count("�") + len(re.findall(r"\?{2,}", raw))
    if replacement_count:
        score += 700 + replacement_count * 20
        reasons.append("깨진 문자 잔존")
    remaining_mojibake = _mojibake_score(repair_mojibake(raw))
    if remaining_mojibake:
        score += 600 + remaining_mojibake * 10
        reasons.append("복구 불가 인코딩")
    if len(cleaned_name) > 160:
        score += 100 + len(cleaned_name)
        reasons.append("비정상적으로 긴 원문")
    elif len(cleaned_name) > 100:
        score += 120 + len(cleaned_name)
        reasons.append("긴 복합 원문")
    if len(cleaned_name) < 2:
        score += 500
        reasons.append("성분명 길이 부족")
    return score, ", ".join(reasons) or "낮은 자동 판정 신뢰도"


def _load_canonical_index(
    ingredients_path: Path,
    aliases_path: Path,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    index: dict[str, set[str]] = defaultdict(set)
    pending_names: dict[str, str] = {}
    canonical_codes: set[str] = set()
    ingredient_rows = read_csv(ingredients_path)
    for row in ingredient_rows:
        code = row["ingredient_id"].strip()
        if code.startswith(PENDING_PREFIXES):
            pending_names[code] = row.get("name_ko", "").strip() or row.get("name_en", "").strip()
            continue
        canonical_codes.add(code)
        for name in (row.get("name_ko", ""), row.get("name_en", "")):
            key = backend_normalize(name)
            if key:
                index[key].add(code)
    for row in read_csv(aliases_path):
        code = row.get("canonical_id", "").strip()
        key = backend_normalize(row.get("alias", ""))
        if code in canonical_codes and key:
            index[key].add(code)
    return index, pending_names


def generate_mapping_csv(
    *,
    pending_path: Path,
    ingredients_path: Path,
    aliases_path: Path,
    output_path: Path,
    excluded_count: int = 20,
    report_path: Path | None = None,
) -> tuple[GenerationSummary, list[ExcludedRow]]:
    pending_rows = read_csv(pending_path)
    index, pending_names = _load_canonical_index(ingredients_path, aliases_path)
    prepared: list[tuple[dict[str, str], dict[str, str], int, str]] = []
    create_candidates: list[tuple[int, str, str]] = []

    for position, row in enumerate(pending_rows):
        pending_code = row.get("pending_code", "").strip()
        raw_name = row.get("raw_name", "")
        master_name = pending_names.get(pending_code, raw_name)
        cleaned_name = normalize_display_name(master_name) or normalize_display_name(raw_name)
        lookup_keys = {
            backend_normalize(raw_name),
            backend_normalize(row.get("normalized_source_name", "")),
            backend_normalize(cleaned_name),
        }
        matches: set[str] = set()
        for key in lookup_keys:
            if key:
                matches.update(index.get(key, set()))
        ambiguous = len(matches) > 1
        risk_score, risk_reason = _risk(row, cleaned_name, ambiguous)
        output = {field: row.get(field, "") for field in OUTPUT_FIELDS}
        if len(matches) == 1:
            output.update(
                action="MAP_EXISTING",
                target_ingredient_code=next(iter(matches)),
                target_name_ko="",
                target_name_en="",
                decision_reason="정규화명 또는 별칭 정확 일치",
                source_reference="운영 미판정 일회성 매핑 2026-07-23",
            )
        else:
            output.update(
                action="CREATE_AND_MAP",
                target_ingredient_code=_new_target_code(pending_code),
                target_name_ko=cleaned_name,
                target_name_en=cleaned_name if _looks_latin(cleaned_name) else "",
                decision_reason="복합 원료 또는 신규 원문 canonical 생성",
                source_reference=(
                    "운영 미판정 일회성 매핑 2026-07-23; "
                    "generate_production_ingredient_mapping_csv.py"
                ),
            )
            create_candidates.append((risk_score, pending_code, row.get("normalized_source_name", "")))
        prepared.append((row, output, risk_score, risk_reason))

    excluded_keys = {
        (pending_code, normalized_name)
        for _, pending_code, normalized_name in sorted(
            create_candidates,
            key=lambda item: (-item[0], item[1], item[2]),
        )[:excluded_count]
    }
    output_rows: list[dict[str, str]] = []
    excluded: list[ExcludedRow] = []
    mapped_existing = 0
    created_canonical = 0
    for source, output, risk_score, risk_reason in prepared:
        key = (source.get("pending_code", ""), source.get("normalized_source_name", ""))
        if key in excluded_keys:
            excluded.append(
                ExcludedRow(
                    pending_code=key[0],
                    normalized_source_name=key[1],
                    raw_name=source.get("raw_name", ""),
                    risk_score=risk_score,
                    reason=risk_reason,
                )
            )
            continue
        output_rows.append(output)
        if output["action"] == "MAP_EXISTING":
            mapped_existing += 1
        else:
            created_canonical += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    summary = GenerationSummary(
        input_rows=len(pending_rows),
        output_rows=len(output_rows),
        mapped_existing=mapped_existing,
        created_canonical=created_canonical,
        excluded_rows=len(excluded),
    )
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {"summary": asdict(summary), "excluded": [asdict(row) for row in excluded]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return summary, excluded


def main() -> int:
    parser = argparse.ArgumentParser(description="운영 미판정 성분을 관리자 업로드용 매핑 CSV로 변환")
    parser.add_argument("--pending-csv", type=Path, required=True)
    parser.add_argument("--ingredients-csv", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--aliases-csv", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--excluded-count", type=int, default=20)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    summary, excluded = generate_mapping_csv(
        pending_path=args.pending_csv,
        ingredients_path=args.ingredients_csv,
        aliases_path=args.aliases_csv,
        output_path=args.output,
        excluded_count=args.excluded_count,
        report_path=args.report,
    )
    print(json.dumps({"summary": asdict(summary), "excluded": [asdict(row) for row in excluded]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
