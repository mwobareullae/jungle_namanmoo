"""관리자 성분 매핑 검수 판정 서비스 (P1-M2-A, 쓰기).

승인·보류·반려·재검토 결정을 `ingredient_mapping_reviews` 에 저장하고, 변경마다
append-only `ingredient_mapping_review_events` 를 남긴다. **기존 `product_ingredients`·
전역 alias·검색/추천 rollup 은 절대 변경하지 않는다(M2-B 이연).** 신규 상품 입력
자동 적용도 여기서 하지 않는다(M2-A2).

서비스는 `flush()` 까지만 수행하고 commit/rollback·성능 로그는 라우터가 담당한다.
상세 계약: `docs/admin/admin-m2a-ingredient-mapping-api-contract.md` §7~§9.
"""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models.taxonomy import (
    Ingredient,
    IngredientMappingReview,
    IngredientMappingReviewEvent,
)
from app.schemas.admin.ingredient_mapping import IngredientMappingActionResponse
from app.schemas.common import ApiError
from app.services.admin.ingredient_mapping_service import (
    _ACTIONS_BY_STATUS,
    _NORMALIZE_SQL,
    _build_suggestion,
    _effective_status,
    _load_page_suggestions,
)


MAX_DECISION_REASON_LENGTH = 1000
MAX_EVIDENCE_SOURCE_URL_LENGTH = 2000
MAX_SOURCE_REFERENCE_LENGTH = 255
NON_MAPPING_FINAL_DISPOSITIONS = frozenset(
    {"NON_INGREDIENT", "COMPOUND_MATERIAL", "SOURCE_ERROR", "UNRESOLVABLE"}
)

# 액션별 허용 시작 상태(현재 유효 상태 기준). 그 외 상태는 409 TRANSITION_NOT_ALLOWED.
# 단, 결과가 이미 같은 상태면 아래 멱등 처리로 새 이벤트 없이 반환한다.
_ALLOWED_SOURCE_STATUSES = {
    "APPROVE": {"PENDING", "HELD", "NEEDS_REVIEW"},
    "HOLD": {"PENDING", "HELD", "NEEDS_REVIEW"},
    "REJECT": {"PENDING", "HELD", "NEEDS_REVIEW"},
    "REOPEN": {"APPROVED", "REJECTED"},
}


def approve_ingredient_mapping(
    session: Session,
    *,
    pending_code: str,
    normalized_source_name: str,
    target_ingredient_code: str,
    decision_reason: str | None,
    actor_user_id: int,
    source_reference: str | None = None,
) -> IngredientMappingActionResponse:
    reason = _normalize_optional_reason(decision_reason)
    source = _load_locked_pending(session, pending_code)
    nsn = _require_group(session, source, normalized_source_name)
    target = _load_active_canonical(session, target_ingredient_code)
    review = _load_locked_review(session, source.id, nsn)
    current = _effective_status(review.status if review else None)

    # 멱등: 이미 같은 target 으로 APPROVED 면 이벤트 없이 그대로 반환.
    if review is not None and review.status == "APPROVED":
        if review.target_ingredient_id == target.id:
            return _to_response(source, nsn, review, target=target)
        raise ApiError(
            409,
            "INGREDIENT_MAPPING_DECISION_CONFLICT",
            "이미 다른 canonical 로 승인된 매핑입니다. 재검토 후 다시 승인하세요.",
        )

    _guard_transition("APPROVE", current)
    review = _upsert_review(session, review, source, nsn, actor_user_id)
    from_status, from_target, from_final_disposition = _snapshot_before(review)
    review.status = "APPROVED"
    review.final_disposition = "MAPPED"
    review.target_ingredient_id = target.id
    review.decision_reason = reason
    _stamp(review, actor_user_id)
    session.flush()  # 신규 review 의 id 확보
    _append_event(
        session,
        review,
        from_status,
        from_target,
        from_final_disposition,
        reason,
        actor_user_id,
        nsn,
        source,
        source_reference=source_reference,
    )
    session.flush()
    return _to_response(source, nsn, review, target=target)


