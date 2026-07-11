import argparse

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.elasticsearch_catalog_index import reindex_catalog_product_to_elasticsearch


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reindex or remove one general catalog product in Elasticsearch.",
    )
    parser.add_argument("product_id")
    parser.add_argument(
        "--alias-name",
        default=settings.elasticsearch_catalog_products_alias,
    )
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = reindex_catalog_product_to_elasticsearch(
            session,
            product_id=args.product_id,
            index_alias=args.alias_name,
            refresh=args.refresh,
        )
    print(result)


if __name__ == "__main__":
    main()
