import pytest

from app.schemas.common import ApiError
from app.services.agent_safety import reject_sensitive_agent_input


@pytest.mark.parametrize(
    "message",
    [
        "password: secret-value",
        "api_key=abcdefghijklmnopqrstuvwxyz",
        "카드번호 4111 1111 1111 1111",
    ],
)
def test_reject_sensitive_agent_input(message: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        reject_sensitive_agent_input(message)

    assert exc_info.value.code == "AGENT_SENSITIVE_INPUT"


def test_allow_shipping_phone_number_in_agent_input() -> None:
    reject_sensitive_agent_input("연락처는 010-1234-5678이고 서울특별시 강남구 테헤란로 123이에요.")
