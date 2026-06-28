from app.cli.recommendation_quality_report import (
    QualityCase,
    QualityCaseResult,
    format_json_report,
    format_markdown_report,
)
from app.schemas.recommendation import (
    PurchaseConstraints,
    RecommendedProduct,
    RecommendationResponse,
    RecommendationSummary,
    ScoreBreakdown,
)


def test_format_markdown_report_limits_products_to_top_n() -> None:
    result = QualityCaseResult(
        case=QualityCase(label="dry cream", concern_text="dry cream", skin_type="dry"),
        elapsed_ms=12.34,
        response=_response_with_products(),
    )

    report = format_markdown_report([result], top_n=1, result_limit=50)

    assert "# 추천 품질 리포트" in report
    assert "rec_test" in report
    assert "Product 1" in report
    assert "Product 2" not in report
    assert "eff 90 / ev 80 / skin 70 / price 60 / search 50 / risk 0" in report


def test_format_markdown_report_includes_case_errors() -> None:
    result = QualityCaseResult(
        case=QualityCase(label="bad case", concern_text=""),
        elapsed_ms=1.23,
        error="invalid input",
    )

    report = format_markdown_report([result], top_n=10)

    assert "## bad case" in report
    assert "- error: invalid input" in report


def test_format_json_report_returns_parseable_payload() -> None:
    result = QualityCaseResult(
        case=QualityCase(label="dry cream", concern_text="dry cream"),
        elapsed_ms=12.34,
        response=_response_with_products(),
    )

    report = format_json_report([result], top_n=1)

    assert '"label": "dry cream"' in report
    assert '"product_id": "prod_1"' in report
    assert '"product_id": "prod_2"' not in report


def _response_with_products() -> RecommendationResponse:
    return RecommendationResponse(
        recommendation_id="rec_test",
        summary=RecommendationSummary(
            concern_text="dry cream",
            skin_type="dry",
            sensitivity="normal",
            avoid_ingredients=[],
            matched_concerns=["dryness"],
            expected_effects=["moisturizing"],
            purchase_constraints=PurchaseConstraints(
                categories=[],
                brands=[],
            ),
        ),
        unmatched_terms=[],
        products=[
            _product("prod_1", 1, "Product 1"),
            _product("prod_2", 2, "Product 2"),
        ],
    )


def _product(product_id: str, rank: int, name: str) -> RecommendedProduct:
    return RecommendedProduct(
        product_id=product_id,
        rank=rank,
        total_score=90 - rank,
        reason_summary="good reason",
        brand="Brand",
        name=name,
        thumbnail_url="",
        lowest_price=10000,
        evidence_tags=["moisturizing:high"],
        key_ingredients=["ingredient"],
        score_breakdown=ScoreBreakdown(
            ingredient_effect_score=90,
            ingredient_evidence_score=80,
            skin_type_score=70,
            price_score=60,
            search_match_score=50,
            risk_penalty=0,
        ),
    )
