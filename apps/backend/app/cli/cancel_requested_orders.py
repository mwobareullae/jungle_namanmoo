import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.payment_cancel_service import TossPaymentCancelClient, cancel_requested_orders
from app.services.toss_payments_client import TossPaymentsClient, TossPaymentsClientError


class _UnavailableTossCancelClient:
    def cancel_payment(self, *, payment_key: str, cancel_reason: str) -> dict:
        raise TossPaymentsClientError(
            "TOSS_SECRET_KEY_MISSING",
            "TossPayments secret key is not configured.",
        )


def main() -> None:
    args = _parse_args()
    try:
        toss_client: TossPaymentCancelClient = TossPaymentsClient.from_settings()
    except TossPaymentsClientError:
        toss_client = _UnavailableTossCancelClient()
    with SessionLocal() as session:
        result = cancel_requested_orders(
            session,
            toss_client=toss_client,
            limit=args.limit,
            cancel_reason=args.reason,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(json.dumps(asdict(result), ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process full cancellation for requested orders.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--reason", default="customer requested cancellation")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
