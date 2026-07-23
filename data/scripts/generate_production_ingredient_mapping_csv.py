from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
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
SOURCE_REFERENCE = "운영 미판정 export 및 운영 추천 스냅샷 2026-07-23"
GENERATED_SOURCE_REFERENCE = f"{SOURCE_REFERENCE}; production mapping generator"
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
# NFKC 후 종성 자리에 남은 현대 한글 초성을 앞 음절의 종성으로 결합한다.
STRAY_CHOSEONG_TO_JONGSEONG = {
    "\u1100": 1,
    "\u1101": 2,
    "\u1102": 4,
    "\u1103": 7,
    "\u1105": 8,
    "\u1106": 16,
    "\u1107": 17,
    "\u1109": 19,
    "\u110a": 20,
    "\u110b": 21,
    "\u110c": 22,
    "\u110e": 23,
    "\u110f": 24,
    "\u1110": 25,
    "\u1111": 26,
    "\u1112": 27,
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
    replacement = value.count("\ufffd") + len(re.findall(r"\?{2,}", value))
    control = sum(0x80 <= ord(char) <= 0x9F for char in value)
    common_markers = sum(value.count(marker) for marker in ("Ã", "Â", "â", "í", "ë", "ì", "ð"))
    hangul = sum("가" <= char <= "힣" for char in value)
    return replacement * 100 + control * 20 + common_markers * 3 - hangul


def repair_mojibake(value: str) -> str:
    """UTF-8 바이트가 latin-1/cp1252로 잘못 해석된 원문을 보수적으로 복구한다."""

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
    """신규 canonical 표시명에만 적용하는 복구·정리 규칙."""

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


def _display_risk(value: str) -> int:
    lowered = value.casefold()
    score = 0
    if not value:
        return 100_000
    if len(value) > 255:
        score += 90_000 + len(value)
    if any(marker in lowered for marker in MARKETING_MARKERS):
        score += 2_000
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        score += 2_000
    if "\ufffd" in value or re.search(r"\?{2,}", value):
        score += 1_500
    score += max(0, len(value) - 100)
    if len(value) < 2:
        score += 1_000
    return score


def _row_risk(
    row: dict[str, str],
    cleaned_name: str,
    candidate_type: str,
) -> tuple[int, str]:
    normalized = row.get("normalized_source_name", "")
    raw = row.get("raw_name", "")
    reasons: list[str] = []
    score = _display_risk(cleaned_name)
    if not normalized:
        score += 200_000
        reasons.append("정규화 원문 없음")
    elif len(normalized) > 255:
        score += 200_000 + len(normalized)
        reasons.append("정규화 원문 255자 초과")
    elif normalized != backend_normalize(normalized):
        score += 200_000
        reasons.append("백엔드 정규화 규칙 불일치")
    if not cleaned_name:
        reasons.append("신규 canonical 표시명 없음")
    elif len(cleaned_name) > 255:
        reasons.append("신규 canonical 표시명 255자 초과")
    lowered = raw.casefold()
    if any(marker in lowered for marker in MARKETING_MARKERS):
        score += 1_000
        reasons.append("마케팅·안내 문구 포함")
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        score += 900
        reasons.append("URL 포함")
    if "\ufffd" in raw or re.search(r"\?{2,}", raw):
        score += 700
        reasons.append("깨진 문자 의심")
    if candidate_type == "EXACT_MATCH_CONFLICT":
        score += 100_000
        reasons.append("운영 canonical 정확 일치 충돌")
    if len(raw) > 255:
        score += len(raw)
        reasons.append("긴 원문")
    return score, ", ".join(reasons) or "자동 판정 보류 상위 위험군"


def _load_pending_names(ingredients_path: Path | None) -> dict[str, str]:
    if ingredients_path is None or not ingredients_path.exists():
        return {}
    pending_names: dict[str, str] = {}
    for row in read_csv(ingredients_path):
        code = row.get("ingredient_id", "").strip()
        if not code.startswith(PENDING_PREFIXES):
            continue
        name = row.get("name_ko", "").strip() or row.get("name_en", "").strip()
        if name:
            pending_names[code] = name
    return pending_names


def _load_suggestions(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    suggestions: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv(path):
        key = (row.get("pending_code", "").strip(), row.get("normalized_source_name", ""))
        if not all(key):
            raise ValueError(f"운영 추천 스냅샷에 빈 식별자가 있습니다: {key!r}")
        if key in suggestions:
            raise ValueError(f"운영 추천 스냅샷에 중복 식별자가 있습니다: {key!r}")
        suggestions[key] = row
    return suggestions


def _select_display_names(
    pending_rows: list[dict[str, str]],
    pending_names: dict[str, str],
) -> dict[str, str]:
    candidates: dict[str, list[tuple[bool, str]]] = defaultdict(list)
    for row in pending_rows:
        code = row.get("pending_code", "").strip()
        if code in pending_names:
            candidates[code].append((True, normalize_display_name(pending_names[code])))
        candidates[code].append((False, normalize_display_name(row.get("raw_name", ""))))

    selected: dict[str, str] = {}
    for code, values in candidates.items():
        distinct = {(is_master, value) for is_master, value in values if value}
        if not distinct:
            selected[code] = ""
            continue
        selected[code] = min(
            distinct,
            key=lambda item: (
                _display_risk(item[1]),
                0 if item[0] else 1,
                len(item[1]),
                item[1].casefold(),
            ),
        )[1]
    return selected


def _validate_output_rows(
    rows: list[dict[str, str]],
    expected_count: int,
) -> None:
    errors: list[str] = []
    if len(rows) != expected_count:
        errors.append(f"행 수 불일치: expected={expected_count}, actual={len(rows)}")
    identities: set[tuple[str, str]] = set()
    create_definitions: dict[str, tuple[str, str]] = {}
    for number, row in enumerate(rows, start=2):
        key = (row["pending_code"], row["normalized_source_name"])
        if key in identities:
            errors.append(f"{number}행 중복 식별자: {key!r}")
        identities.add(key)
        for field, limit in (
            ("pending_code", 64),
            ("normalized_source_name", 255),
            ("target_ingredient_code", 64),
            ("target_name_ko", 255),
            ("target_name_en", 255),
            ("decision_reason", 1000),
            ("source_reference", 255),
        ):
            if len(row[field]) > limit:
                errors.append(f"{number}행 {field} {limit}자 초과")
        if not row["pending_code"] or not row["normalized_source_name"] or not row["target_ingredient_code"]:
            errors.append(f"{number}행 필수 식별자 누락")
        if row["normalized_source_name"] != backend_normalize(row["normalized_source_name"]):
            errors.append(f"{number}행 normalized_source_name 정규화 불일치")
        try:
            if int(row["expected_connection_count"]) < 1:
                raise ValueError
        except ValueError:
            errors.append(f"{number}행 expected_connection_count 오류")
        if row["action"] == "CREATE_AND_MAP":
            if not row["target_name_ko"] or not row["source_reference"]:
                errors.append(f"{number}행 신규 canonical 필수값 누락")
            definition = (row["target_name_ko"], row["target_name_en"])
            previous = create_definitions.setdefault(row["target_ingredient_code"], definition)
            if previous != definition:
                errors.append(f"{number}행 신규 canonical 이름 정의 충돌")
        elif row["action"] != "MAP_EXISTING":
            errors.append(f"{number}행 지원하지 않는 action")
    if errors:
        preview = "\n".join(errors[:20])
        suffix = f"\n외 {len(errors) - 20}건" if len(errors) > 20 else ""
        raise ValueError(f"생성 CSV 검증 실패:\n{preview}{suffix}")


def generate_mapping_csv(
    *,
    pending_path: Path,
    suggestions_path: Path,
    output_path: Path,
    ingredients_path: Path | None = None,
    excluded_count: int = 20,
    report_path: Path | None = None,
) -> tuple[GenerationSummary, list[ExcludedRow]]:
    pending_rows = read_csv(pending_path)
    suggestions = _load_suggestions(suggestions_path)
    pending_names = _load_pending_names(ingredients_path)
    display_names = _select_display_names(pending_rows, pending_names)

    pending_keys = [
        (row.get("pending_code", "").strip(), row.get("normalized_source_name", ""))
        for row in pending_rows
    ]
    duplicate_keys = {key for key, count in Counter(pending_keys).items() if count > 1}
    if duplicate_keys:
        raise ValueError(f"운영 export에 중복 식별자가 있습니다: {sorted(duplicate_keys)[:5]!r}")
    missing = set(pending_keys) - set(suggestions)
    extra = set(suggestions) - set(pending_keys)
    if missing or extra:
        raise ValueError(
            "운영 export와 추천 스냅샷 식별자가 일치하지 않습니다: "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    if excluded_count < 0 or excluded_count > len(pending_rows):
        raise ValueError("excluded_count는 0 이상 입력 행 수 이하여야 합니다.")

    prepared: list[tuple[dict[str, str], dict[str, str], int, str]] = []
    for row in pending_rows:
        pending_code = row.get("pending_code", "").strip()
        normalized = row.get("normalized_source_name", "")
        suggestion = suggestions[(pending_code, normalized)]
        target_code = suggestion.get("target_ingredient_code", "").strip()
        candidate_type = suggestion.get("candidate_type", "").strip()
        cleaned_name = display_names.get(pending_code, "")
        risk_score, risk_reason = _row_risk(row, cleaned_name, candidate_type)
        output = {field: row.get(field, "") for field in OUTPUT_FIELDS}
        output["pending_code"] = pending_code

        if target_code:
            output.update(
                action="MAP_EXISTING",
                target_ingredient_code=target_code,
                target_name_ko="",
                target_name_en="",
                decision_reason="운영 DB canonical 정확 일치 추천",
                source_reference=SOURCE_REFERENCE,
            )
        else:
            output.update(
                action="CREATE_AND_MAP",
                target_ingredient_code=_new_target_code(pending_code),
                target_name_ko=cleaned_name,
                target_name_en=cleaned_name if _looks_latin(cleaned_name) else "",
                decision_reason="미판정 원문을 신규 canonical 성분으로 생성 후 연결",
                source_reference=GENERATED_SOURCE_REFERENCE,
            )
        prepared.append((row, output, risk_score, risk_reason))

    excluded_keys = {
        (source.get("pending_code", "").strip(), source.get("normalized_source_name", ""))
        for source, _, _, _ in sorted(
            prepared,
            key=lambda item: (
                -item[2],
                item[0].get("pending_code", ""),
                item[0].get("normalized_source_name", ""),
            ),
        )[:excluded_count]
    }
    output_rows: list[dict[str, str]] = []
    excluded: list[ExcludedRow] = []
    for source, output, risk_score, risk_reason in prepared:
        key = (source.get("pending_code", "").strip(), source.get("normalized_source_name", ""))
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

    _validate_output_rows(output_rows, len(pending_rows) - excluded_count)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    summary = GenerationSummary(
        input_rows=len(pending_rows),
        output_rows=len(output_rows),
        mapped_existing=sum(row["action"] == "MAP_EXISTING" for row in output_rows),
        created_canonical=sum(row["action"] == "CREATE_AND_MAP" for row in output_rows),
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
    parser = argparse.ArgumentParser(description="운영 DB 미판정 성분용 관리자 일괄 매핑 CSV 생성")
    parser.add_argument("--pending-csv", type=Path, required=True)
    parser.add_argument("--suggestions-csv", type=Path, required=True)
    parser.add_argument("--ingredients-csv", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--excluded-count", type=int, default=20)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    summary, excluded = generate_mapping_csv(
        pending_path=args.pending_csv,
        suggestions_path=args.suggestions_csv,
        ingredients_path=args.ingredients_csv,
        output_path=args.output,
        excluded_count=args.excluded_count,
        report_path=args.report,
    )
    print(json.dumps({"summary": asdict(summary), "excluded": [asdict(row) for row in excluded]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
