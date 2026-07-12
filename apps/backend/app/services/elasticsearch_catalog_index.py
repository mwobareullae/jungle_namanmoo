from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.catalog import (
    Brand,
    BrandAlias,
    Product,
    ProductCategory,
    ProductCategoryAlias,
    ProductIngredient,
    ProductPrice,
)
from app.db.models.commerce import Inventory, ProductPopularityMetric, Seller
from app.db.models.review import ProductReviewMetric
from app.db.models.taxonomy import (
    Effect,
    EffectAlias,
    Ingredient,
    IngredientAlias,
    IngredientEffect,
)
from app.services.catalog_search_text import (
    category_group_for_code,
    compact_search_text,
    extract_chosung,
    normalize_search_text,
)
from app.services.catalog_search_aliases import equivalent_brand_values
from app.services.catalog_search_filters import (
    feature_codes_for_effect_codes,
    skin_type_codes_for_tags,
)
from app.services.elasticsearch_client import (
    ElasticsearchClientProvider,
    default_elasticsearch_client_provider,
)


CATALOG_PRODUCT_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "normalizer": {
                "catalog_keyword": {
                    "type": "custom",
                    "filter": ["lowercase", "asciifolding"],
                }
            },
            "tokenizer": {
                "catalog_nori_tokenizer": {
                    "type": "nori_tokenizer",
                    "decompound_mode": "mixed",
                    "discard_punctuation": True,
                },
                "catalog_edge_tokenizer": {
                    "type": "edge_ngram",
                    "min_gram": 1,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                },
            },
            "analyzer": {
                "catalog_nori": {
                    "type": "custom",
                    "tokenizer": "catalog_nori_tokenizer",
                    "filter": ["lowercase"],
                },
                "catalog_edge": {
                    "type": "custom",
                    "tokenizer": "catalog_edge_tokenizer",
                    "filter": ["lowercase"],
                },
                "catalog_keyword_search": {
                    "type": "custom",
                    "tokenizer": "keyword",
                    "filter": ["lowercase"],
                },
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "product_db_id": {"type": "long"},
            "product_id": {"type": "keyword"},
            "product_name": {
                "type": "text",
                "analyzer": "catalog_nori",
                "search_analyzer": "catalog_nori",
                "fields": {
                    "exact": {"type": "keyword", "normalizer": "catalog_keyword"},
                    "edge": {
                        "type": "text",
                        "analyzer": "catalog_edge",
                        "search_analyzer": "catalog_keyword_search",
                    },
                },
            },
            "product_name_normalized": {"type": "keyword", "normalizer": "catalog_keyword"},
            "product_name_compact": {"type": "keyword", "normalizer": "catalog_keyword"},
            "product_name_chosung": {
                "type": "text",
                "analyzer": "catalog_edge",
                "search_analyzer": "catalog_keyword_search",
            },
            "brand_code": {"type": "keyword"},
            "brand_name": {
                "type": "text",
                "analyzer": "catalog_nori",
                "fields": {
                    "exact": {"type": "keyword", "normalizer": "catalog_keyword"},
                    "edge": {
                        "type": "text",
                        "analyzer": "catalog_edge",
                        "search_analyzer": "catalog_keyword_search",
                    },
                },
            },
            "brand_name_compact": {"type": "keyword", "normalizer": "catalog_keyword"},
            "brand_name_chosung": {
                "type": "text",
                "analyzer": "catalog_edge",
                "search_analyzer": "catalog_keyword_search",
            },
            "brand_aliases": {
                "type": "text",
                "analyzer": "catalog_nori",
                "fields": {
                    "edge": {
                        "type": "text",
                        "analyzer": "catalog_edge",
                        "search_analyzer": "catalog_keyword_search",
                    }
                },
            },
            "category_code": {"type": "keyword"},
            "category_group": {"type": "keyword"},
            "category_name": {
                "type": "text",
                "analyzer": "catalog_nori",
                "fields": {
                    "exact": {"type": "keyword", "normalizer": "catalog_keyword"}
                },
            },
            "category_aliases": {
                "type": "text",
                "analyzer": "catalog_nori",
                "fields": {
                    "edge": {
                        "type": "text",
                        "analyzer": "catalog_edge",
                        "search_analyzer": "catalog_keyword_search",
                    }
                },
            },
            "ingredient_names": {"type": "text", "analyzer": "catalog_nori"},
            "ingredient_aliases": {"type": "text", "analyzer": "catalog_nori"},
            "effect_names": {"type": "text", "analyzer": "catalog_nori"},
            "effect_aliases": {"type": "text", "analyzer": "catalog_nori"},
            "feature_codes": {"type": "keyword"},
            "skin_type_codes": {"type": "keyword"},
            "aliases": {"type": "text", "analyzer": "catalog_nori"},
            "aliases_compact": {"type": "keyword", "normalizer": "catalog_keyword"},
            "aliases_chosung": {
                "type": "text",
                "analyzer": "catalog_edge",
                "search_analyzer": "catalog_keyword_search",
            },
            "all_text": {
                "type": "text",
                "analyzer": "catalog_nori",
                "fields": {
                    "edge": {
                        "type": "text",
                        "analyzer": "catalog_edge",
                        "search_analyzer": "catalog_keyword_search",
                    }
                },
            },
            "lowest_price": {"type": "integer"},
            "rating": {"type": "float"},
            "review_count": {"type": "integer"},
            "popularity_score": {"type": "float"},
            "sales_status": {"type": "keyword"},
            "available_quantity": {"type": "integer"},
            "in_stock": {"type": "boolean"},
            "is_recommendable": {"type": "boolean"},
            "thumbnail_url": {"type": "keyword", "index": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    },
}

