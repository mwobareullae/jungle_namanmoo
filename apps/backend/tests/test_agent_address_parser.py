from app.services.agent_address_tools import (
    get_shipping_address_clarification,
    parse_shipping_address_details,
)


def test_parse_shipping_address_accepts_labelled_fields_in_any_order() -> None:
    parsed = parse_shipping_address_details(
        "주소: 서울특별시 중구 세종대로 110, 연락처: 010-1234-5678, "
        "우편번호: 04524, 받는 분: 김원우, 배송 메모: 문 앞에 놓아주세요"
    )

    assert parsed == {
        "recipient_name": "김원우",
        "phone": "01012345678",
        "postal_code": "04524",
        "address1": "서울특별시 중구 세종대로 110",
        "address2": None,
        "delivery_memo": "문 앞에 놓아주세요",
    }


def test_parse_shipping_address_accepts_free_form_fields_in_any_order() -> None:
    parsed = parse_shipping_address_details(
        "010 1234 5678 / 서울특별시 중구 세종대로 110 3층 / 04524 / 김원우"
    )

    assert parsed == {
        "recipient_name": "김원우",
        "phone": "01012345678",
        "postal_code": "04524",
        "address1": "서울특별시 중구 세종대로 110 3층",
        "address2": None,
        "delivery_memo": None,
    }


def test_parse_shipping_address_allows_profile_name_and_phone_fallbacks() -> None:
    parsed = parse_shipping_address_details("04524, 서울특별시 중구 세종대로 110")

    assert parsed == {
        "recipient_name": None,
        "phone": None,
        "postal_code": "04524",
        "address1": "서울특별시 중구 세종대로 110",
        "address2": None,
        "delivery_memo": None,
    }


def test_parse_shipping_address_requires_postal_code_and_address() -> None:
    assert parse_shipping_address_details("김원우, 010-1234-5678, 서울특별시 중구 세종대로 110") is None
    assert parse_shipping_address_details("김원우, 010-1234-5678, 04524") is None


def test_shipping_address_clarification_handles_only_labelled_invalid_postal_code() -> None:
    assert get_shipping_address_clarification(
        "받는 분: 김원우, 연락처: 010-1234-5678, 우편번호: 0452, 주소: 서울특별시 중구 세종대로 110"
    ) == "우편번호는 숫자 5자리로 알려주세요."
    assert get_shipping_address_clarification(
        "받는 분: 김원우, 연락처: 010-1234-5678, 우편번호: 04524, 주소: 서울특별시 중구 세종대로 110"
    ) is None