def hold_ingredient_mapping(
    session: Session,
    *,
    pending_code: str,
    normalized_source_name: str,
    decision_reason: str,
    actor_user_id: int,
) -> IngredientMappingActionResponse:
    return _decide_no_target(
        session,
        action="HOLD",
        new_status="HELD",
        pending_code=pending_code,
        normalized_source_name=normalized_source_name,
        decision_reason=decision_reason,
        actor_user_id=actor_user_id,
    )


def reject_ingredient_mapping(
    session: Session,
    *,
    pending_code: str,
    normalized_source_name: str,
    decision_reason: str,
    final_disposition: str,
    evidence_source_url: str | None,
    source_reference: str | None,
    actor_user_id: int,
) -> IngredientMappingActionResponse:
    disposition, normalized_evidence_url, normalized_source_reference = _normalize_final_disposition_evidence(
        final_disposition,
        evidence_source_url,
        source_reference,
    )
    return _decide_no_target(
        session,
        action="REJECT",
        new_status="REJECTED",
        final_disposition=disposition,
        evidence_source_url=normalized_evidence_url,
        source_reference=normalized_source_reference,
        pending_code=pending_code,
        normalized_source_name=normalized_source_name,
        decision_reason=decision_reason,
        actor_user_id=actor_user_id,
    )


def reopen_ingredient_mapping(
    session: Session,
    *,
    pending_code: str,
    normalized_source_name: str,
    decision_reason: str,
    actor_user_id: int,
) -> IngredientMappingActionResponse:
    return _decide_no_target(
        session,
        action="REOPEN",
        new_status="NEEDS_REVIEW",
        final_disposition=None,
        evidence_source_url=None,
        source_reference=None,
        pending_code=pending_code,
        normalized_source_name=normalized_source_name,
        decision_reason=decision_reason,
        actor_user_id=actor_user_id,
    )


# 보류/반려/재검토 공통: target 을 저장하지 않고 사유 필수, HELD/REJECTED/HELD 로 전이.
def _decide_no_target(
    session: Session,
    *,
    action: str,
    new_status: str,
    final_disposition: str | None = None,
    evidence_source_url: str | None = None,
    source_reference: str | None = None,
    pending_code: str,
    normalized_source_name: str,
    decision_reason: str,
    actor_user_id: int,
) -> IngredientMappingActionResponse:
    reason = _require_reason(decision_reason)
    source = _load_locked_pending(session, pending_code)
    nsn = _require_group(session, source, normalized_source_name)
    review = _load_locked_review(session, source.id, nsn)
    current = _effective_status(review.status if review else None)

    # 멱등: 이미 목표 상태면 이벤트 없이 반환.
    if (
        review is not None
        and review.status == new_status
        and review.final_disposition == final_disposition
    ):
        return _to_response(source, nsn, review)

    _guard_transition(action, current)
    review = _upsert_review(session, review, source, nsn, actor_user_id)
    from_status, from_target, from_final_disposition = _snapshot_before(review)
    review.status = new_status
    review.target_ingredient_id = None
    review.final_disposition = final_disposition
    review.decision_reason = reason
    _stamp(review, actor_user_id)
    session.flush()  # 신규 review 의 id 확보
    _append_event(
        session,
        review,
        from_status,
        from_target,
        from_final_disposition,
        reason,
        actor_user_id,
        nsn,
        source,
        evidence_source_url=evidence_source_url,
        source_reference=source_reference,
    )
    session.flush()
    return _to_response(source, nsn, review)


# --- 로드·검증 -------------------------------------------------------------


def _load_locked_pending(session: Session, pending_code: str) -> Ingredient:
    code = (pending_code or "").strip()
    if not code:
        raise ApiError(404, "PENDING_INGREDIENT_NOT_FOUND", "Pending ingredient not found.")
    source = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == code).with_for_update()
    ).scalar_one_or_none()
    if source is None:
        raise ApiError(404, "PENDING_INGREDIENT_NOT_FOUND", "Pending ingredient not found.")
    if not (
        source.ingredient_code.startswith("ing_pending_")
        or source.ingredient_code.startswith("foreign_pending_")
    ):
        raise ApiError(409, "INGREDIENT_MAPPING_SOURCE_NOT_PENDING", "Source is not a pending ingredient.")
    return source