DEFAULT_CATALOG_INDEX_BATCH_SIZE = 500
DEFAULT_POPULARITY_WINDOW_DAYS = 7
DEFAULT_RETAIN_PREVIOUS_INDICES = 2


class ElasticsearchCatalogIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class ElasticsearchCatalogIndexResult:
    expected: int
    scanned: int
    indexed: int
    failed: int
    indexed_document_count: int
    duplicate_or_missing_count: int
    missing_representative_product_ids: tuple[str, ...]
    index_name: str
    alias_name: str
    dry_run: bool
    validation_passed: bool
    alias_swapped: bool
    deleted_indices: tuple[str, ...]

    def __str__(self) -> str:
        return (
            "ElasticsearchCatalogIndexResult("
            f"expected={self.expected}, scanned={self.scanned}, indexed={self.indexed}, "
            f"failed={self.failed}, indexed_document_count={self.indexed_document_count}, "
            f"duplicate_or_missing_count={self.duplicate_or_missing_count}, "
            f"missing_representative_product_ids={self.missing_representative_product_ids}, "
            f"index_name='{self.index_name}', alias_name='{self.alias_name}', "
            f"dry_run={self.dry_run}, validation_passed={self.validation_passed}, "
            f"alias_swapped={self.alias_swapped}, deleted_indices={self.deleted_indices}"
            ")"
        )


@dataclass(frozen=True)
class ElasticsearchCatalogProductSyncResult:
    product_id: str
    action: str
    index_alias: str



def build_catalog_products_index_name(index_suffix: str | None = None) -> str:
    suffix = index_suffix or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    normalized_suffix = suffix.strip().removeprefix("_")
    return f"{settings.elasticsearch_index_prefix}_catalog_products_{normalized_suffix}"


def count_catalog_search_products(session: Session) -> int:
    statement = (
        select(func.count(Product.id))
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(*_catalog_product_eligibility())
    )
    return int(session.execute(statement).scalar_one())


