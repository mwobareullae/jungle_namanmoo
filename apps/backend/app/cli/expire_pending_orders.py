import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.services.payment_expiry_service import ExpirePendingOrdersResult, expire_pending_orders


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
    sys.exit(_exit_code_for(result))


def _exit_code_for(result: ExpirePendingOrdersResult) -> int:
    # 실패한 주문이 있어도 나머지 배치는 정상 커밋되지만(주문별 savepoint 격리), 종료 코드는
    # 실패로 표시해 scripts/run_payment_expiry_scheduler.sh 의 연속 실패 로깅이 이 경우도
    # 잡아내도록 한다. 그렇지 않으면 특정 주문이 매 스윕마다 계속 실패해도 스케줄러 종료 코드는
    # 항상 0이라 아무도 알아채지 못한 채 그 주문만 영원히 방치될 수 있다.
    return 1 if result.failed_count > 0 else 0


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
