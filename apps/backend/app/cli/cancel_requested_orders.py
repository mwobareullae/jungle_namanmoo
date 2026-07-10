import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.payment_cancel_service import cancel_requested_orders
from app.services.toss_payments_client import TossPaymentsClient


def main() -> None:
    args = _parse_args()
    with SessionLocal() as session:
        result = cancel_requested_orders(
            session,
            toss_client=TossPaymentsClient.from_settings(),
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
