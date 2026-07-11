import argparse
import json
from dataclasses import asdict

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.review_importer import (
    DEFAULT_REVIEW_IMPORT_BATCH_SIZE,
    ReviewImportError,
    import_product_reviews,
)


def main() -> None:
    args = _parse_args()
    if not args.dry_run and not args.full and args.limit is None:
        raise SystemExit("Choose --full or provide --limit for a non-dry-run import.")

    try:
        with SessionLocal() as session:
            result = import_product_reviews(
                session,
                data_dir=args.data_dir,
                file_paths=args.files,
                limit=None if args.full else args.limit,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    except ReviewImportError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(asdict(result), ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import storefront product review CSV files into normalized review tables.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--full", action="store_true", help="Import every selected review row.")
    scope.add_argument("--limit", type=int, default=None, help="Import at most this many rows.")
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=None,
        help="Review CSV path relative to DATA_DIR, or an absolute path. Repeatable.",
    )
    parser.add_argument("--data-dir", default=settings.data_dir)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_REVIEW_IMPORT_BATCH_SIZE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and classify rows without changing persistent review tables.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
