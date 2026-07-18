"""함량(농도) 추정치 오버레이.

data/reconciliation/concentration_coverage_estimates.csv 는 KCIA 고시·법정 사용한도·
1% 마커 규칙 등 전략으로 만든 성분 함량 추정치다. 씨드 시점에 product_ingredients의
정규화 함량이 비어(NULL) 있는 행에만 이 추정치를 채워 넣어, 함량 축이 실제 신호를
갖게 한다. 실측값은 절대 덮어쓰지 않는다.

주의: 이것은 추천 지표를 올리기 위한 것이 아니라(리뷰파생 정답셋은 성분과학 축을
구조적으로 벌준다 — RESULT_vocab_isolation 참고), 함량 축을 '사실상 상수'에서
'근거 기반 신호'로 만들어 과다-주의 경고·투명성·콜드스타트 판단을 가능케 하기 위함이다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

# 대표값 산출을 허용하는 전략과 규칙.
# prior_estimate(정제수 60~90% 순수 휴리스틱)와 marker_upper_bound(≤1% 상한 휴리스틱을
# 점값으로 쓰면 버킷 오분류 위험)는 기본 제외 — 근거가 약해 노이즈가 된다.
# 나머지는 min/max 중앙값(범위) 또는 상·하한을 대표값으로 쓴다.
_MIDPOINT_STRATEGIES = {"exact", "range", "regulatory_anchor"}
_UPPER_STRATEGIES = {"legal_upper_bound"}
_LOWER_STRATEGIES = {"lower_bound"}
_ALLOWED_STRATEGIES = _MIDPOINT_STRATEGIES | _UPPER_STRATEGIES | _LOWER_STRATEGIES

_ESTIMATES_RELPATH = Path("reconciliation") / "concentration_coverage_estimates.csv"


@dataclass(frozen=True)
class ConcentrationEstimate:
    value: Decimal
    unit: str
    confidence: str
    strategy: str


def _to_decimal(raw: str) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _representative_value(strategy: str, value_min: str, value_max: str) -> Decimal | None:
    lo = _to_decimal(value_min)
    hi = _to_decimal(value_max)
    if strategy in _MIDPOINT_STRATEGIES:
        if lo is not None and hi is not None:
            return (lo + hi) / 2
        return hi if hi is not None else lo
    if strategy in _UPPER_STRATEGIES:
        return hi
    if strategy in _LOWER_STRATEGIES:
        return lo
    return None


def load_concentration_estimates(
    data_dir: str | Path,
    *,
    allowed_strategies: set[str] | None = None,
) -> dict[tuple[str, int, str], ConcentrationEstimate]:
    """(product_code, display_order, ingredient_name) → 추정치 맵.

    파일이 없으면 빈 맵(오버레이 무동작). 대표값 산출 불가·단위 '%' 아님·전략 미허용은
    건너뛴다. 한 키에 여러 후보가 오면 전략 우선순위(중앙값>상한>하한)로 결정한다.
    """
    base = Path(data_dir) / _ESTIMATES_RELPATH
    if not base.exists():
        return {}
    allowed = allowed_strategies or _ALLOWED_STRATEGIES

    priority = {s: 3 for s in _MIDPOINT_STRATEGIES}
    priority.update({s: 2 for s in _UPPER_STRATEGIES})
    priority.update({s: 1 for s in _LOWER_STRATEGIES})

    out: dict[tuple[str, int, str], ConcentrationEstimate] = {}
    best_priority: dict[tuple[str, int, str], int] = {}
    with base.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            strategy = (row.get("concentration_type") or "").strip()
            if strategy not in allowed:
                continue
            if (row.get("unit") or "").strip() != "%":
                continue
            try:
                display_order = int(row["display_order"])
            except (KeyError, ValueError, TypeError):
                continue
            value = _representative_value(strategy, row.get("value_min", ""), row.get("value_max", ""))
            if value is None or value <= 0:
                continue
            key = (
                (row.get("product_id") or "").strip(),
                display_order,
                (row.get("ingredient_name") or "").strip(),
            )
            if not key[0] or not key[2]:
                continue
            pr = priority.get(strategy, 0)
            if key in best_priority and best_priority[key] >= pr:
                continue
            best_priority[key] = pr
            out[key] = ConcentrationEstimate(
                value=value,
                unit="%",
                confidence=(row.get("confidence") or "low").strip() or "low",
                strategy=strategy,
            )
    return out
