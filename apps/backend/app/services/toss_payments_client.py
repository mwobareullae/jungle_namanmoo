import base64
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import settings


class TossPaymentsClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TossPaymentsClient:
    secret_key: str
    api_base_url: str = "https://api.tosspayments.com"
    timeout_seconds: float = 10.0

    @classmethod
    def from_settings(cls) -> "TossPaymentsClient":
        if not settings.toss_secret_key:
            raise TossPaymentsClientError(
                "TOSS_SECRET_KEY_MISSING",
                "TossPayments secret key is not configured.",
            )
        return cls(secret_key=settings.toss_secret_key)

    def confirm_payment(self, *, payment_key: str, order_code: str, amount: int) -> dict[str, Any]:
        auth_token = base64.b64encode(f"{self.secret_key}:".encode("utf-8")).decode("ascii")
        payload = {
            "paymentKey": payment_key,
            "orderId": order_code,
            "amount": amount,
        }
        try:
            response = requests.post(
                f"{self.api_base_url.rstrip('/')}/v1/payments/confirm",
                json=payload,
                headers={
                    "Authorization": f"Basic {auth_token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TossPaymentsClientError(
                "TOSS_CONFIRM_REQUEST_FAILED",
                "TossPayments confirm request failed.",
            ) from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}

        if response.status_code >= 400:
            raise TossPaymentsClientError(
                str(response_payload.get("code") or "TOSS_CONFIRM_FAILED"),
                str(response_payload.get("message") or "TossPayments confirm failed."),
            )
        if not isinstance(response_payload, dict):
            raise TossPaymentsClientError(
                "TOSS_CONFIRM_INVALID_RESPONSE",
                "TossPayments confirm response is invalid.",
            )
        return response_payload

    def get_payment(self, *, payment_key: str) -> dict[str, Any]:
        auth_token = base64.b64encode(f"{self.secret_key}:".encode("utf-8")).decode("ascii")
        try:
            response = requests.get(
                f"{self.api_base_url.rstrip('/')}/v1/payments/{payment_key}",
                headers={
                    "Authorization": f"Basic {auth_token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TossPaymentsClientError(
                "TOSS_PAYMENT_QUERY_REQUEST_FAILED",
                "TossPayments payment query request failed.",
            ) from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}
        if response.status_code >= 400:
            raise TossPaymentsClientError(
                str(response_payload.get("code") or "TOSS_PAYMENT_QUERY_FAILED"),
                str(response_payload.get("message") or "TossPayments payment query failed."),
            )
        if not isinstance(response_payload, dict):
            raise TossPaymentsClientError(
                "TOSS_PAYMENT_QUERY_INVALID_RESPONSE",
                "TossPayments payment query response is invalid.",
            )
        return response_payload

    def cancel_payment(self, *, payment_key: str, cancel_reason: str) -> dict[str, Any]:
        auth_token = base64.b64encode(f"{self.secret_key}:".encode("utf-8")).decode("ascii")
        try:
            response = requests.post(
                f"{self.api_base_url.rstrip('/')}/v1/payments/{payment_key}/cancel",
                json={"cancelReason": cancel_reason},
                headers={
                    "Authorization": f"Basic {auth_token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TossPaymentsClientError(
                "TOSS_CANCEL_REQUEST_FAILED",
                "TossPayments cancel request failed.",
            ) from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}
        if response.status_code >= 400:
            raise TossPaymentsClientError(
                str(response_payload.get("code") or "TOSS_CANCEL_FAILED"),
                str(response_payload.get("message") or "TossPayments cancel failed."),
            )
        if not isinstance(response_payload, dict):
            raise TossPaymentsClientError(
                "TOSS_CANCEL_INVALID_RESPONSE",
                "TossPayments cancel response is invalid.",
            )
        return response_payload
