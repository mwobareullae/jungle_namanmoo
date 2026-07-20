import secrets

from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.schemas.address import UserAddressCreateRequest
from app.schemas.agent import AgentChatResponse, AgentUiAction
from app.schemas.common import ApiError
from app.services.address_service import create_user_address
from app.services.agent_commerce_tools import prepare_agent_checkout
from app.services.agent_policy import validate_tool_access, validate_tool_ui_action


REGISTER_SHIPPING_ADDRESS_TOOL = "register_shipping_address"


def register_shipping_address(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    recipient_name: str | None,
    phone: str | None,
    postal_code: str,
    address1: str,
    address2: str,
    delivery_memo: str | None,
    is_default: bool,
    continue_checkout: bool,
    cart_item_ids: list[int] | None,
) -> AgentChatResponse:
    validate_tool_access(REGISTER_SHIPPING_ADDRESS_TOOL, user_id=user.id)

    resolved_recipient_name = _resolve_required_profile_value(
        recipient_name,
        user.display_name,
        "받는 분 이름을 알려주세요.",
    )
    resolved_phone = _resolve_required_profile_value(
        phone,
        user.phone,
        "받는 분 연락처를 알려주세요.",
    )
    address = create_user_address(
        session,
        user,
        UserAddressCreateRequest(
            recipient_name=resolved_recipient_name,
            phone=resolved_phone,
            postal_code=postal_code,
            address1=address1,
            address2=address2,
            delivery_memo=delivery_memo,
            is_default=is_default,
        ),
    )

    if continue_checkout:
        checkout_response = prepare_agent_checkout(
            session,
            user,
            conversation_id=conversation_id,
            cart_item_ids=cart_item_ids,
            address_id=address.id,
        )
        return checkout_response.model_copy(
            update={
                "message": "배송지를 등록했어요. 이 배송지로 주문서를 준비할게요.",
                "tool_name": REGISTER_SHIPPING_ADDRESS_TOOL,
            }
        )

    action = AgentUiAction()
    validate_tool_ui_action(REGISTER_SHIPPING_ADDRESS_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message="배송지를 등록했어요.",
        tool_name=REGISTER_SHIPPING_ADDRESS_TOOL,
        ui_action=action,
    )


def _resolve_required_profile_value(value: str | None, fallback: str | None, missing_message: str) -> str:
    normalized = (value or fallback or "").strip()
    if not normalized:
        raise ApiError(400, "AGENT_ADDRESS_DETAILS_REQUIRED", missing_message)
    return normalized


def _conversation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else f"conv_{secrets.token_urlsafe(12)}"
