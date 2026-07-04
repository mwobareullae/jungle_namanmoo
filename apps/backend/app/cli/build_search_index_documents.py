import argparse

from app.db.session import SessionLocal
from app.services.search_index_builder import DEFAULT_BATCH_SIZE, build_product_search_index_documents


def main() -> None:
    args = _parse_args()
    with SessionLocal() as session:
        result = build_product_search_index_documents(
            session,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(result)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build product join documents for search_documents.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum active products to scan.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Only count documents that would change.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
