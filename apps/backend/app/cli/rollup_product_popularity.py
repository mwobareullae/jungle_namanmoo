import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.services.product_popularity_rollup import rollup_product_popularity_metrics


def main() -> None:
    args = _parse_args()
    computed_at = _parse_computed_at(args.computed_at)

    with SessionLocal() as session:
        result = rollup_product_popularity_metrics(
            session,
            window_days=args.window_days,
            computed_at=computed_at,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = asdict(result)
    payload["computed_at"] = result.computed_at.isoformat()
    print(json.dumps(payload, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Roll up event/order behavior logs into product popularity metrics.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Rolling popularity window in days. Use 0 for all-time aggregation.",
    )
    parser.add_argument(
        "--computed-at",
        default=None,
        help="Override rollup time, for example 2026-07-06T12:00:00+09:00.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the rollup and print the result without committing changes.",
    )
    return parser.parse_args()


def _parse_computed_at(value: str | None) -> datetime | None:
    if value is None:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    main()
