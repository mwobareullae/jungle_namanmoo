from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product
from app.db.models.recommendation import HomeSectionSnapshot
from app.services import home_sections
from app.services.home_section_snapshot_service import (
    HOME_EVIDENCE_SNAPSHOT_CONTEXT,
    HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
    HOME_EVIDENCE_SNAPSHOT_SIZE,
    HOME_FOR_YOU_SNAPSHOT_SECTION_ID,
    HOME_FOR_YOU_SNAPSHOT_SIZE,
    HOME_GUEST_SKIN_TYPES,
    HOME_SNAPSHOT_ALGORITHM_VERSION,
    guest_skin_snapshot_context,
)


@dataclass(frozen=True)
class HomeSectionSnapshotRollupResult:
    algorithm_version: str
    computed_at: datetime
    counts_by_context: dict[str, int]


def rollup_home_section_snapshots(session: Session) -> HomeSectionSnapshotRollupResult:
    """Materialize stable home rankings after product/coarse feature rollups finish."""
    computed_at = datetime.now(UTC)
    counts_by_context: dict[str, int] = {}

    evidence = home_sections.get_evidence_picks_response(
        session,
        limit=HOME_EVIDENCE_SNAPSHOT_SIZE,
        _skip_snapshot=True,
        _internal_limit=HOME_EVIDENCE_SNAPSHOT_SIZE,
    )
    counts_by_context[
        _snapshot_key(
            HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
            HOME_EVIDENCE_SNAPSHOT_CONTEXT,
        )
    ] = _replace_snapshot_rows(
        session,
        section_id=HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
        context_key=HOME_EVIDENCE_SNAPSHOT_CONTEXT,
        products=evidence.products,
        computed_at=computed_at,
    )

    for skin_type in HOME_GUEST_SKIN_TYPES:
        section = home_sections.get_for_you_response(
            session,
            skin_type=skin_type,
            limit=HOME_FOR_YOU_SNAPSHOT_SIZE,
            _skip_snapshot=True,
            _internal_limit=HOME_FOR_YOU_SNAPSHOT_SIZE,
        )
        context_key = guest_skin_snapshot_context(skin_type)
        counts_by_context[
            _snapshot_key(HOME_FOR_YOU_SNAPSHOT_SECTION_ID, context_key)
        ] = _replace_snapshot_rows(
            session,
            section_id=HOME_FOR_YOU_SNAPSHOT_SECTION_ID,
            context_key=context_key,
            products=section.products,
            computed_at=computed_at,
        )

    return HomeSectionSnapshotRollupResult(
        algorithm_version=HOME_SNAPSHOT_ALGORITHM_VERSION,
        computed_at=computed_at,
        counts_by_context=counts_by_context,
    )


def _replace_snapshot_rows(
    session: Session,
    *,
    section_id: str,
    context_key: str,
    products,
    computed_at: datetime,
) -> int:
    product_codes = [product.product_id for product in products]
    product_ids_by_code = {
        product_code: int(product_id)
        for product_id, product_code in session.execute(
            select(Product.id, Product.product_code).where(Product.product_code.in_(product_codes))
        ).all()
    }
    session.execute(
        delete(HomeSectionSnapshot).where(
            HomeSectionSnapshot.section_id == section_id,
            HomeSectionSnapshot.context_key == context_key,
        )
    )
    rows = [
        HomeSectionSnapshot(
            section_id=section_id,
            context_key=context_key,
            rank_order=rank_order,
            product_id=product_ids_by_code[product.product_id],
            display_score=product.display_score,
            reason_summary=product.reason_summary,
            badges=list(product.badges),
            tags=list(product.tags),
            algorithm_version=HOME_SNAPSHOT_ALGORITHM_VERSION,
            computed_at=computed_at,
        )
        for rank_order, product in enumerate(products, start=1)
        if product.product_id in product_ids_by_code
    ]
    session.add_all(rows)
    session.flush()
    return len(rows)


def _snapshot_key(section_id: str, context_key: str) -> str:
    return f"{section_id}:{context_key}"
