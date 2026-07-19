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


def test_direct_shipping_address_requires_detail_address() -> None:
    with pytest.raises(ValidationError):
        DirectShippingAddressRequest(
            recipient_name="배송 받는 사람",
            phone="01012345678",
            postal_code="04524",
            address1="서울특별시 중구 세종대로 110",
        )
