from datetime import UTC, datetime, timedelta
import secrets
from typing import Literal

from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.schemas.agent import (
    AgentChatResponse,
    AgentError,
    AgentLastToolResult,
    AgentResponseItem,
    AgentToolConfirmResponse,
    AgentUiAction,
)
from app.schemas.common import ApiError
from app.schemas.order import OrderCreateRequest
from app.services.address_service import get_user_addresses
from app.services.agent_policy import validate_tool_access, validate_tool_ui_action
from app.services.agent_product_reference import ProductReferenceSource, resolve_product_reference
from app.services.cart_service import (
    add_cart_item,
    get_cart_response,
    get_checkout_preview,
    update_cart_item_quantity,
)
from app.services.order_service import create_order


GET_CART_TOOL = "get_cart"
ADD_TO_CART_TOOL = "add_to_cart"
PREPARE_PRODUCT_CHECKOUT_TOOL = "prepare_product_checkout"
PREPARE_CHECKOUT_TOOL = "prepare_checkout"
PREPARE_ORDER_TOOL = "prepare_order"
ORDER_CONFIRMATION_TTL_MINUTES = 10


def get_agent_cart(
    session: Session,
    user: User | None,
    *,
    conversation_id: str | None,
    anonymous_cart_id: str | None = None,
) -> AgentChatResponse:
    validate_tool_access(GET_CART_TOOL, user_id=user.id if user is not None else None)
    cart = get_cart_response(session, user, anonymous_cart_id)
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
    user: User | None,
    *,
    conversation_id: str | None,
    product_id: str | None,
    quantity: int,
    recommendation_id: str | None,
    recommendation_rank: int | None,
    reference_source: ProductReferenceSource | None = None,
    reference_rank: int | None = None,
    reference_position: Literal["first", "last"] | None = None,
    current_product_id: str | None = None,
    anonymous_cart_id: str | None = None,
    last_tool_result: AgentLastToolResult | None = None,
) -> AgentChatResponse:
    validate_tool_access(ADD_TO_CART_TOOL, user_id=user.id if user is not None else None)
    reference = resolve_product_reference(
        session,
        product_id=product_id,
        source=reference_source,
        rank=reference_rank,
        current_product_id=current_product_id,
        recommendation_id=recommendation_id,
        user=user,
        position=reference_position,
        last_tool_result=last_tool_result,
    )
    result = add_cart_item(
        session,
        user,
        anonymous_cart_id,
        product_code=reference.product_id,
        quantity=quantity,
        source=f"agent:{reference.source}",
        recommendation_id=reference.recommendation_id or recommendation_id,
        recommendation_rank=reference.rank if reference.source == "recommendation" else recommendation_rank,
    )
    action = AgentUiAction(type="show_cart", target="cart", payload=jsonable_encoder(result.cart))
    validate_tool_ui_action(ADD_TO_CART_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=f"{reference.label} 장바구니에 담았어요.",
        tool_name=ADD_TO_CART_TOOL,
        ui_action=action,
    )


