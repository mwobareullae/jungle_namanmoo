import pytest
from pydantic import ValidationError

from app.schemas.order import DirectShippingAddressRequest


def test_direct_shipping_address_normalizes_hyphenated_phone() -> None:
    request = DirectShippingAddressRequest(
        recipient_name="배송 받는 사람",
        phone="010-123-4567",
        postal_code="04524",
        address1="서울특별시 중구 세종대로 110",
        address2="3층",
    )

    assert request.phone == "0101234567"


def test_direct_shipping_address_allows_missing_detail_address() -> None:
    request = DirectShippingAddressRequest(
        recipient_name="배송 받는 사람",
        phone="01012345678",
        postal_code="04524",
        address1="서울특별시 중구 세종대로 110",
    )

    assert request.address2 is None


def test_direct_shipping_address_rejects_non_five_digit_postal_code() -> None:
    with pytest.raises(ValidationError, match="postal_code must contain exactly 5 digits"):
        DirectShippingAddressRequest(
            recipient_name="Recipient",
            phone="01012345678",
            postal_code="0452",
            address1="Seoul Jung-gu Sejong-daero 110",
        )
