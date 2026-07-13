#!/usr/bin/env python3
"""Build review-only role and effect-watchlist proposals for canonical ingredients.

CosIng functions are screening signals only. They never create runtime scores or
scientific evidence, and every new pair remains candidate_unverified.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping


COSING_APP_CONFIG_URL = (
    "https://ec.europa.eu/growth/tools-databases/cosing/assets/env-json-config.json"
)
COSING_PUBLIC_URL = (
    "https://single-market-economy.ec.europa.eu/sectors/cosmetics/"
    "cosmetic-ingredient-database_en"
)

EFFECT_NAMES = {
    "effect_brightening": "미백·톤",
    "effect_moisture_barrier": "보습·장벽",
    "effect_acne_sebum": "여드름·피지",
    "effect_wrinkle": "주름·탄력",
    "effect_calming": "진정",
    "effect_exfoliation": "각질",
}

# These are discovery signals, not score rules. Broad terms such as
# SKIN CONDITIONING and ANTIOXIDANT are intentionally excluded.
HIGH_EFFECT_FUNCTIONS = {
    "effect_brightening": {"BLEACHING"},
    "effect_moisture_barrier": {
        "HUMECTANT",
        "MOISTURISING",
        "SKIN CONDITIONING - HUMECTANT",
    },
    "effect_acne_sebum": {"ANTI-SEBORRHEIC"},
    "effect_calming": {"SOOTHING"},
    "effect_exfoliation": {"KERATOLYTIC"},
}
MEDIUM_EFFECT_FUNCTIONS = {
    "effect_moisture_barrier": {
        "SKIN CONDITIONING - EMOLLIENT",
        "SKIN CONDITIONING - OCCLUSIVE",
        "SKIN PROTECTING",
    },
}

FORMULATION_FUNCTIONS = {
    "ABRASIVE",
    "ABSORBENT",
    "ANTICAKING",
    "ANTICORROSIVE",
    "ANTIFOAMING",
    "ANTISTATIC",
    "BINDING",
    "BUFFERING",
    "BULKING",
    "CHELATING",
    "CLEANSING",
    "COLORANT",
    "DENATURANT",
    "DISPERSING NON-SURFACTANT",
    "EMULSION STABILISING",
    "FILM FORMING",
    "FLAVOURING",
    "FOAMING",
    "FRAGRANCE",
    "GEL FORMING",
    "HAIR CONDITIONING",
    "HAIR FIXING",
    "HAIR WAVING OR STRAIGHTENING",
    "LIGHT STABILIZER",
    "OPACIFYING",
    "ORAL CARE",
    "PERFUMING",
    "PLASTICISER",
    "PRESERVATIVE",
    "REDUCING",
    "REFATTING",
    "SLIP MODIFIER",
    "SOLVENT",
    "SURFACTANT - CLEANSING",
    "SURFACTANT - EMULSIFYING",
    "SURFACTANT - FOAM BOOSTING",
    "UV ABSORBER",
    "UV FILTER",
    "VISCOSITY CONTROLLING",
    "pH ADJUSTERS",
}

ROLE_FIELDS = [
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_row_count",
    "product_count",
    "current_effect_ids",
    "current_risk_types",
    "cosing_match_status",
    "cosing_inci_name",
    "cosing_functions",
    "cosing_restrictions",
    "cosing_sccs_opinion_count",
    "effect_signal_ids",
    "effect_signal_basis",
    "role_effect_candidate",
    "role_formulation",
    "role_risk_review",
    "role_general_other",
    "role_unresolved",
    "research_priority",
    "classification_status",
    "classification_note",
    "source_url",
    "source_fetched_on",
]

WATCHLIST_FIELDS = [
    "priority_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "product_count",
    "pair_status",
    "signal_strength",
    "signal_functions",
    "current_effect_score",
    "search_action",
    "review_status",
    "score_change",
    "rationale",
]

COSING_CACHE_FIELDS = [
    "fetched_on",
    "source_url",
    "inci_name",
    "functions_json",
    "restrictions_json",
    "sccs_opinions_json",
    "substance_ids_json",
]


@dataclass(frozen=True)
class CosingRecord:
    inci_name: str
    functions: tuple[str, ...]
    restrictions: tuple[str, ...]
    sccs_opinions: tuple[str, ...]
    substance_ids: tuple[str, ...]


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(normalized.split())


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def clean_cosing_values(values: Iterable[object]) -> tuple[str, ...]:
    cleaned = {clean(str(value)) for value in values}
    return tuple(sorted(value for value in cleaned if value))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def candidate_query_names(name_en: str) -> tuple[str, ...]:
    original = clean(name_en).upper()
    candidates = [original]
    simplified = clean(re.sub(r"\s*\([^)]*\)", "", name_en)).upper()
    if simplified and simplified not in candidates:
        candidates.append(simplified)
    if "|" in original:
        for part in reversed(original.split("|")):
            part = clean(part)
            if part and part not in candidates:
                candidates.append(part)
    return tuple(candidates)


def effect_signals(functions: Iterable[str]) -> dict[str, tuple[str, tuple[str, ...]]]:
    function_set = set(functions)
    signals: dict[str, tuple[str, tuple[str, ...]]] = {}
    for effect_id, rules in HIGH_EFFECT_FUNCTIONS.items():
        matched = tuple(sorted(function_set & rules))
        if matched:
            signals[effect_id] = ("high", matched)
    for effect_id, rules in MEDIUM_EFFECT_FUNCTIONS.items():
        if effect_id in signals:
            continue
        matched = tuple(sorted(function_set & rules))
        if matched:
            signals[effect_id] = ("medium", matched)
    return signals


def apply_mapping(
    ingredient_id: str,
    ingredient_name: str,
    exact_mapping: dict[tuple[str, str], str],
    wildcard_mapping: dict[str, str],
) -> str:
    exact = exact_mapping.get((ingredient_id, normalize(ingredient_name)))
    if exact:
        return exact
    return wildcard_mapping.get(ingredient_id, ingredient_id)


def load_mappings(path: Path) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    exact: dict[tuple[str, str], str] = {}
    wildcard: dict[str, str] = {}
    for row in read_csv(path):
        source_id = row["source_ingredient_id"].strip()
        source_name = row["source_ingredient_name"].strip()
        canonical_id = row["canonical_id"].strip()
        if source_name:
            exact[(source_id, normalize(source_name))] = canonical_id
        else:
            wildcard[source_id] = canonical_id
    return exact, wildcard


def count_product_usage(
    product_paths: Iterable[Path],
    canonical_ids: set[str],
    exact_mapping: dict[tuple[str, str], str],
    wildcard_mapping: dict[str, str],
) -> tuple[Counter[str], dict[str, int]]:
    row_counts: Counter[str] = Counter()
    products_by_ingredient: dict[str, set[str]] = defaultdict(set)
    for path in product_paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                canonical_id = apply_mapping(
                    row["ingredient_id"],
                    row.get("ingredient_name", ""),
                    exact_mapping,
                    wildcard_mapping,
                )
                if canonical_id not in canonical_ids:
                    continue
                row_counts[canonical_id] += 1
                products_by_ingredient[canonical_id].add(row["product_id"])
    product_counts = {
        ingredient_id: len(product_ids)
        for ingredient_id, product_ids in products_by_ingredient.items()
    }
    return row_counts, product_counts


def _post_multipart_json(url: str, payload: dict[str, object], timeout: int = 60) -> dict:
    boundary = f"----codex-{uuid.uuid4().hex}"
    query_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="query"; filename="query.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode("utf-8") + query_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _merge_cosing_metadata(
    metadata_by_name: dict[str, list[dict]],
    response: dict,
) -> None:
    for result in response.get("results", []):
        metadata = result.get("metadata", {})
        inci_name = clean((metadata.get("inciName") or [""])[0]).upper()
        if inci_name:
            metadata_by_name[inci_name].append(metadata)


def _fetch_cosing_names(
    api_url: str,
    api_key: str,
    query_names: Iterable[str],
    metadata_by_name: dict[str, list[dict]],
    *,
    batch_size: int,
) -> None:
    names_to_fetch = sorted(set(query_names))
    for start in range(0, len(names_to_fetch), batch_size):
        names = names_to_fetch[start : start + batch_size]
        if not names:
            continue
        query = {
            "bool": {
                "must": [
                    {"terms": {"inciName": names}},
                    {"term": {"itemType": "ingredient"}},
                    {"term": {"status": "Active"}},
                ]
            }
        }
        params = urllib.parse.urlencode(
            {
                "apiKey": api_key,
                "text": "*",
                "pageSize": 500,
                "pageNumber": 1,
            }
        )
        response = _post_multipart_json(f"{api_url}?{params}", query)
        _merge_cosing_metadata(metadata_by_name, response)


def fetch_cosing_records(ingredient_rows: list[dict[str, str]]) -> dict[str, CosingRecord]:
    with urllib.request.urlopen(COSING_APP_CONFIG_URL, timeout=30) as response:
        config = json.load(response)
    api_url = config["euSearchApiUrl"]
    api_key = config["euSearchApiKey"]
    metadata_by_name: dict[str, list[dict]] = defaultdict(list)
    primary_names = {
        candidate_query_names(row["name_en"])[0]
        for row in ingredient_rows
        if candidate_query_names(row["name_en"])
    }
    _fetch_cosing_names(
        api_url,
        api_key,
        primary_names,
        metadata_by_name,
        batch_size=80,
    )

    # The EU search endpoint can occasionally return a partial large-batch result.
    # Retry missing exact names in smaller batches before attempting name variants.
    missing_primary = primary_names - set(metadata_by_name)
    _fetch_cosing_names(
        api_url,
        api_key,
        missing_primary,
        metadata_by_name,
        batch_size=20,
    )

    unmatched_rows = [
        row
        for row in ingredient_rows
        if not any(name in metadata_by_name for name in candidate_query_names(row["name_en"]))
    ]
    variant_names = {
        name
        for row in unmatched_rows
        for name in candidate_query_names(row["name_en"])[1:]
    }
    _fetch_cosing_names(
        api_url,
        api_key,
        variant_names,
        metadata_by_name,
        batch_size=20,
    )

    records: dict[str, CosingRecord] = {}
    for inci_name, entries in metadata_by_name.items():
        records[inci_name] = CosingRecord(
            inci_name=inci_name,
            functions=clean_cosing_values(
                value for entry in entries for value in entry.get("functionName", [])
            ),
            restrictions=clean_cosing_values(
                value
                for entry in entries
                for value in entry.get("cosmeticRestriction", [])
            ),
            sccs_opinions=clean_cosing_values(
                value for entry in entries for value in entry.get("sccsOpinion", [])
            ),
            substance_ids=clean_cosing_values(
                value for entry in entries for value in entry.get("substanceId", [])
            ),
        )
    return records


def write_cosing_cache(path: Path, records: dict[str, CosingRecord], fetched_on: str) -> None:
    rows = [
        {
            "fetched_on": fetched_on,
            "source_url": COSING_PUBLIC_URL,
            "inci_name": record.inci_name,
            "functions_json": json.dumps(record.functions, ensure_ascii=False),
            "restrictions_json": json.dumps(record.restrictions, ensure_ascii=False),
            "sccs_opinions_json": json.dumps(record.sccs_opinions, ensure_ascii=False),
            "substance_ids_json": json.dumps(record.substance_ids, ensure_ascii=False),
        }
        for record in sorted(records.values(), key=lambda item: item.inci_name)
    ]
    write_csv(path, COSING_CACHE_FIELDS, rows)


def load_cosing_cache(path: Path) -> tuple[dict[str, CosingRecord], str]:
    rows = read_csv(path)
    records = {
        clean(row["inci_name"]): CosingRecord(
            inci_name=clean(row["inci_name"]),
            functions=clean_cosing_values(json.loads(row["functions_json"])),
            restrictions=clean_cosing_values(json.loads(row["restrictions_json"])),
            sccs_opinions=clean_cosing_values(json.loads(row["sccs_opinions_json"])),
            substance_ids=clean_cosing_values(json.loads(row["substance_ids_json"])),
        )
        for row in rows
    }
    fetched_dates = {row["fetched_on"] for row in rows}
    if len(fetched_dates) != 1:
        raise ValueError("CosIng cache의 fetched_on 값이 하나가 아닙니다")
    return records, next(iter(fetched_dates))


def match_cosing_record(
    name_en: str,
    records: dict[str, CosingRecord],
) -> tuple[str, CosingRecord | None]:
    candidates = candidate_query_names(name_en)
    for index, candidate in enumerate(candidates):
        record = records.get(candidate)
        if record is not None:
            return ("exact_name" if index == 0 else "official_name_variant"), record
    return "not_matched", None


def load_current_effects(path: Path) -> dict[str, dict[str, str]]:
    effects: dict[str, dict[str, str]] = defaultdict(dict)
    for row in read_csv(path):
        effects[row["ingredient_id"]][row["effect_id"]] = row["effect_score"]
    return effects


def load_candidate_selections(path: Path) -> dict[tuple[str, str], str]:
    selected: dict[tuple[str, str], str] = {}
    for row in read_csv(path):
        if row.get("selected_for_paper_review") != "Y":
            continue
        key = (row["ingredient_id"], row["effect_id"])
        selected[key] = row.get("screening_status", "selected")
    return selected


def load_current_risks(
    path: Path,
    wildcard_mapping: dict[str, str] | None = None,
) -> dict[str, set[str]]:
    risks: dict[str, set[str]] = defaultdict(set)
    wildcard_mapping = wildcard_mapping or {}
    for row in read_csv(path):
        ingredient_id = wildcard_mapping.get(row["ingredient_id"], row["ingredient_id"])
        risks[ingredient_id].add(row["risk_type"])
    return risks


def validate_generated_rows(
    role_rows: list[dict[str, object]],
    watch_rows: list[dict[str, object]],
    current_pair_count: int,
) -> None:
    role_ids = [str(row["ingredient_id"]) for row in role_rows]
    if len(role_ids) != len(set(role_ids)):
        raise ValueError("역할 검수표에 ingredient_id 중복이 있습니다")

    pair_keys = [
        (str(row["ingredient_id"]), str(row["effect_id"])) for row in watch_rows
    ]
    if len(pair_keys) != len(set(pair_keys)):
        raise ValueError("watchlist에 성분×효능 중복이 있습니다")

    current_rows = [
        row for row in watch_rows if row["pair_status"] == "current_runtime_pair"
    ]
    if len(current_rows) != current_pair_count:
        raise ValueError(
            "기존 런타임 점수쌍 수가 watchlist와 다릅니다: "
            f"{current_pair_count} != {len(current_rows)}"
        )

    invalid_new = [
        row
        for row in watch_rows
        if row["pair_status"] == "new_watchlist_proposal"
        and (
            row["review_status"] != "candidate_unverified"
            or row["score_change"] != "none"
            or row["current_effect_score"]
        )
    ]
    if invalid_new:
        raise ValueError("신규 watchlist 후보에 점수 또는 승인 상태가 섞였습니다")


def build_rows(
    ingredient_rows: list[dict[str, str]],
    records: dict[str, CosingRecord],
    row_counts: Counter[str],
    product_counts: dict[str, int],
    current_effects: dict[str, dict[str, str]],
    current_risks: dict[str, set[str]],
    fetched_on: str,
    candidate_selections: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    role_rows: list[dict[str, object]] = []
    watch_rows: list[dict[str, object]] = []
    for ingredient in ingredient_rows:
        ingredient_id = ingredient["ingredient_id"]
        match_status, record = match_cosing_record(ingredient["name_en"], records)
        functions = record.functions if record else ()
        raw_signals = effect_signals(functions)
        signals = (
            raw_signals
            if candidate_selections is None
            else {
                effect_id: value
                for effect_id, value in raw_signals.items()
                if (ingredient_id, effect_id) in candidate_selections
            }
        )
        existing_effects = current_effects.get(ingredient_id, {})
        signal_ids = sorted(set(existing_effects) | set(signals))
        risk_types = current_risks.get(ingredient_id, set())
        role_effect = bool(signal_ids)
        role_formulation = bool(set(functions) & FORMULATION_FUNCTIONS)
        role_risk = bool(
            risk_types
            or (record and record.restrictions)
            or (record and record.sccs_opinions)
        )
        role_unresolved = record is None and not existing_effects and not risk_types
        role_general = not role_effect and not role_formulation and not role_risk
        direct_priority = (
            any(strength == "high" for strength, _ in signals.values())
            if candidate_selections is None
            else any(
                candidate_selections.get((ingredient_id, effect_id))
                == "direct_cosing_signal"
                for effect_id in signals
            )
        )
        if existing_effects:
            priority = "current_runtime"
        elif direct_priority:
            priority = "P1_initial_evidence"
        elif signals:
            priority = "P2_initial_evidence"
        else:
            priority = "not_selected"

        signal_basis = []
        for effect_id, (strength, matched_functions) in sorted(signals.items()):
            signal_basis.append(f"{effect_id}:{strength}:{'+'.join(matched_functions)}")
        for effect_id in sorted(existing_effects):
            signal_basis.append(f"{effect_id}:current_runtime")

        if existing_effects:
            classification_status = "existing_runtime"
            classification_note = "기존 ingredient_effect 런타임 조합"
        elif signals:
            classification_status = "candidate_unverified"
            classification_note = (
                "CosIng 직접 신호 또는 인체 국소 PubMed 사전검사 통과 후보이며 "
                "논문 근거나 점수 승인은 아님"
            )
        else:
            classification_status = "not_selected"
            classification_note = (
                "인체 국소 PubMed 사전검사 미통과"
                if raw_signals and candidate_selections is not None
                else "6축 효능 후보 신호 없음"
            )

        role_rows.append(
            {
                "ingredient_id": ingredient_id,
                "name_ko": ingredient["name_ko"],
                "name_en": ingredient["name_en"],
                "product_row_count": row_counts.get(ingredient_id, 0),
                "product_count": product_counts.get(ingredient_id, 0),
                "current_effect_ids": "|".join(sorted(existing_effects)),
                "current_risk_types": "|".join(sorted(risk_types)),
                "cosing_match_status": match_status,
                "cosing_inci_name": record.inci_name if record else "",
                "cosing_functions": "|".join(functions),
                "cosing_restrictions": "|".join(record.restrictions if record else ()),
                "cosing_sccs_opinion_count": len(record.sccs_opinions) if record else 0,
                "effect_signal_ids": "|".join(signal_ids),
                "effect_signal_basis": "|".join(signal_basis),
                "role_effect_candidate": "Y" if role_effect else "N",
                "role_formulation": "Y" if role_formulation else "N",
                "role_risk_review": "Y" if role_risk else "N",
                "role_general_other": "Y" if role_general else "N",
                "role_unresolved": "Y" if role_unresolved else "N",
                "research_priority": priority,
                "classification_status": classification_status,
                "classification_note": classification_note,
                "source_url": COSING_PUBLIC_URL if record else "",
                "source_fetched_on": fetched_on if record else "",
            }
        )

        for effect_id in signal_ids:
            if effect_id in existing_effects:
                pair_status = "current_runtime_pair"
                strength = "current"
                matched_functions: tuple[str, ...] = ()
                search_action = "keep_current_weekly_monitor"
                review_status = "existing_runtime"
                score_change = "none"
                rationale = "기존 ingredient_effect 점수쌍"
            else:
                strength, matched_functions = signals[effect_id]
                selection_status = (
                    candidate_selections.get((ingredient_id, effect_id), "")
                    if candidate_selections is not None
                    else ""
                )
                pair_status = "new_watchlist_proposal"
                search_action = "initial_evidence_search_then_watch"
                review_status = "candidate_unverified"
                score_change = "none"
                rationale = (
                    "CosIng 직접 기능 검색 후보이며 근거 승인 전 점수 사용 금지"
                    if selection_status == "direct_cosing_signal"
                    else "인체 국소 PubMed 사전검사 통과 후보이며 원문 검수 전 점수 사용 금지"
                )
            watch_rows.append(
                {
                    "priority_rank": 0,
                    "ingredient_id": ingredient_id,
                    "name_ko": ingredient["name_ko"],
                    "name_en": ingredient["name_en"],
                    "effect_id": effect_id,
                    "effect_name": EFFECT_NAMES[effect_id],
                    "product_count": product_counts.get(ingredient_id, 0),
                    "pair_status": pair_status,
                    "signal_strength": strength,
                    "signal_functions": "+".join(matched_functions),
                    "current_effect_score": existing_effects.get(effect_id, ""),
                    "search_action": search_action,
                    "review_status": review_status,
                    "score_change": score_change,
                    "rationale": rationale,
                }
            )

    role_rows.sort(key=lambda row: (-int(row["product_count"]), str(row["ingredient_id"])))
    strength_order = {"current": 0, "high": 1, "medium": 2}
    watch_rows.sort(
        key=lambda row: (
            0 if row["pair_status"] == "new_watchlist_proposal" else 1,
            strength_order[str(row["signal_strength"])],
            -int(row["product_count"]),
            str(row["ingredient_id"]),
            str(row["effect_id"]),
        )
    )
    new_rank = 0
    for row in watch_rows:
        if row["pair_status"] == "new_watchlist_proposal":
            new_rank += 1
            row["priority_rank"] = new_rank
        else:
            row["priority_rank"] = ""
    return role_rows, watch_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--roles-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_role_review.csv"),
    )
    parser.add_argument(
        "--watchlist-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_watchlist_proposal.csv"),
    )
    parser.add_argument(
        "--cosing-cache",
        type=Path,
        default=Path("data/reconciliation/ingredient_cosing_function_snapshot.csv"),
    )
    parser.add_argument(
        "--pubmed-screening",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_pubmed_screening.csv"),
    )
    parser.add_argument("--refresh-cosing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ingredient_rows = [
        row
        for row in read_csv(args.data_dir / "ingredients.csv")
        if not row["ingredient_id"].startswith("ing_pending_")
    ]
    exact_mapping, wildcard_mapping = load_mappings(
        args.data_dir / "ingredient_canonical_mappings.csv"
    )
    row_counts, product_counts = count_product_usage(
        sorted((args.data_dir / "product_ingredients").glob("product_ingredients_*.csv")),
        {row["ingredient_id"] for row in ingredient_rows},
        exact_mapping,
        wildcard_mapping,
    )
    if args.cosing_cache.exists() and not args.refresh_cosing:
        records, fetched_on = load_cosing_cache(args.cosing_cache)
    else:
        fetched_on = date.today().isoformat()
        records = fetch_cosing_records(ingredient_rows)
        write_cosing_cache(args.cosing_cache, records, fetched_on)
    current_effects = load_current_effects(args.data_dir / "ingredient_effect.csv")
    role_rows, watch_rows = build_rows(
        ingredient_rows,
        records,
        row_counts,
        product_counts,
        current_effects,
        load_current_risks(args.data_dir / "risk_flags.csv", wildcard_mapping),
        fetched_on,
        load_candidate_selections(args.pubmed_screening),
    )
    validate_generated_rows(
        role_rows,
        watch_rows,
        sum(len(effects) for effects in current_effects.values()),
    )
    write_csv(args.roles_output, ROLE_FIELDS, role_rows)
    write_csv(args.watchlist_output, WATCHLIST_FIELDS, watch_rows)

    new_watch = [row for row in watch_rows if row["pair_status"] == "new_watchlist_proposal"]
    print(f"canonical ingredients: {len(ingredient_rows)}")
    print(f"CosIng matched: {sum(row['cosing_match_status'] != 'not_matched' for row in role_rows)}")
    print(f"effect candidates: {sum(row['role_effect_candidate'] == 'Y' for row in role_rows)}")
    print(f"new watchlist pairs: {len(new_watch)}")
    print("runtime score changes: 0")


if __name__ == "__main__":
    main()
