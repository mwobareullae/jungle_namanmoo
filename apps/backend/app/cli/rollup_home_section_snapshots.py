import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.home_section_snapshot_rollup import rollup_home_section_snapshots


def main() -> None:
    args = _parse_args()
    with SessionLocal() as session:
        result = rollup_home_section_snapshots(session)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = asdict(result)
    payload["computed_at"] = result.computed_at.isoformat()
    payload["dry_run"] = args.dry_run
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize evidence and guest skin-type home section snapshots.",
    )
    parser.add_argument("--full", action="store_true", help="Required for explicit full home snapshot rollup.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.full:
        parser.error("--full is required")
    return args


if __name__ == "__main__":
    main()
