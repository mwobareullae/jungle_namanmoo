from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.recommendation import RecommendationResult, RecommendationScoreEvidence
from app.services.scoring import ScoredProduct


TOTAL_SCORE_QUANTIZE = Decimal("0.01")
CONTRIBUTION_SCORE_QUANTIZE = Decimal("0.0001")
DEFAULT_RESULT_LIMIT = 50
DEFAULT_EVIDENCE_LIMIT_PER_RESULT = 3


@dataclass(frozen=True)
class SavedRecommendationResults:
    results: tuple[RecommendationResult, ...]
    evidence: tuple[RecommendationScoreEvidence, ...]


def save_recommendation_results(
    session: Session,
    recommendation_run_id: int,
    scored_products: list[ScoredProduct],
    *,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    evidence_limit_per_result: int = DEFAULT_EVIDENCE_LIMIT_PER_RESULT,
) -> SavedRecommendationResults:
    _delete_existing_results(session, recommendation_run_id)

    ranked_products = _ranked_products(scored_products, result_limit)
    result_rows = [
        RecommendationResult(
            recommendation_run_id=recommendation_run_id,
            product_id=scored_product.db_product_id,
            rank_order=rank_order,
            total_score=_to_decimal(scored_product.total_score, TOTAL_SCORE_QUANTIZE),
            reason_summary=scored_product.reason_summary,
            score_breakdown=scored_product.score_breakdown,
        )
        for rank_order, scored_product in enumerate(ranked_products, start=1)
    ]
    session.add_all(result_rows)
    session.flush()

    evidence_rows = [
        RecommendationScoreEvidence(
            recommendation_result_id=result.id,
            ingredient_id=evidence.ingredient_id,
            effect_id=evidence.effect_id,
            evidence_id=evidence.evidence_id,
            contribution_score=_to_decimal(
                evidence.contribution_score,
                CONTRIBUTION_SCORE_QUANTIZE,
            ),
            reason=evidence.reason,
        )
        for result, scored_product in zip(result_rows, ranked_products, strict=False)
        for evidence in scored_product.score_evidence[:evidence_limit_per_result]
    ]
    session.add_all(evidence_rows)
    session.flush()

    return SavedRecommendationResults(
        results=tuple(result_rows),
        evidence=tuple(evidence_rows),
    )


def _delete_existing_results(session: Session, recommendation_run_id: int) -> None:
    result_ids = session.execute(
        select(RecommendationResult.id).where(
            RecommendationResult.recommendation_run_id == recommendation_run_id,
        )
    ).scalars().all()

    if not result_ids:
        return

    session.execute(
        delete(RecommendationScoreEvidence).where(
            RecommendationScoreEvidence.recommendation_result_id.in_(result_ids),
        )
    )
    session.execute(
        delete(RecommendationResult).where(
            RecommendationResult.recommendation_run_id == recommendation_run_id,
        )
    )
    session.flush()


def _ranked_products(
    scored_products: list[ScoredProduct],
    result_limit: int,
) -> tuple[ScoredProduct, ...]:
    if result_limit <= 0:
        return ()

    return tuple(
        product
        for _, product in sorted(
            enumerate(scored_products),
            key=lambda item: (
                item[1].rank if item[1].rank > 0 else item[0] + 1,
                item[0],
            ),
        )[:result_limit]
    )


def _to_decimal(score: float, quantize: Decimal) -> Decimal:
    return Decimal(str(score)).quantize(quantize)