def prepare_agent_product_checkout(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    product_id: str | None,
    quantity: int,
    recommendation_id: str | None,
    recommendation_rank: int | None,
    reference_source: ProductReferenceSource | None = None,
    reference_rank: int | None = None,
    reference_position: Literal["first", "last"] | None = None,
    current_product_id: str | None = None,
    last_tool_result: AgentLastToolResult | None = None,
) -> AgentChatResponse:
    validate_tool_access(PREPARE_PRODUCT_CHECKOUT_TOOL, user_id=user.id)
    reference = resolve_product_reference(
        session,
        product_id=product_id,
        source=reference_source,
        rank=reference_rank,
        current_product_id=current_product_id,
        recommendation_id=recommendation_id,
        user=user,
        position=reference_position,
        last_tool_result=last_tool_result,
    )
    product_id = reference.product_id
    recommendation_id = reference.recommendation_id or recommendation_id
    recommendation_rank = reference.rank or recommendation_rank
    cart = get_cart_response(session, user, None)
    existing = next((item for item in cart.items if item.product_id == product_id), None)
    if existing is None:
        cart = add_cart_item(
            session,
            user,
            None,
            product_code=product_id,
            quantity=quantity,
            source="agent_product_checkout",
            recommendation_id=recommendation_id,
            recommendation_rank=recommendation_rank,
        ).cart
    else:
        cart = update_cart_item_quantity(
            session,
            user,
            None,
            item_id=existing.id,
            quantity=max(existing.quantity, quantity),
        )

    selected_item = next(item for item in cart.items if item.product_id == product_id)
    response_item = AgentResponseItem(
        item_type="product",
        id=selected_item.product_id,
        title=selected_item.product.name,
        subtitle=selected_item.product.brand,
        image_storage_key=selected_item.product.thumbnail_url or None,
        price=selected_item.product.current_price,
        currency=selected_item.product.currency,
        metadata={
            "cart_item_id": selected_item.id,
            "quantity": selected_item.quantity,
            "recommendation_id": selected_item.recommendation_id,
            "recommendation_rank": selected_item.recommendation_rank,
        },
    )
    addresses = get_user_addresses(session, user).items
    default_address = next(
        (item for item in addresses if item.is_default),
        addresses[0] if addresses else None,
    )
    if default_address is None:
        action = AgentUiAction(
            type="noop",
            payload={
                "agent_flow": "product_checkout",
                "cart_item_ids": [selected_item.id],
                "highlight_product_id": product_id,
                "continuation": "register_shipping_address",
            },
        )
        validate_tool_ui_action(PREPARE_PRODUCT_CHECKOUT_TOOL, action)
        return AgentChatResponse(
            conversation_id=_conversation_id(conversation_id),
            message=(
                "상품은 장바구니에 반영했어요. 받는 분 이름, 연락처, 우편번호, "
                "기본 주소와 상세 주소를 알려주시면 주문서를 이어서 열어드릴게요."
            ),
            tool_name=PREPARE_PRODUCT_CHECKOUT_TOOL,
            ui_action=action,
            items=[response_item],
            error=AgentError(
                code="AGENT_ADDRESS_REQUIRED",
                message="주문서 이동을 위해 배송지가 필요해요.",
                retryable=False,
            ),
        )

    preview = get_checkout_preview(
        session,
        user,
        None,
        cart_item_ids=[selected_item.id],
        address_id=default_address.id,
    )
    if not preview.can_checkout:
        raise ApiError(409, "AGENT_CHECKOUT_BLOCKED", "선택한 상품은 현재 주문할 수 없어요.")
    payload = {
        **jsonable_encoder(preview),
        "address_id": default_address.id,
        "agent_flow": "product_checkout",
        "highlight_product_id": product_id,
    }
    action = AgentUiAction(
        type="show_checkout_preview",
        target="checkout_preview",
        payload=payload,
    )
    validate_tool_ui_action(PREPARE_PRODUCT_CHECKOUT_TOOL, action)
    return AgentChatResponse(
        conversation_id=_conversation_id(conversation_id),
        message=(
            "선택한 상품을 장바구니에 반영하고 주문서를 열었어요. "
            "상품과 배송지, 최종 금액을 확인해 주세요."
        ),
        tool_name=PREPARE_PRODUCT_CHECKOUT_TOOL,
        ui_action=action,
        items=[response_item],
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
        raise ApiError(409, "AGENT_CHECKOUT_BLOCKED", "선택한 장바구니 상품은 현재 주문할 수 없어요.")

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
        raise ApiError(400, "AGENT_ORDER_INPUT_INVALID", "저장된 장바구니 선택 정보를 확인할 수 없어요.")
    if not isinstance(address_id, int):
        raise ApiError(400, "AGENT_ORDER_INPUT_INVALID", "저장된 배송지 선택 정보를 확인할 수 없어요.")

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
        raise ApiError(400, "AGENT_CART_EMPTY", "장바구니가 비어 있어요.")

    selected_address_id = address_id
    if selected_address_id is None:
        addresses = get_user_addresses(session, user).items
        default_address = next((item for item in addresses if item.is_default), addresses[0] if addresses else None)
        if default_address is None:
            raise ApiError(409, "AGENT_ADDRESS_REQUIRED", "주문서 이동을 위해 배송지가 필요해요.")
        selected_address_id = default_address.id
    return selected_item_ids, selected_address_id


def _conversation_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else f"conv_{secrets.token_urlsafe(12)}"
