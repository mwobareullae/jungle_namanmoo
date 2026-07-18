"""함량 추정치 오버레이 로더 단위 테스트."""
import csv
from decimal import Decimal
from pathlib import Path

from app.services.concentration_estimates import load_concentration_estimates


_HEADER = [
    "product_id", "ingredient_id", "ingredient_name", "display_order",
    "concentration_type", "value_min", "value_max", "unit",
    "confidence", "visibility", "basis", "source",
]


def _write(data_dir: Path, rows: list[dict]) -> None:
    out = data_dir / "reconciliation" / "concentration_coverage_estimates.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _HEADER})


def _row(**kw):
    base = dict(product_id="p1", ingredient_id="i1", ingredient_name="나이아신아마이드",
               display_order="1", unit="%", confidence="medium")
    base.update(kw)
    return base


def test_midpoint_and_bounds(tmp_path):
    _write(tmp_path, [
        _row(concentration_type="range", value_min="2", value_max="5"),           # 중앙값 3.5
        _row(ingredient_name="B", concentration_type="legal_upper_bound", value_max="1"),  # 상한 1
        _row(ingredient_name="C", concentration_type="lower_bound", value_min="0.5"),      # 하한 0.5
    ])
    m = load_concentration_estimates(tmp_path)
    assert m[("p1", 1, "나이아신아마이드")].value == Decimal("3.5")
    assert m[("p1", 1, "B")].value == Decimal("1")
    assert m[("p1", 1, "C")].value == Decimal("0.5")


def test_excludes_noisy_strategies(tmp_path):
    """prior_estimate·marker_upper_bound은 기본 제외(노이즈)."""
    _write(tmp_path, [
        _row(ingredient_name="water", concentration_type="prior_estimate", value_min="60", value_max="90"),
        _row(ingredient_name="edta", concentration_type="marker_upper_bound", value_max="1"),
    ])
    m = load_concentration_estimates(tmp_path)
    assert m == {}


def test_skips_non_percent_and_bad_values(tmp_path):
    _write(tmp_path, [
        _row(ingredient_name="x", concentration_type="exact", value_min="", value_max="", unit="%"),  # 값 없음
        _row(ingredient_name="y", concentration_type="exact", value_max="5", unit="ppm"),             # % 아님
        _row(ingredient_name="z", concentration_type="exact", value_max="0", unit="%"),               # 0 이하
    ])
    assert load_concentration_estimates(tmp_path) == {}


def test_missing_file_returns_empty(tmp_path):
    assert load_concentration_estimates(tmp_path) == {}


def test_priority_midpoint_over_bound(tmp_path):
    """같은 키에 여러 전략이 오면 중앙값(우선순위 높음)이 이긴다."""
    _write(tmp_path, [
        _row(concentration_type="lower_bound", value_min="0.5"),
        _row(concentration_type="exact", value_min="4", value_max="4"),
    ])
    m = load_concentration_estimates(tmp_path)
    assert m[("p1", 1, "나이아신아마이드")].value == Decimal("4")