def _require_group(session: Session, source: Ingredient, normalized_source_name: str) -> str:
    nsn = normalized_source_name
    if nsn is None or not nsn.strip():
        raise ApiError(400, "NORMALIZED_SOURCE_NAME_REQUIRED", "normalized_source_name is required.")
    exists = session.execute(
        text(
            f"select 1 from product_ingredients pi where pi.ingredient_id = :sid "
            f"and {_NORMALIZE_SQL.format(col='pi.ingredient_name')} = :nsn limit 1"
        ),
        {"sid": source.id, "nsn": nsn},
    ).first()
    if exists is None:
        raise ApiError(404, "INGREDIENT_MAPPING_GROUP_NOT_FOUND", "Ingredient mapping group not found.")
    return nsn


def _load_active_canonical(session: Session, target_ingredient_code: str) -> Ingredient:
    code = (target_ingredient_code or "").strip()
    if not code:
        raise ApiError(404, "CANONICAL_INGREDIENT_NOT_FOUND", "Canonical ingredient not found.")
    target = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == code).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "CANONICAL_INGREDIENT_NOT_FOUND", "Canonical ingredient not found.")
    is_pending = target.ingredient_code.startswith("ing_pending_") or target.ingredient_code.startswith(
        "foreign_pending_"
    )
    if is_pending or not target.is_active:
        raise ApiError(
            409, "CANONICAL_INGREDIENT_NOT_AVAILABLE", "Target is not an active canonical ingredient."
        )
    return target


