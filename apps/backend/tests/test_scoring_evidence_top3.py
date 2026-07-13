import pytest

from app.services.scoring import (
    _ConcentrationInfo,
    _DesiredEffect,
    _EvidenceInfo,
    _IngredientEffectInfo,
    _build_contributions_by_effect,
    _build_evidence_contributions_by_effect,
    _score_ingredient_evidence,
)


EFFECT_CODE = "effect_wrinkle"


def _ingredient(
    ingredient_id: int,
    *,
    effect_score: float,
    evidence_score: float | None,
    display_order: int,
    source_authority_score: float = 1.0,
) -> _IngredientEffectInfo:
    evidence = None
    if evidence_score is not None:
        evidence = _EvidenceInfo(
            evidence_id=ingredient_id,
            evidence_score=evidence_score,
            evidence_level="medium",
            summary=None,
            source_type="test",
            pmid=None,
            doi=None,
            source_authority_score=source_authority_score,
        )
    return _IngredientEffectInfo(
        product_db_id=1,
        ingredient_id=ingredient_id,
        ingredient_code=f"ing_{ingredient_id}",
        ingredient_name=f"성분 {ingredient_id}",
        effect_id=1,
        effect_code=EFFECT_CODE,
        effect_name="주름·탄력",
        effect_score=effect_score,
        display_order=display_order,
        evidence=evidence,
        concentration=_ConcentrationInfo(
            value=None,
            unit=None,
            text=None,
            confidence=None,
            range=None,
        ),
    )


def test_evidence_top3_is_selected_independently_from_effect_top3() -> None:
    evidence_ingredients = (
        _ingredient(1, effect_score=90, evidence_score=60, display_order=1),
        _ingredient(2, effect_score=80, evidence_score=50, display_order=2),
        _ingredient(3, effect_score=70, evidence_score=40, display_order=3),
    )
    effect_only_ingredient = _ingredient(
        4,
        effect_score=100,
        evidence_score=None,
        display_order=4,
    )
    ingredients = evidence_ingredients + (effect_only_ingredient,)

    effect_contributions = _build_contributions_by_effect(ingredients)[EFFECT_CODE]
    evidence_contributions = _build_evidence_contributions_by_effect(ingredients)[
        EFFECT_CODE
    ]

    assert [item.ingredient.ingredient_id for item in effect_contributions] == [4, 1, 2]
    assert [item.ingredient.ingredient_id for item in evidence_contributions] == [1, 2, 3]

    desired_effects = (_DesiredEffect(EFFECT_CODE, "주름·탄력", 1.0),)
    baseline_score = _score_ingredient_evidence(
        desired_effects,
        _build_evidence_contributions_by_effect(evidence_ingredients),
    )
    expanded_score = _score_ingredient_evidence(
        desired_effects,
        _build_evidence_contributions_by_effect(ingredients),
    )

    assert baseline_score == pytest.approx(0.95)
    assert expanded_score == baseline_score


def test_evidence_top3_ranks_by_authority_adjusted_score() -> None:
    ingredients = (
        _ingredient(
            1,
            effect_score=90,
            evidence_score=80,
            display_order=1,
            source_authority_score=0.5,
        ),
        _ingredient(2, effect_score=30, evidence_score=50, display_order=2),
    )

    contributions = _build_evidence_contributions_by_effect(ingredients)[EFFECT_CODE]

    assert [item.ingredient.ingredient_id for item in contributions] == [2, 1]
    assert [item.evidence_component for item in contributions] == pytest.approx([0.5, 0.2])
