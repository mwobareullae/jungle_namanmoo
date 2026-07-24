from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderItem
from app.schemas.agent import AgentChatResponse, AgentResponseItem, AgentUiAction
from app.schemas.claim import ClaimType
from app.schemas.common import ApiError
from app.services.agent_policy import (
    validate_result_item_count,
    validate_tool_access,
    validate_tool_ui_action,
)
from app.services.order_claim_service import get_claim_eligibility


PREPARE_CLAIM_DRAFT_TOOL = "prepare_claim_draft"
ALLOWED_REASON_CODES = {"CHANGE_OF_MIND", "DEFECTIVE", "WRONG_ITEM", "OTHER"}


def prepare_claim_draft(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    order_code: str | None,
    order_item_id: int | None,
    claim_type: ClaimType,
    reason_code: str,
    reason_detail: str | None,
) -> AgentChatResponse:
    validate_tool_access(PREPARE_CLAIM_DRAFT_TOOL, user_id=user.id)
    normalized_reason = reason_code.strip().upper()
    if normalized_reason not in ALLOWED_REASON_CODES:
        raise ApiError(400, "AGENT_CLAIM_REASON_INVALID", "지원하지 않는 신청 사유예요.")

    order = _find_eligible_order(session, user, order_code)
    eligibility = get_claim_eligibility(session, user, order.order_code)
    eligible_item_ids = {
        item.order_item_id for item in eligibility.items if item.claimable_quantity > 0
    }
    selected_item_id = order_item_id or next(
        (item.order_item_id for item in eligibility.items if item.claimable_quantity > 0),
        None,
    )
    if selected_item_id is None or selected_item_id not in eligible_item_ids:
        raise ApiError(409, "AGENT_CLAIM_ITEM_NOT_AVAILABLE", "신청 가능한 주문 상품을 찾지 못했어요.")

    order_item = session.execute(
        select(OrderItem).where(OrderItem.id == selected_item_id, OrderItem.order_id == order.id)
    ).scalar_one_or_none()
    if order_item is None:
        raise ApiError(404, "ORDER_ITEM_NOT_FOUND", "주문 상품을 찾지 못했어요.")

    payload = {
        "order_code": order.order_code,
        "order_item_id": selected_item_id,
        "claim_type": claim_type,
        "reason_code": normalized_reason,
        "reason_detail": reason_detail.strip() if reason_detail and reason_detail.strip() else None,
    }
    action = AgentUiAction(type="navigate", target="claim_request", payload=payload)
    validate_tool_ui_action(PREPARE_CLAIM_DRAFT_TOOL, action)
    validate_result_item_count(PREPARE_CLAIM_DRAFT_TOOL, 1)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message="신청 가능한 주문인지 확인하고 내용을 신청 화면에 넣어뒀어요. 최종 내용을 확인한 뒤 직접 접수해 주세요.",
        tool_name=PREPARE_CLAIM_DRAFT_TOOL,
        ui_action=action,
        items=[
            AgentResponseItem(
                item_type="order",
                id=order.order_code,
                title=order_item.product_name_snapshot,
                subtitle=f"{order_item.brand_name_snapshot} · {claim_type}",
                image_storage_key=order_item.thumbnail_storage_key_snapshot,
                metadata={"order_item_id": selected_item_id, "reason_code": normalized_reason},
            )
        ],
    )


def _find_eligible_order(session: Session, user: User, order_code: str | None) -> Order:
    if order_code and order_code.strip():
        orders = session.execute(
            select(Order).where(Order.user_id == user.id, Order.order_code == order_code.strip())
        ).scalars().all()
        if not orders:
            raise ApiError(404, "ORDER_NOT_FOUND", "주문을 찾지 못했어요.")
    else:
        orders = session.execute(
            select(Order)
            .where(Order.user_id == user.id, Order.status == "DELIVERED")
            .order_by(Order.ordered_at.desc(), Order.id.desc())
            .limit(20)
        ).scalars().all()

    for order in orders:
        eligibility = get_claim_eligibility(session, user, order.order_code)
        if eligibility.eligible and any(item.claimable_quantity > 0 for item in eligibility.items):
            return order
    raise ApiError(409, "AGENT_CLAIM_NOT_AVAILABLE", "현재 신청 가능한 배송완료 주문을 찾지 못했어요.")


def _conversation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else "conv_agent_claim"