def _load_locked_review(
    session: Session, source_id: int, normalized_source_name: str
) -> IngredientMappingReview | None:
    return session.execute(
        select(IngredientMappingReview)
        .where(
            IngredientMappingReview.source_ingredient_id == source_id,
            IngredientMappingReview.normalized_source_name == normalized_source_name,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _guard_transition(action: str, current_status: str) -> None:
    if current_status not in _ALLOWED_SOURCE_STATUSES[action]:
        if action == "REOPEN" and current_status == "PENDING":
            raise ApiError(
                409, "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED", "미판정 상태는 재검토할 수 없습니다."
            )
        raise ApiError(
            409,
            "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED",
            f"현재 상태({current_status})에서 허용되지 않은 액션입니다.",
        )


# --- 쓰기 헬퍼 -------------------------------------------------------------


def _upsert_review(
    session: Session,
    review: IngredientMappingReview | None,
    source: Ingredient,
    normalized_source_name: str,
    actor_user_id: int,
) -> IngredientMappingReview:
    if review is not None:
        return review
    review = IngredientMappingReview(
        source_ingredient_id=source.id,
        source_ingredient_name=source.name_ko,
        normalized_source_name=normalized_source_name,
        status="HELD",  # 아래 호출부에서 즉시 최종 상태로 덮어씀
        reviewed_by_user_id=actor_user_id,
        reviewed_at=datetime.now(UTC),
    )
    session.add(review)
    return review


def _snapshot_before(review: IngredientMappingReview) -> tuple[str | None, int | None, str | None]:
    # 새로 만든(아직 flush 전) 행은 id 가 없으므로 최초 판정으로 간주(from=None).
    if review.id is None:
        return None, None, None
    return review.status, review.target_ingredient_id, review.final_disposition


def _stamp(review: IngredientMappingReview, actor_user_id: int) -> None:
    now = datetime.now(UTC)
    review.reviewed_by_user_id = actor_user_id
    review.reviewed_at = now
    review.updated_at = now


def _append_event(
    session: Session,
    review: IngredientMappingReview,
    from_status: str | None,
    from_target: int | None,
    from_final_disposition: str | None,
    reason: str | None,
    actor_user_id: int,
    normalized_source_name: str,
    source: Ingredient,
    *,
    evidence_source_url: str | None = None,
    source_reference: str | None = None,
) -> None:
    metadata = _suggestion_snapshot(session, normalized_source_name, source)
    if evidence_source_url is not None:
        metadata["final_disposition_evidence_source_url"] = evidence_source_url
    if source_reference is not None:
        metadata["final_disposition_source_reference"] = source_reference
    session.add(
        IngredientMappingReviewEvent(
            review_id=review.id,
            from_status=from_status,
            to_status=review.status,
            from_final_disposition=from_final_disposition,
            to_final_disposition=review.final_disposition,
            from_target_ingredient_id=from_target,
            to_target_ingredient_id=review.target_ingredient_id,
            actor_id=actor_user_id,
            reason=reason,
            metadata_json=metadata,
        )
    )


def _suggestion_snapshot(session: Session, normalized_source_name: str, source: Ingredient) -> dict:
    """판정 시점의 읽기 전용 추천을 스냅샷으로 남긴다(있을 때만)."""

    alias_hits, canonical_hits, _canonical_conflicts = _load_page_suggestions(
        session, [normalized_source_name]
    )
    suggestion = _build_suggestion(normalized_source_name, alias_hits, canonical_hits)
    if suggestion is None:
        return {}
    return {
        "suggestion_target_ingredient_code": suggestion.target_ingredient_code,
        "suggestion_match_source": suggestion.match_source,
    }


def _to_response(
    source: Ingredient,
    normalized_source_name: str,
    review: IngredientMappingReview,
    *,
    target: Ingredient | None = None,
) -> IngredientMappingActionResponse:
    # APPROVED 응답에는 항상 target(활성 canonical)이 함께 전달된다. HELD/REJECTED 는 target 없음.
    target_code = target.ingredient_code if (review.status == "APPROVED" and target is not None) else None
    target_name = target.name_ko if (review.status == "APPROVED" and target is not None) else None
    return IngredientMappingActionResponse(
        pending_code=source.ingredient_code,
        normalized_source_name=normalized_source_name,
        status=review.status,
        final_disposition=review.final_disposition,
        target_ingredient_code=target_code,
        target_ingredient_name=target_name,
        decision_reason=review.decision_reason,
        reviewed_at=review.reviewed_at,
        available_actions=list(_ACTIONS_BY_STATUS[review.status]),
    )


# --- 사유 정규화 -----------------------------------------------------------


def _require_reason(decision_reason: str) -> str:
    trimmed = (decision_reason or "").strip()
    if not trimmed:
        raise ApiError(400, "DECISION_REASON_REQUIRED", "사유를 입력해 주세요.")
    return trimmed[:MAX_DECISION_REASON_LENGTH]


def _normalize_optional_reason(decision_reason: str | None) -> str | None:
    if decision_reason is None:
        return None
    trimmed = decision_reason.strip()
    return trimmed[:MAX_DECISION_REASON_LENGTH] if trimmed else None


def _normalize_final_disposition_evidence(
    final_disposition: str,
    evidence_source_url: str | None,
    source_reference: str | None,
) -> tuple[str, str | None, str | None]:
    disposition = (final_disposition or "").strip().upper()
    if disposition not in NON_MAPPING_FINAL_DISPOSITIONS:
        raise ApiError(400, "INVALID_FINAL_DISPOSITION", "Invalid final disposition.")

    normalized_evidence_url = _normalize_optional_value(evidence_source_url, MAX_EVIDENCE_SOURCE_URL_LENGTH)
    normalized_source_reference = _normalize_optional_value(source_reference, MAX_SOURCE_REFERENCE_LENGTH)
    if disposition != "NON_INGREDIENT" and not (normalized_evidence_url or normalized_source_reference):
        raise ApiError(
            400,
            "FINAL_DISPOSITION_EVIDENCE_REQUIRED",
            "Evidence source URL or source reference is required for this final disposition.",
        )
    return disposition, normalized_evidence_url, normalized_source_reference


def _normalize_optional_value(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed[:max_length] if trimmed else None
