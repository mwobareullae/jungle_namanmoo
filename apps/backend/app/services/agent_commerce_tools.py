from datetime import UTC, datetime, timedelta
import secrets

from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.schemas.agent import AgentChatResponse, AgentToolConfirmResponse, AgentUiAction
from app.schemas.common import ApiError
from app.schemas.order import OrderCreateRequest
from app.services.address_service import get_user_addresses
from app.services.agent_policy import validate_tool_access, validate_tool_ui_action
from app.services.cart_service import add_cart_item, get_cart_response, get_checkout_preview
from app.services.order_service import create_order


GET_CART_TOOL = "get_cart"
ADD_TO_CART_TOOL = "add_to_cart"
PREPARE_CHECKOUT_TOOL = "prepare_checkout"
PREPARE_ORDER_TOOL = "prepare_order"
ORDER_CONFIRMATION_TTL_MINUTES = 10


def get_agent_cart(session: Session, user: User, *, conversation_id: str | None) -> AgentChatResponse:
    validate_tool_access(GET_CART_TOOL, user_id=user.id)
    cart = get_cart_response(session, user, None)
    action = AgentUiAction(type="show_cart", target="cart", payload=jsonable_encoder(cart))
    validate_tool_ui_action(GET_CART_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=f"장바구니에 {cart.total_quantity}개 상품이 있어요.",
        tool_name=GET_CART_TOOL,
        ui_action=action,
    )


def add_agent_cart_item(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    product_id: str,
    quantity: int,
    recommendation_id: str | None,
    recommendation_rank: int | None,
) -> AgentChatResponse:
    validate_tool_access(ADD_TO_CART_TOOL, user_id=user.id)
    result = add_cart_item(
        session,
        user,
        None,
        product_code=product_id,
        quantity=quantity,
        source="agent",
        recommendation_id=recommendation_id,
        recommendation_rank=recommendation_rank,
    )
    action = AgentUiAction(type="show_cart", target="cart", payload=jsonable_encoder(result.cart))
    validate_tool_ui_action(ADD_TO_CART_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=f"상품 {quantity}개를 장바구니에 담았어요.",
        tool_name=ADD_TO_CART_TOOL,
        ui_action=action,
    )


def prepare_agent_checkout(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    cart_item_ids: list[int] | None,
    address_id: int | None,
) -> AgentChatResponse:
    validate_tool_access(PREPARE_CHECKOUT_TOOL, user_id=user.id)
    selected_item_ids, selected_address_id = _resolve_checkout_selection(
        session, user, cart_item_ids=cart_item_ids, address_id=address_id
    )
    preview = get_checkout_preview(
        session,
        user,
        None,
        cart_item_ids=selected_item_ids,
        address_id=selected_address_id,
    )
    payload = jsonable_encoder(preview)
    payload["address_id"] = selected_address_id
    action = AgentUiAction(type="show_checkout_preview", target="checkout_preview", payload=payload)
    validate_tool_ui_action(PREPARE_CHECKOUT_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=f"배송비를 포함한 결제 예정 금액은 {preview.total:,}원이에요.",
        tool_name=PREPARE_CHECKOUT_TOOL,
        ui_action=action,
    )


def prepare_agent_order(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    cart_item_ids: list[int] | None,
    address_id: int | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    validate_tool_access(PREPARE_ORDER_TOOL, user_id=user.id)
    selected_item_ids, selected_address_id = _resolve_checkout_selection(
        session, user, cart_item_ids=cart_item_ids, address_id=address_id
    )
    preview = get_checkout_preview(
        session,
        user,
        None,
        cart_item_ids=selected_item_ids,
        address_id=selected_address_id,
    )
    if not preview.can_checkout:
        raise ApiError(409, "AGENT_CHECKOUT_BLOCKED", "The selected cart items cannot be checked out.")

    now = datetime.now(UTC)
    tool_call_id = f"tool_{secrets.token_urlsafe(18)}"
    expires_at = now + timedelta(minutes=ORDER_CONFIRMATION_TTL_MINUTES)
    payload = {
        **jsonable_encoder(preview),
        "address_id": selected_address_id,
        "payment_provider": "TOSS",
        "tool_call_id": tool_call_id,
        "expires_at": expires_at.isoformat(),
    }
    session.add(
        AgentToolCall(
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            user_id=user.id,
            anonymous_user_id=anonymous_user_id,
            session_id=session_id,
            request_id=request_id,
            tool_name=PREPARE_ORDER_TOOL,
            status="AWAITING_CONFIRMATION",
            confirmation_required=True,
            expires_at=expires_at,
            input_json={
                "cart_item_ids": selected_item_ids,
                "address_id": selected_address_id,
                "payment_provider": "TOSS",
            },
            output_json=payload,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    action = AgentUiAction(type="open_modal", target="order_create_confirm", payload=payload)
    validate_tool_ui_action(PREPARE_ORDER_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=f"총 {preview.total:,}원 주문을 만들기 전에 내용을 확인해 주세요.",
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=PREPARE_ORDER_TOOL,
        ui_action=action,
    )


def execute_confirmed_agent_order(
    session: Session,
    user: User,
    tool_call: AgentToolCall,
) -> AgentToolConfirmResponse:
    input_json = dict(tool_call.input_json or {})
    cart_item_ids = input_json.get("cart_item_ids")
    address_id = input_json.get("address_id")
    if not isinstance(cart_item_ids, list) or not all(isinstance(item_id, int) for item_id in cart_item_ids):
        raise ApiError(400, "AGENT_ORDER_INPUT_INVALID", "Stored cart selection is invalid.")
    if not isinstance(address_id, int):
        raise ApiError(400, "AGENT_ORDER_INPUT_INVALID", "Stored address selection is invalid.")

    order = create_order(
        session,
        user,
        OrderCreateRequest(cart_item_ids=cart_item_ids, address_id=address_id, payment_provider="TOSS"),
        f"agent:{tool_call.tool_call_id}",
    )
    payload = {
        "order_code": order.order_code,
        "payment_code": order.payment.payment_code,
        "amount": order.total,
        "currency": order.currency,
        "payment_provider": "TOSS",
    }
    return AgentToolConfirmResponse(
        tool_call_id=tool_call.tool_call_id,
        status="EXECUTED",
        message="주문이 생성됐어요. Toss 결제창에서 결제를 완료해 주세요.",
        ui_action=AgentUiAction(type="open_payment", target="toss_payment", payload=payload),
    )


def _resolve_checkout_selection(
    session: Session,
    user: User,
    *,
    cart_item_ids: list[int] | None,
    address_id: int | None,
) -> tuple[list[int], int]:
    cart = get_cart_response(session, user, None)
    selected_item_ids = cart_item_ids or [item.id for item in cart.items]
    if not selected_item_ids:
        raise ApiError(400, "AGENT_CART_EMPTY", "The cart is empty.")

    selected_address_id = address_id
    if selected_address_id is None:
        addresses = get_user_addresses(session, user).items
        default_address = next((item for item in addresses if item.is_default), addresses[0] if addresses else None)
        if default_address is None:
            raise ApiError(409, "AGENT_ADDRESS_REQUIRED", "A shipping address is required.")
        selected_address_id = default_address.id
    return selected_item_ids, selected_address_id


def _conversation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else f"conv_{secrets.token_urlsafe(12)}"
