from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.schemas.agent import AgentChatResponse, AgentResponseItem, AgentUiAction
from app.schemas.common import ApiError
from app.services.agent_policy import (
    validate_result_item_count,
    validate_tool_access,
    validate_tool_ui_action,
)
from app.services.review_user_query_service import get_reviewable_order_items


PREPARE_REVIEW_DRAFT_TOOL = "prepare_review_draft"


def prepare_review_draft(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    order_code: str | None,
    product_id: str | None,
    rating: int,
    review_text: str,
    is_repurchase_review: bool,
) -> AgentChatResponse:
    validate_tool_access(PREPARE_REVIEW_DRAFT_TOOL, user_id=user.id)
    response = get_reviewable_order_items(session, current_user=user, page=1, page_size=50)
    candidates = [item for item in response.items if item.can_write]
    if order_code:
        candidates = [item for item in candidates if item.order_code == order_code]
    if product_id:
        candidates = [item for item in candidates if item.product_id == product_id]
    if not candidates:
        raise ApiError(409, "AGENT_REVIEW_NOT_AVAILABLE", "작성 가능한 구매 리뷰 상품을 찾지 못했어요.")

    selected = candidates[0]
    payload = {
        "order_item_id": selected.order_item_id,
        "order_code": selected.order_code,
        "product_id": selected.product_id,
        "product_name": selected.product_name,
        "rating": rating,
        "review_text": review_text.strip(),
        "is_repurchase_review": is_repurchase_review,
    }
    action = AgentUiAction(type="navigate", target="review_write", payload=payload)
    validate_tool_ui_action(PREPARE_REVIEW_DRAFT_TOOL, action)
    validate_result_item_count(PREPARE_REVIEW_DRAFT_TOOL, 1)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message="실제 구매 상품의 리뷰 초안을 작성 화면에 넣어뒀어요. 내용을 확인한 뒤 직접 등록해 주세요.",
        tool_name=PREPARE_REVIEW_DRAFT_TOOL,
        ui_action=action,
        items=[
            AgentResponseItem(
                item_type="product",
                id=selected.product_id,
                title=selected.product_name,
                subtitle=f"{selected.brand_name} · {rating}점",
                image_storage_key=selected.thumbnail_storage_key,
                metadata={"order_code": selected.order_code, "order_item_id": selected.order_item_id},
            )
        ],
    )


def _conversation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else "conv_agent_review"
