import argparse

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.elasticsearch_catalog_index import (
    DEFAULT_CATALOG_INDEX_BATCH_SIZE,
    DEFAULT_RETAIN_PREVIOUS_INDICES,
    index_catalog_products_to_elasticsearch,
    rollback_catalog_products_alias,
)


def main() -> None:
    args = _parse_args()
    if args.rollback_to:
        rollback_catalog_products_alias(
            target_index_name=args.rollback_to,
            alias_name=args.alias_name,
        )
        print(f"alias '{args.alias_name}' rolled back to '{args.rollback_to}'")
        return

    if not args.dry_run and not args.full and args.limit is None:
        raise SystemExit("Choose --full or provide --limit for a non-dry-run index operation.")

    with SessionLocal() as session:
        result = index_catalog_products_to_elasticsearch(
            session,
            index_name=args.index_name,
            index_suffix=args.index_suffix,
            alias_name=args.alias_name,
            limit=None if args.full else args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            swap_alias=not args.no_alias_swap,
            cleanup_old_indices=not args.no_cleanup,
            retain_previous_indices=args.retain_previous_indices,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    print(result)
    if not result.validation_passed:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and atomically publish the general catalog product Elasticsearch index.",
    )
    parser.add_argument("--full", action="store_true", help="Index the full eligible catalog.")
    parser.add_argument("--limit", type=int, default=None, help="Index at most this many products.")
    parser.add_argument("--index-name", default=None, help="Exact versioned index name.")
    parser.add_argument("--index-suffix", default=None, help="Suffix for a generated index name.")
    parser.add_argument(
        "--alias-name",
        default=settings.elasticsearch_catalog_products_alias,
        help="Catalog search alias to publish or roll back.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_CATALOG_INDEX_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Count eligible products only.")
    parser.add_argument("--no-alias-swap", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument(
        "--retain-previous-indices",
        type=int,
        default=DEFAULT_RETAIN_PREVIOUS_INDICES,
    )
    parser.add_argument("--rollback-to", default=None, help="Point the alias at a prior catalog index.")
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
