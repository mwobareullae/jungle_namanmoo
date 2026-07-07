import argparse

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.elasticsearch_product_index import (
    DEFAULT_INDEX_BATCH_SIZE,
    index_products_to_elasticsearch,
)


def main() -> None:
    args = _parse_args()
    with SessionLocal() as session:
        result = index_products_to_elasticsearch(
            session,
            index_name=args.index_name,
            index_suffix=args.index_suffix,
            alias_name=args.alias_name,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            refresh=not args.no_refresh,
            swap_alias=not args.no_alias_swap,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    print(result)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index product join search_documents into Elasticsearch.",
    )
    parser.add_argument("--index-name", default=None, help="Exact Elasticsearch index name.")
    parser.add_argument("--index-suffix", default=None, help="Suffix for generated versioned index name.")
    parser.add_argument(
        "--alias-name",
        default=settings.elasticsearch_products_alias,
        help="Alias to swap after a successful index run.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum product documents to index.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_INDEX_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Only count documents that would be indexed.")
    parser.add_argument("--no-refresh", action="store_true", help="Skip index refresh after bulk indexing.")
    parser.add_argument("--no-alias-swap", action="store_true", help="Do not point the search alias at the new index.")
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30.0,
        help="Elasticsearch request timeout for index creation and bulk indexing.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
