import re
import secrets
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.schemas.address import UserAddressCreateRequest
from app.schemas.agent import AgentChatResponse, AgentUiAction
from app.schemas.common import ApiError
from app.services.address_service import create_user_address
from app.services.agent_commerce_tools import prepare_agent_checkout
from app.services.agent_policy import validate_tool_access, validate_tool_ui_action


REGISTER_SHIPPING_ADDRESS_TOOL = "register_shipping_address"


_ADDRESS_LABEL_PATTERN = re.compile(
    r"(?<![\w가-힣])"
    r"(?P<label>"
    r"받는\s*분|수령인|수취인|성함|이름|"
    r"연락처|전화(?:번호)?|휴대폰|"
    r"우편번호|postal\s*code|"
    r"상세\s*주소|주소|address\s*2|address|"
    r"배송\s*메모|요청\s*사항|메모"
    r")"
    r"(?=\s|[:：]|은|는|$)\s*(?:은|는)?\s*[:：]?\s*",
    re.IGNORECASE,
)
_POSTAL_CODE_PATTERN = re.compile(r"(?<!\d)(?P<postal_code>\d{5})(?!\d)")
_MOBILE_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?P<phone>(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4})(?!\d)"
)
_ADDRESS_LOCATION_HINTS = ("시", "군", "구", "읍", "면", "동", "로", "길", "번길", "아파트", "빌딩", "호")


def parse_shipping_address_details(message: str) -> dict[str, Any] | None:
    """Extract a complete Korean shipping address from labelled or free-form input.

    This parser is intentionally conservative: it only returns a fast-path payload
    after finding both a five-digit postal code and an address. Missing values fall
    through to the narrow checkout Specialist, which can ask one clarification.
    """

    text = message.strip()
    if not text:
        return None

    labelled = _parse_labelled_address_fields(text)
    phone_match = _MOBILE_PHONE_PATTERN.search(text)
    postal_match = _POSTAL_CODE_PATTERN.search(text)
    phone = _normalize_phone(labelled.get("phone") or (phone_match.group("phone") if phone_match else None))
    postal_code = _normalize_postal_code(labelled.get("postal_code") or (postal_match.group("postal_code") if postal_match else None))

    recipient_name = _clean_address_value(labelled.get("recipient_name"))
    address1 = _clean_address_value(labelled.get("address1"))
    address2 = _clean_address_value(labelled.get("address2"))
    delivery_memo = _clean_address_value(labelled.get("delivery_memo"))

    residual_parts = _unlabelled_address_parts(text, labelled)
    if recipient_name is None:
        recipient_name = _find_recipient_name(residual_parts)
    if address1 is None:
        address_parts = [part for part in residual_parts if part != recipient_name]
        if address_parts:
            address1 = address_parts[0]
            if address2 is None and len(address_parts) > 1:
                address2 = " ".join(address_parts[1:])

    if postal_code is None or address1 is None:
        return None

    return {
        "recipient_name": recipient_name,
        "phone": phone,
        "postal_code": postal_code,
        "address1": address1,
        "address2": address2,
        "delivery_memo": delivery_memo,
    }


def _parse_labelled_address_fields(text: str) -> dict[str, str]:
    matches = list(_ADDRESS_LABEL_PATTERN.finditer(text))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        raw_value = text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        value = _clean_address_value(raw_value)
        if value is None:
            continue
        field_name = _address_field_name(match.group("label"))
        if field_name is not None and field_name not in fields:
            fields[field_name] = value
    return fields


def _address_field_name(label: str) -> str | None:
    normalized = re.sub(r"\s+", "", label).casefold()
    if normalized in {"받는분", "수령인", "수취인", "성함", "이름"}:
        return "recipient_name"
    if normalized in {"연락처", "전화", "전화번호", "휴대폰"}:
        return "phone"
    if normalized in {"우편번호", "postalcode"}:
        return "postal_code"
    if normalized in {"주소", "address"}:
        return "address1"
    if normalized in {"상세주소", "address2"}:
        return "address2"
    if normalized in {"배송메모", "요청사항", "메모"}:
        return "delivery_memo"
    return None


def _unlabelled_address_parts(text: str, labelled: dict[str, str]) -> list[str]:
    without_phone = _MOBILE_PHONE_PATTERN.sub(" ", text)
    without_postal = _POSTAL_CODE_PATTERN.sub(" ", without_phone)
    for value in labelled.values():
        without_postal = without_postal.replace(value, " ")
    without_labels = _ADDRESS_LABEL_PATTERN.sub(" ", without_postal)
    parts = [_clean_address_value(part) for part in re.split(r"[,;/\n]+", without_labels)]
    return [part for part in parts if part]


def _find_recipient_name(parts: list[str]) -> str | None:
    for part in parts:
        normalized = part.replace(" ", "")
        if (
            len(normalized) <= 50
            and re.fullmatch(r"[가-힣A-Za-z.'-]+", normalized)
            and not any(hint in part for hint in _ADDRESS_LOCATION_HINTS)
        ):
            return part
    return None


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("82"):
        digits = f"0{digits[2:]}"
    return digits if re.fullmatch(r"01[016789]\d{7,8}", digits) else None


def _normalize_postal_code(value: str | None) -> str | None:
    if value is None:
        return None
    match = _POSTAL_CODE_PATTERN.search(value)
    return match.group("postal_code") if match else None


def _clean_address_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip(" \t\r\n,;/:-")
    return cleaned or None


def register_shipping_address(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    recipient_name: str | None,
    phone: str | None,
    postal_code: str,
    address1: str,
    address2: str | None,
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