def iter_catalog_product_document_batches(
    session: Session,
    *,
    batch_size: int = DEFAULT_CATALOG_INDEX_BATCH_SIZE,
    limit: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    normalized_batch_size = max(1, batch_size)
    remaining = max(0, limit) if limit is not None else None
    last_product_db_id = 0

    while remaining is None or remaining > 0:
        requested_size = normalized_batch_size if remaining is None else min(normalized_batch_size, remaining)
        base_rows = _load_base_product_rows(
            session,
            after_product_db_id=last_product_db_id,
            limit=requested_size,
        )
        if not base_rows:
            break

        product_db_ids = [int(row.product_db_id) for row in base_rows]
        context = _load_batch_context(session, base_rows, product_db_ids)
        documents = [_build_catalog_document(row, context) for row in base_rows]
        yield documents

        last_product_db_id = int(base_rows[-1].product_db_id)
        if remaining is not None:
            remaining -= len(base_rows)


def index_catalog_products_to_elasticsearch(
    session: Session,
    *,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_name: str | None = None,
    index_suffix: str | None = None,
    alias_name: str = settings.elasticsearch_catalog_products_alias,
    limit: int | None = None,
    batch_size: int = DEFAULT_CATALOG_INDEX_BATCH_SIZE,
    dry_run: bool = False,
    swap_alias: bool = True,
    cleanup_old_indices: bool = True,
    retain_previous_indices: int = DEFAULT_RETAIN_PREVIOUS_INDICES,
    request_timeout_seconds: float = 30.0,
) -> ElasticsearchCatalogIndexResult:
    resolved_index_name = index_name or build_catalog_products_index_name(index_suffix)
    total_expected = count_catalog_search_products(session)
    expected = min(total_expected, max(0, limit)) if limit is not None else total_expected
    if dry_run:
        return ElasticsearchCatalogIndexResult(
            expected=expected,
            scanned=0,
            indexed=0,
            failed=0,
            indexed_document_count=0,
            duplicate_or_missing_count=0,
            missing_representative_product_ids=(),
            index_name=resolved_index_name,
            alias_name=alias_name,
            dry_run=True,
            validation_passed=True,
            alias_swapped=False,
            deleted_indices=(),
        )

    client = client_provider.get_client()
    if client is None:
        raise ElasticsearchCatalogIndexError("Elasticsearch client is unavailable.")
    if hasattr(client, "options"):
        client = client.options(request_timeout=request_timeout_seconds)

    scanned = 0
    indexed = 0
    failed = 0
    representative_product_ids: list[str] = []
    try:
        _create_catalog_index(client, resolved_index_name)
        for documents in iter_catalog_product_document_batches(
            session,
            batch_size=batch_size,
            limit=limit,
        ):
            scanned += len(documents)
            for document in documents:
                product_id = str(document["product_id"])
                if product_id not in representative_product_ids and len(representative_product_ids) < 3:
                    representative_product_ids.append(product_id)
            success_count, errors = _bulk_index_documents(
                client,
                resolved_index_name,
                documents,
                request_timeout_seconds=request_timeout_seconds,
            )
            indexed += success_count
            failed += len(errors)

        client.indices.refresh(index=resolved_index_name)
        indexed_document_count = _index_document_count(client, resolved_index_name)
        missing_representative_product_ids = tuple(
            _missing_product_documents(client, resolved_index_name, representative_product_ids)
        )
        duplicate_or_missing_count = abs(indexed_document_count - indexed)
        validation_passed = (
            failed == 0
            and scanned == expected
            and indexed == expected
            and indexed_document_count == expected
            and duplicate_or_missing_count == 0
            and not missing_representative_product_ids
        )

        alias_swapped = False
        deleted_indices: tuple[str, ...] = ()
        if swap_alias and validation_passed:
            _swap_alias(client, index_name=resolved_index_name, alias_name=alias_name)
            alias_swapped = True
            if cleanup_old_indices:
                deleted_indices = tuple(
                    _cleanup_catalog_indices(
                        client,
                        current_index_name=resolved_index_name,
                        retain_previous_indices=max(0, retain_previous_indices),
                    )
                )
        client_provider.mark_success()
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        raise ElasticsearchCatalogIndexError(str(exc)) from exc

    return ElasticsearchCatalogIndexResult(
        expected=expected,
        scanned=scanned,
        indexed=indexed,
        failed=failed,
        indexed_document_count=indexed_document_count,
        duplicate_or_missing_count=duplicate_or_missing_count,
        missing_representative_product_ids=missing_representative_product_ids,
        index_name=resolved_index_name,
        alias_name=alias_name,
        dry_run=False,
        validation_passed=validation_passed,
        alias_swapped=alias_swapped,
        deleted_indices=deleted_indices,
    )


def rollback_catalog_products_alias(
    *,
    target_index_name: str,
    alias_name: str = settings.elasticsearch_catalog_products_alias,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
) -> None:
    expected_prefix = f"{settings.elasticsearch_index_prefix}_catalog_products_"
    if not target_index_name.startswith(expected_prefix):
        raise ElasticsearchCatalogIndexError("Rollback target is not a catalog product index.")
    client = client_provider.get_client()
    if client is None:
        raise ElasticsearchCatalogIndexError("Elasticsearch client is unavailable.")
    if not client.indices.exists(index=target_index_name):
        raise ElasticsearchCatalogIndexError(f"Rollback target does not exist: {target_index_name}")
    _swap_alias(client, index_name=target_index_name, alias_name=alias_name)


def reindex_catalog_product_to_elasticsearch(
    session: Session,
    *,
    product_id: str,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_alias: str = settings.elasticsearch_catalog_products_alias,
    refresh: bool = False,
) -> ElasticsearchCatalogProductSyncResult:
    normalized_product_id = product_id.strip()
    if not normalized_product_id:
        raise ElasticsearchCatalogIndexError("product_id is required.")
    client = client_provider.get_client()
    if client is None:
        raise ElasticsearchCatalogIndexError("Elasticsearch client is unavailable.")

    try:
        row = session.execute(
            _base_product_row_statement().where(
                Product.product_code == normalized_product_id,
                *_catalog_product_eligibility(),
            )
        ).first()
        if row is None:
            _delete_catalog_product_document(
                client,
                index_alias=index_alias,
                product_id=normalized_product_id,
                refresh=refresh,
            )
            action = "DELETED_OR_MISSING"
        else:
            product_db_id = int(row.product_db_id)
            context = _load_batch_context(session, [row], [product_db_id])
            document = _build_catalog_document(row, context)
            client.index(
                index=index_alias,
                id=normalized_product_id,
                document=document,
                refresh="wait_for" if refresh else False,
            )
            action = "INDEXED"
        client_provider.mark_success()
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        raise ElasticsearchCatalogIndexError(str(exc)) from exc

    return ElasticsearchCatalogProductSyncResult(
        product_id=normalized_product_id,
        action=action,
        index_alias=index_alias,
    )


def _catalog_product_eligibility() -> tuple[Any, ...]:
    return (
        Product.is_active.is_(True),
        Brand.is_active.is_(True),
        ProductCategory.is_active.is_(True),
        Seller.status == "ACTIVE",
        or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
    )


def _load_base_product_rows(
    session: Session,
    *,
    after_product_db_id: int,
    limit: int,
) -> list[Any]:
    statement = (
        _base_product_row_statement()
        .where(Product.id > after_product_db_id, *_catalog_product_eligibility())
        .order_by(Product.id.asc())
        .limit(limit)
    )
    return list(session.execute(statement).all())


def _base_product_row_statement() -> Any:
    return (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Product.skin_type_tags,
            Product.thumbnail_url,
            Product.is_recommendable,
            Product.created_at,
            Product.updated_at,
            Brand.id.label("brand_db_id"),
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.id.label("category_db_id"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
    )


@dataclass(frozen=True)
class _BatchContext:
    prices: dict[int, int]
    popularity: dict[int, float]
    reviews: dict[int, tuple[float | None, int]]
    brand_aliases: dict[int, tuple[str, ...]]
    category_aliases: dict[int, tuple[str, ...]]
    ingredient_names: dict[int, tuple[str, ...]]
    ingredient_aliases: dict[int, tuple[str, ...]]
    effect_names: dict[int, tuple[str, ...]]
    effect_aliases: dict[int, tuple[str, ...]]
    effect_codes: dict[int, tuple[str, ...]]


def _load_batch_context(
    session: Session,
    base_rows: Sequence[Any],
    product_db_ids: list[int],
) -> _BatchContext:
    brand_db_ids = sorted({int(row.brand_db_id) for row in base_rows})
    category_db_ids = sorted({int(row.category_db_id) for row in base_rows})
    prices = {
        int(product_id): int(lowest_price)
        for product_id, lowest_price in session.execute(
            select(ProductPrice.product_id, func.min(ProductPrice.price))
            .where(ProductPrice.product_id.in_(product_db_ids))
            .group_by(ProductPrice.product_id)
        ).all()
    }
    popularity = {
        int(row.product_id): float(row.popularity_score)
        for row in session.execute(
            select(ProductPopularityMetric).where(
                ProductPopularityMetric.product_id.in_(product_db_ids),
                ProductPopularityMetric.window_days == DEFAULT_POPULARITY_WINDOW_DAYS,
            )
        ).scalars()
    }
    reviews = {
        int(row.product_id): (
            float(row.average_rating) if row.average_rating is not None else None,
            int(row.review_count),
        )
        for row in session.execute(
            select(ProductReviewMetric).where(
                ProductReviewMetric.product_id.in_(product_db_ids)
            )
        ).scalars()
    }
    brand_aliases = _alias_values_by_owner(
        session.execute(
            select(BrandAlias.brand_id, BrandAlias.alias).where(BrandAlias.brand_id.in_(brand_db_ids))
        ).all()
    )
    category_aliases = _alias_values_by_owner(
        session.execute(
            select(ProductCategoryAlias.category_id, ProductCategoryAlias.alias).where(
                ProductCategoryAlias.category_id.in_(category_db_ids)
            )
        ).all()
    )
    ingredient_rows = session.execute(
        select(
            ProductIngredient.product_id,
            Ingredient.id.label("ingredient_db_id"),
            Ingredient.name_ko,
            Ingredient.name_en,
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .where(
            ProductIngredient.product_id.in_(product_db_ids),
            Ingredient.is_active.is_(True),
        )
    ).all()
    ingredient_db_ids = sorted({int(row.ingredient_db_id) for row in ingredient_rows})
    ingredient_alias_values = _alias_values_by_owner(
        session.execute(
            select(IngredientAlias.ingredient_id, IngredientAlias.alias).where(
                IngredientAlias.ingredient_id.in_(ingredient_db_ids)
            )
        ).all()
        if ingredient_db_ids
        else []
    )
    ingredient_names_by_product: dict[int, set[str]] = defaultdict(set)
    ingredient_aliases_by_product: dict[int, set[str]] = defaultdict(set)
    for row in ingredient_rows:
        product_id = int(row.product_id)
        ingredient_id = int(row.ingredient_db_id)
        ingredient_names_by_product[product_id].add(row.name_ko)
        if row.name_en:
            ingredient_names_by_product[product_id].add(row.name_en)
        ingredient_aliases_by_product[product_id].update(ingredient_alias_values.get(ingredient_id, ()))

    effect_rows = session.execute(
        select(
            ProductIngredient.product_id,
            Effect.id.label("effect_db_id"),
            Effect.effect_code,
            Effect.name,
        )
        .join(IngredientEffect, ProductIngredient.ingredient_id == IngredientEffect.ingredient_id)
        .join(Effect, IngredientEffect.effect_id == Effect.id)
        .where(
            ProductIngredient.product_id.in_(product_db_ids),
            Effect.is_active.is_(True),
        )
    ).all()
    effect_db_ids = sorted({int(row.effect_db_id) for row in effect_rows})
    effect_alias_values = _alias_values_by_owner(
        session.execute(
            select(EffectAlias.effect_id, EffectAlias.alias).where(EffectAlias.effect_id.in_(effect_db_ids))
        ).all()
        if effect_db_ids
        else []
    )
    effect_names_by_product: dict[int, set[str]] = defaultdict(set)
    effect_aliases_by_product: dict[int, set[str]] = defaultdict(set)
    effect_codes_by_product: dict[int, set[str]] = defaultdict(set)
    for row in effect_rows:
        product_id = int(row.product_id)
        effect_id = int(row.effect_db_id)
        effect_names_by_product[product_id].add(row.name)
        effect_aliases_by_product[product_id].update(effect_alias_values.get(effect_id, ()))
        effect_codes_by_product[product_id].add(row.effect_code)

    return _BatchContext(
        prices=prices,
        popularity=popularity,
        reviews=reviews,
        brand_aliases=brand_aliases,
        category_aliases=category_aliases,
        ingredient_names=_freeze_values(ingredient_names_by_product),
        ingredient_aliases=_freeze_values(ingredient_aliases_by_product),
        effect_names=_freeze_values(effect_names_by_product),
        effect_aliases=_freeze_values(effect_aliases_by_product),
        effect_codes=_freeze_values(effect_codes_by_product),
    )


def _build_catalog_document(row: Any, context: _BatchContext) -> dict[str, Any]:
    product_db_id = int(row.product_db_id)
    brand_aliases = tuple(
        sorted(
            set(
                (
                    *context.brand_aliases.get(int(row.brand_db_id), ()),
                    *equivalent_brand_values(row.brand_name),
                    *equivalent_brand_values(row.brand_code),
                )
            )
        )
    )
    category_aliases = context.category_aliases.get(int(row.category_db_id), ())
    ingredient_names = context.ingredient_names.get(product_db_id, ())
    ingredient_aliases = context.ingredient_aliases.get(product_db_id, ())
    effect_names = context.effect_names.get(product_db_id, ())
    effect_aliases = context.effect_aliases.get(product_db_id, ())
    effect_codes = context.effect_codes.get(product_db_id, ())
    skin_type_tags = _split_skin_type_tags(row.skin_type_tags)
    aliases = tuple(sorted(set((*brand_aliases, *category_aliases, *ingredient_aliases, *effect_aliases))))
    rating, review_count = context.reviews.get(product_db_id, (None, 0))
    popularity_score = context.popularity.get(product_db_id, 0.0)
    if row.inventory_id is None:
        available_quantity = None
        sales_status = "UNKNOWN"
    else:
        available_quantity = max(
            int(row.stock_quantity or 0) - int(row.reserved_quantity or 0) - int(row.safety_stock or 0),
            0,
        )
        sales_status = row.sales_status or "UNKNOWN"
    in_stock = sales_status == "ON_SALE" and available_quantity is not None and available_quantity > 0
    all_text_values = (
        row.product_name,
        row.brand_name,
        row.category_name,
        *brand_aliases,
        *category_aliases,
        *ingredient_names,
        *ingredient_aliases,
        *effect_names,
        *effect_aliases,
    )
    return {
        "product_db_id": product_db_id,
        "product_id": row.product_code,
        "product_name": row.product_name,
        "product_name_normalized": normalize_search_text(row.product_name),
        "product_name_compact": compact_search_text(row.product_name),
        "product_name_chosung": extract_chosung(row.product_name),
        "brand_code": row.brand_code,
        "brand_name": row.brand_name,
        "brand_name_compact": compact_search_text(row.brand_name),
        "brand_name_chosung": extract_chosung(row.brand_name),
        "brand_aliases": list(brand_aliases),
        "category_code": row.category_code,
        "category_group": category_group_for_code(row.category_code),
        "category_name": row.category_name,
        "category_aliases": list(category_aliases),
        "ingredient_names": list(ingredient_names),
        "ingredient_aliases": list(ingredient_aliases),
        "effect_names": list(effect_names),
        "effect_aliases": list(effect_aliases),
        "feature_codes": list(feature_codes_for_effect_codes(effect_codes)),
        "skin_type_codes": list(skin_type_codes_for_tags(skin_type_tags)),
        "aliases": list(aliases),
        "aliases_compact": [compact_search_text(alias) for alias in aliases],
        "aliases_chosung": [extract_chosung(alias) for alias in aliases],
        "all_text": " ".join(str(value) for value in all_text_values if value),
        "lowest_price": context.prices.get(product_db_id),
        "rating": rating,
        "review_count": review_count,
        "popularity_score": popularity_score,
        "sales_status": sales_status,
        "available_quantity": available_quantity,
        "in_stock": in_stock,
        "is_recommendable": bool(row.is_recommendable),
        "thumbnail_url": row.thumbnail_url,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _alias_values_by_owner(rows: Sequence[Any]) -> dict[int, tuple[str, ...]]:
    values: dict[int, set[str]] = defaultdict(set)
    for owner_id, alias in rows:
        if alias:
            values[int(owner_id)].add(str(alias))
    return _freeze_values(values)


def _freeze_values(values: dict[int, set[str]]) -> dict[int, tuple[str, ...]]:
    return {owner_id: tuple(sorted(owner_values)) for owner_id, owner_values in values.items()}


def _split_skin_type_tags(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(tag.strip() for tag in value.replace(",", ";").split(";") if tag.strip())


def _create_catalog_index(client: Any, index_name: str) -> None:
    if client.indices.exists(index=index_name):
        raise ElasticsearchCatalogIndexError(f"Catalog index already exists: {index_name}")
    client.indices.create(index=index_name, **CATALOG_PRODUCT_INDEX_MAPPING)


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
            "_id": document["product_id"],
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


def _delete_catalog_product_document(
    client: Any,
    *,
    index_alias: str,
    product_id: str,
    refresh: bool,
) -> None:
    try:
        client.delete(
            index=index_alias,
            id=product_id,
            refresh="wait_for" if refresh else False,
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            status_code = getattr(getattr(exc, "meta", None), "status", None)
        if status_code != 404:
            raise


def _index_document_count(client: Any, index_name: str) -> int:
    response = client.count(index=index_name)
    if not isinstance(response, dict):
        response = dict(response)
    return int(response.get("count", 0))


def _missing_product_documents(client: Any, index_name: str, product_ids: list[str]) -> list[str]:
    if not product_ids:
        return []
    response = client.mget(index=index_name, ids=product_ids, source=False)
    if not isinstance(response, dict):
        response = dict(response)
    found_ids = {
        str(document.get("_id"))
        for document in response.get("docs", [])
        if document.get("found")
    }
    return [product_id for product_id in product_ids if product_id not in found_ids]


def _swap_alias(client: Any, *, index_name: str, alias_name: str) -> None:
    actions: list[dict[str, Any]] = []
    for existing_index in _existing_alias_indices(client, alias_name):
        if existing_index != index_name:
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


def _cleanup_catalog_indices(
    client: Any,
    *,
    current_index_name: str,
    retain_previous_indices: int,
) -> list[str]:
    pattern = f"{settings.elasticsearch_index_prefix}_catalog_products_*"
    try:
        response = client.indices.get(index=pattern, allow_no_indices=True)
    except Exception:
        return []
    if not isinstance(response, dict):
        response = dict(response)
    index_names = sorted(response.keys(), reverse=True)
    previous_indices = [name for name in index_names if name != current_index_name]
    keep = {current_index_name, *previous_indices[:retain_previous_indices]}
    deleted: list[str] = []
    for index_name in index_names:
        if index_name in keep:
            continue
        client.indices.delete(index=index_name)
        deleted.append(index_name)
    return deleted
