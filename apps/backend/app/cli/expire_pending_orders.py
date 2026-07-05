import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.services.payment_expiry_service import expire_pending_orders


def main() -> None:
    args = _parse_args()
    now = _parse_now(args.now)

    with SessionLocal() as session:
        result = expire_pending_orders(session, now=now, limit=args.limit)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(json.dumps(asdict(result), ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expire pending payment orders and release reserved inventory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of pending orders to expire in one run.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current time, for example 2026-07-05T12:00:00+09:00.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the sweep and print the result without committing changes.",
    )
    return parser.parse_args()


def _parse_now(value: str | None) -> datetime | None:
    if value is None:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    main()
