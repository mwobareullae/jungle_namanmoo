"""KCIA 근거가 확인된 별칭 정확 일치 후보의 원자적 일괄 승인 서비스.

기존 상품 성분 연결은 변경하지 않는다. 이 서비스는 관리자 판정과 append-only
결정 이력만 저장하며, 실제 기존 연결 반영(M2-B)은 별도 범위다.
"""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.admin.ingredient_mapping import (
    IngredientMappingActionResponse,
    IngredientMappingBulkApprovalItem,
    IngredientMappingBulkApprovalPreviewItem,
    IngredientMappingBulkApprovalPreviewResponse,
    IngredientMappingBulkApprovalResponse,
)
from app.schemas.common import ApiError
from app.services.admin.ingredient_mapping_mutation_service import approve_ingredient_mapping


KCIA_ALIAS_SOURCE = "KCIA 표준화명칭목록 2026-06-30"
MAX_BULK_APPROVAL_COUNT = 100
BULK_REFERENCE_PREFIX = "BULK_KCIA_ALIAS_EXACT"


_ELIGIBLE_FROM_SQL = """
    from ingredient_mapping_pending_groups g
    join ingredient_aliases a
      on a.normalized_alias = g.normalized_source_name
     and a.confidence = 'high'
     and a.source = :alias_source
    join ingredients target
      on target.id = a.ingredient_id
     and target.is_active = true
     and target.ingredient_code not like 'ing_pending_%'
     and target.ingredient_code not like 'foreign_pending_%'
     and lower(coalesce(target.source_url, '')) like '%kcia%'
    left join ingredient_mapping_reviews rev
      on rev.source_ingredient_id = g.source_ingredient_id
     and rev.normalized_source_name = g.normalized_source_name
    where rev.id is null
      and not exists (
        select 1
        from ingredients canonical
        where canonical.normalized_name = g.normalized_source_name
          and canonical.is_active = true
          and canonical.ingredient_code not like 'ing_pending_%'
          and canonical.ingredient_code not like 'foreign_pending_%'
          and canonical.id <> target.id
      )
"""


def get_kcia_alias_exact_bulk_preview(session: Session) -> IngredientMappingBulkApprovalPreviewResponse:
    """현재 시점에 서버 기준을 모두 통과한 후보만 최대 100개 반환한다."""

    eligible_count = int(
        session.execute(
            text(f"select count(*) {_ELIGIBLE_FROM_SQL}"),
            {"alias_source": KCIA_ALIAS_SOURCE},
        ).scalar_one()
    )
    rows = session.execute(
        text(
            f"""
            select g.pending_code, g.normalized_source_name, g.raw_name,
                   g.product_count, g.connection_count,
                   target.ingredient_code as target_ingredient_code,
                   target.name_ko as target_ingredient_name,
                   a.source as alias_source, target.source_url as canonical_source_url
            {_ELIGIBLE_FROM_SQL}
            order by g.connection_count desc, g.pending_code asc, g.normalized_source_name asc
            limit :limit
            """
        ),
        {"alias_source": KCIA_ALIAS_SOURCE, "limit": MAX_BULK_APPROVAL_COUNT},
    ).all()
    return IngredientMappingBulkApprovalPreviewResponse(
        criteria="KCIA_ALIAS_EXACT",
        maximum_count=MAX_BULK_APPROVAL_COUNT,
        eligible_count=eligible_count,
        items=[
            IngredientMappingBulkApprovalPreviewItem(
                pending_code=row.pending_code,
                normalized_source_name=row.normalized_source_name,
                raw_name=row.raw_name,
                product_count=int(row.product_count),
                connection_count=int(row.connection_count),
                target_ingredient_code=row.target_ingredient_code,
                target_ingredient_name=row.target_ingredient_name,
                alias_source=row.alias_source,
                canonical_source_url=row.canonical_source_url,
            )
            for row in rows
        ],
    )


def approve_kcia_alias_exact_batch(
    session: Session,
    *,
    items: list[IngredientMappingBulkApprovalItem],
    confirmed_count: int,
    actor_user_id: int,
) -> IngredientMappingBulkApprovalResponse:
    """선택 항목을 전부 재검증한 뒤 하나의 트랜잭션으로 승인한다.

    하나라도 현재 기준에서 이탈했거나 상태가 바뀌면 ApiError를 내보내며, 라우터가
    트랜잭션 전체를 rollback한다. 부분 성공 응답을 만들지 않는다.
    """

    if confirmed_count != len(items):
        raise ApiError(
            400,
            "BULK_APPROVAL_CONFIRMATION_MISMATCH",
            "Confirmed count must match the number of selected mapping groups.",
        )
    identities = {(item.pending_code, item.normalized_source_name) for item in items}
    if len(identities) != len(items):
        raise ApiError(400, "BULK_APPROVAL_DUPLICATE_ITEM", "A mapping group was selected more than once.")

    batch_reference = f"{BULK_REFERENCE_PREFIX}:{uuid4()}"
    responses: list[IngredientMappingActionResponse] = []
    for item in items:
        _require_current_kcia_alias_exact_candidate(session, item)
        responses.append(
            approve_ingredient_mapping(
                session,
                pending_code=item.pending_code,
                normalized_source_name=item.normalized_source_name,
                target_ingredient_code=item.target_ingredient_code,
                decision_reason="KCIA 근거 별칭 정확 일치 일괄 승인",
                actor_user_id=actor_user_id,
                source_reference=batch_reference,
            )
        )
    return IngredientMappingBulkApprovalResponse(
        batch_reference=batch_reference,
        approved_count=len(responses),
        items=responses,
    )


def _require_current_kcia_alias_exact_candidate(
    session: Session, item: IngredientMappingBulkApprovalItem
) -> None:
    row = session.execute(
        text(
            f"""
            select 1
            {_ELIGIBLE_FROM_SQL}
              and g.pending_code = :pending_code
              and g.normalized_source_name = :normalized_source_name
              and target.ingredient_code = :target_ingredient_code
            """
        ),
        {
            "alias_source": KCIA_ALIAS_SOURCE,
            "pending_code": item.pending_code,
            "normalized_source_name": item.normalized_source_name,
            "target_ingredient_code": item.target_ingredient_code,
        },
    ).first()
    if row is None:
        raise ApiError(
            409,
            "BULK_APPROVAL_ITEM_INELIGIBLE",
            "A selected mapping group is no longer an eligible KCIA alias exact-match candidate.",
        )
