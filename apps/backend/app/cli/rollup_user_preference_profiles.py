import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.user_preference_profile_rollup import (
    rollup_user_preference_profiles,
)


def main() -> None:
    args = _parse_args()
    user_ids = None if args.full else tuple(args.user_id or ())
    with SessionLocal() as session:
        result = rollup_user_preference_profiles(
            session,
            user_ids=user_ids,
            batch_size=args.batch_size,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = asdict(result)
    payload["computed_at"] = result.computed_at.isoformat()
    payload["dry_run"] = args.dry_run
    print(json.dumps(payload, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Roll up user behavior into reusable preference profiles.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--full", action="store_true", help="Roll up every user.")
    target.add_argument(
        "--user-id",
        action="append",
        type=int,
        help="Roll up one user database ID. Repeat for multiple users.",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
