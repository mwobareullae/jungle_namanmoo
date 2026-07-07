from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.search import SearchDocument
from app.services.elasticsearch_client import (
    ElasticsearchClientProvider,
    default_elasticsearch_client_provider,
)
from app.services.search_index_builder import DOCUMENT_CODE_PREFIX


PRODUCT_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "product_text": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase"],
                }
            }
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "document_code": {"type": "keyword"},
            "product_db_id": {"type": "long"},
            "product_id": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "product_text"},
            "content": {"type": "text", "analyzer": "product_text"},
            "keywords": {"type": "text", "analyzer": "product_text"},
            "brand_code": {"type": "keyword"},
            "brand_name": {"type": "text", "analyzer": "product_text"},
            "category_code": {"type": "keyword"},
            "category_name": {"type": "text", "analyzer": "product_text"},
            "lowest_price": {"type": "integer"},
        },
    },
}

DEFAULT_INDEX_BATCH_SIZE = 500


class ElasticsearchProductIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class ElasticsearchProductIndexResult:
    scanned: int
    indexed: int
    failed: int
    index_name: str
    alias_name: str
    dry_run: bool
    alias_swapped: bool

    def __str__(self) -> str:
        return (
            "ElasticsearchProductIndexResult("
            f"scanned={self.scanned}, "
            f"indexed={self.indexed}, "
            f"failed={self.failed}, "
            f"index_name='{self.index_name}', "
            f"alias_name='{self.alias_name}', "
            f"dry_run={self.dry_run}, "
            f"alias_swapped={self.alias_swapped}"
            ")"
        )


def build_products_index_name(index_suffix: str | None = None) -> str:
    suffix = index_suffix or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    normalized_suffix = suffix.strip().removeprefix("_")
    return f"{settings.elasticsearch_index_prefix}_products_{normalized_suffix}"


def index_products_to_elasticsearch(
    session: Session,
    *,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_name: str | None = None,
    index_suffix: str | None = None,
    alias_name: str = settings.elasticsearch_products_alias,
    limit: int | None = None,
    batch_size: int = DEFAULT_INDEX_BATCH_SIZE,
    dry_run: bool = False,
    refresh: bool = True,
    swap_alias: bool = True,
    request_timeout_seconds: float = 30.0,
) -> ElasticsearchProductIndexResult:
    resolved_index_name = index_name or build_products_index_name(index_suffix)
    documents = list(_load_product_documents(session, limit=limit))
    if dry_run:
        return ElasticsearchProductIndexResult(
            scanned=len(documents),
            indexed=0,
            failed=0,
            index_name=resolved_index_name,
            alias_name=alias_name,
            dry_run=True,
            alias_swapped=False,
        )

    client = client_provider.get_client()
    if client is None:
        raise ElasticsearchProductIndexError("Elasticsearch client is unavailable.")
    if hasattr(client, "options"):
        client = client.options(request_timeout=request_timeout_seconds)

    try:
        _ensure_products_index(client, resolved_index_name)
        indexed = 0
        failed = 0
        for batch in _chunks(documents, max(1, batch_size)):
            success_count, errors = _bulk_index_documents(
                client,
                resolved_index_name,
                batch,
                request_timeout_seconds=request_timeout_seconds,
            )
            indexed += success_count
            failed += len(errors)
        if refresh:
            client.indices.refresh(index=resolved_index_name)
        alias_swapped = False
        if swap_alias and failed == 0:
            _swap_alias(client, index_name=resolved_index_name, alias_name=alias_name)
            alias_swapped = True
        client_provider.mark_success()
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        raise ElasticsearchProductIndexError(str(exc)) from exc

    return ElasticsearchProductIndexResult(
        scanned=len(documents),
        indexed=indexed,
        failed=failed,
        index_name=resolved_index_name,
        alias_name=alias_name,
        dry_run=False,
        alias_swapped=alias_swapped,
    )


def _load_product_documents(
    session: Session,
    *,
    limit: int | None,
) -> list[dict[str, Any]]:
    lowest_price = func.min(ProductPrice.price)
    statement = (
        select(
            SearchDocument.document_code,
            SearchDocument.product_id.label("product_db_id"),
            SearchDocument.title,
            SearchDocument.content,
            SearchDocument.keywords,
            Product.product_code,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            lowest_price.label("lowest_price"),
        )
        .join(Product, SearchDocument.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            SearchDocument.document_type == "product",
            SearchDocument.document_code.like(f"{DOCUMENT_CODE_PREFIX}%"),
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
        .group_by(
            SearchDocument.document_code,
            SearchDocument.product_id,
            SearchDocument.title,
            SearchDocument.content,
            SearchDocument.keywords,
            Product.product_code,
            Brand.brand_code,
            Brand.name,
            ProductCategory.category_code,
            ProductCategory.name,
        )
        .order_by(SearchDocument.product_id.asc(), SearchDocument.document_code.asc())
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = session.execute(statement).all()
    return [
        {
            "document_code": row.document_code,
            "product_db_id": int(row.product_db_id),
            "product_id": row.product_code,
            "title": row.title,
            "content": row.content,
            "keywords": row.keywords or "",
            "brand_code": row.brand_code,
            "brand_name": row.brand_name,
            "category_code": row.category_code,
            "category_name": row.category_name,
            "lowest_price": int(row.lowest_price),
        }
        for row in rows
    ]


def _ensure_products_index(client: Any, index_name: str) -> None:
    if client.indices.exists(index=index_name):
        return
    client.indices.create(index=index_name, **PRODUCT_INDEX_MAPPING)


def _bulk_index_documents(
    client: Any,
    index_name: str,
    documents: list[dict[str, Any]],
    *,
    request_timeout_seconds: float,
) -> tuple[int, list[Any]]:
    from elasticsearch import helpers

    actions = [
        {
            "_op_type": "index",
            "_index": index_name,
            "_id": document["document_code"],
            "_source": document,
        }
        for document in documents
    ]
    success_count, errors = helpers.bulk(
        client,
        actions,
        raise_on_error=False,
        stats_only=False,
        request_timeout=request_timeout_seconds,
    )
    return int(success_count), list(errors)


def _swap_alias(client: Any, *, index_name: str, alias_name: str) -> None:
    actions: list[dict[str, Any]] = []
    for existing_index in _existing_alias_indices(client, alias_name):
        if existing_index == index_name:
            continue
        actions.append({"remove": {"index": existing_index, "alias": alias_name}})
    actions.append({"add": {"index": index_name, "alias": alias_name}})
    client.indices.update_aliases(actions=actions)


def _existing_alias_indices(client: Any, alias_name: str) -> list[str]:
    try:
        aliases = client.indices.get_alias(name=alias_name)
    except Exception:
        return []
    if not isinstance(aliases, dict):
        aliases = dict(aliases)
    return list(aliases.keys())


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index:index + size] for index in range(0, len(items), size)]
