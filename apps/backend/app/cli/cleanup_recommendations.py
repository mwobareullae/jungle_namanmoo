import argparse
from dataclasses import asdict
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.services.recommendation_run_store import cleanup_expired_recommendation_runs


def main() -> None:
    args = _parse_args()
    now = _parse_now(args.now)

    with SessionLocal() as session:
        result = cleanup_expired_recommendation_runs(
            session,
            now=now,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(_format_result(result))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete expired recommendation runs and their child rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows that would be deleted without committing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of recommendation_runs to delete.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current time for tests, for example 2026-06-29T04:00:00+09:00.",
    )
    return parser.parse_args()


def _parse_now(value: str | None) -> datetime | None:
    if value is None:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_result(result: object) -> str:
    values = asdict(result)
    values["cutoff"] = values["cutoff"].isoformat()
    return f"CleanupRecommendationRunsResult({values})"


if __name__ == "__main__":
    main()
