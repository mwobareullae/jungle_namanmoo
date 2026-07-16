import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import recommendation_coarse_quality as quality
from app.services.recommendation_coarse_quality import (
    CoarseQualityCase,
    CoarseQualityCaseResult,
    evaluate_coarse_quality_cases,
    parse_coarse_quality_cases,
    render_coarse_quality_markdown,
    summarize_coarse_quality_results,
)
from app.services.scoring import ScoredProduct


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "app"
    / "cli"
    / "fixtures"
    / "recommendation_coarse_top50_quality_cases.json"
)


def test_quality_fixture_has_fixed_unique_cases() -> None:
    cases = parse_coarse_quality_cases(
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    )

    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert sum(case.weight for case in cases) == pytest.approx(1.0)
    assert all(case.query for case in cases)


def test_quality_evaluator_compares_same_candidates_and_exact_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [SimpleNamespace(db_product_id=index) for index in range(1, 4)]
    score_paths: list[str] = []
    monkeypatch.setattr(quality, "build_recommendation_intent", lambda _query: object())
    monkeypatch.setattr(
        quality,
        "generate_candidate_pool",
        lambda *_args, **_kwargs: SimpleNamespace(candidates=candidates),
    )
    monkeypatch.setattr(
        quality,
        "match_product_search_documents",
        lambda *_args, **_kwargs: [],
    )

    baseline = [_scored(1, 90.0), _scored(2, 80.0), _scored(3, 70.0)]
    coarse = [_scored(1, 90.0, rank=2), _scored(3, 70.0, rank=1)]

    def fake_score(*_args, scoring_read_path, diagnostics=None, **_kwargs):
        score_paths.append(scoring_read_path)
        if scoring_read_path == "coarse_top50_v1":
            diagnostics.update(
                {
                    "coarse_shortlist_size": 2,
                    "scoring_fallback": False,
                }
            )
            return coarse
        return baseline

    monkeypatch.setattr(quality, "score_candidates", fake_score)
    session = SimpleNamespace(rollback=lambda: None)

    results = evaluate_coarse_quality_cases(
        session,
        (CoarseQualityCase(case_id="case", query="query"),),
        candidate_pool_limit=500,
    )

    assert score_paths == ["legacy_bulk", "coarse_top50_v1"]
    assert results[0].candidate_count == 3
    assert results[0].top1_retained is True
    assert results[0].top10_recall_at_50 == pytest.approx(2 / 3)
    assert results[0].exact_value_parity is True
    assert results[0].coarse_shortlist_size == 2


def test_quality_summary_and_markdown_surface_loss_and_fallback() -> None:
    results = [
        CoarseQualityCaseResult(
            case_id="pass",
            query="query",
            weight=0.75,
            candidate_count=500,
            baseline_result_count=500,
            coarse_result_count=50,
            top1_retained=True,
            top10_recall_at_50=0.9,
            exact_value_parity=True,
            coarse_shortlist_size=50,
        ),
        CoarseQualityCaseResult(
            case_id="loss",
            query="query",
            weight=0.25,
            candidate_count=500,
            baseline_result_count=500,
            coarse_result_count=500,
            top1_retained=False,
            top10_recall_at_50=0.5,
            exact_value_parity=True,
            scoring_fallback=True,
            scoring_fallback_reason="missing",
        ),
    ]

    summary = summarize_coarse_quality_results(results)
    markdown = render_coarse_quality_markdown(results, candidate_pool_limit=500)

    assert summary["top1_retention_rate"] == pytest.approx(0.5)
    assert summary["top10_recall_at_50_mean"] == pytest.approx(0.7)
    assert summary["top10_recall_at_50_weighted"] == pytest.approx(0.8)
    assert summary["fallback_case_count"] == 1
    assert "| loss | 500 | 500 | 500 | FAIL | 50.00% | PASS | True |" in markdown


def _scored(product_id: int, score: float, *, rank: int | None = None) -> ScoredProduct:
    return ScoredProduct(
        product_id=f"product-{product_id}",
        db_product_id=product_id,
        rank=rank if rank is not None else product_id,
        total_score=score,
        reason_summary="reason",
        evidence_tags=("tag",),
        key_ingredients=("ingredient",),
        score_breakdown={"ingredient_effect_score": score / 100},
        score_evidence=(),
    )
