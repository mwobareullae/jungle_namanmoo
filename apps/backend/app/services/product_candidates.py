from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Brand,
    Product,
    ProductCategory,
    ProductIngredient,
    ProductPrice,
)
from app.db.models.commerce import Inventory, ProductPopularityMetric, Seller
from app.db.models.review import ProductReviewMetric
from app.db.models.taxonomy import Ingredient, IngredientAlias
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.purchase_conditions import ParsedPurchaseConditions


RECOMMENDATION_FALLBACK_POPULARITY_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ProductCandidate:
    db_product_id: int
    product_id: str
    brand_code: str
    brand: str
    category_code: str
    name: str
    thumbnail_url: str | None
    lowest_price: int


def list_product_candidates(
    session: Session,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    limit: int = 50,
    recommendable_only: bool = True,
) -> list[ProductCandidate]:
    statement, _ = _build_product_candidate_statement(
        purchase_conditions,
        recommendable_only=recommendable_only,
    )

    rows = session.execute(
        statement
        .order_by(Product.id.asc())
        .limit(limit)
    ).all()
    return _rows_to_product_candidates(session, rows)


def list_product_candidates_by_db_ids(
    session: Session,
    purchase_conditions: ParsedPurchaseConditions,
    product_db_ids: list[int],
    *,
    limit: int = 50,
    recommendable_only: bool = True,
) -> list[ProductCandidate]:
    ordered_product_ids = _dedupe_ints(product_db_ids)
    if not ordered_product_ids:
        return []

    statement, _ = _build_product_candidate_statement(
        purchase_conditions,
        recommendable_only=recommendable_only,
    )
    rows = session.execute(statement.where(Product.id.in_(ordered_product_ids))).all()
    candidates_by_db_id = {
        candidate.db_product_id: candidate
        for candidate in _rows_to_product_candidates(session, rows)
    }

    return [
        candidates_by_db_id[product_id]
        for product_id in ordered_product_ids
        if product_id in candidates_by_db_id
    ][:limit]


def list_recommendation_fallback_candidates(
    session: Session,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    avoid_ingredients: list[str],
    limit: int = 50,
) -> list[ProductCandidate]:
    lowest_price = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    availability_rank = case(
        (
            (
                (Inventory.sales_status == "ON_SALE")
                & (
                    Inventory.stock_quantity
                    - Inventory.reserved_quantity
                    - Inventory.safety_stock
                    > 0
                )
            ),
            0,
        ),
        (Inventory.sales_status == "SOLD_OUT", 2),
        else_=1,
    )
    statement = (
        select(
            Product.id,
            Product.product_code,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            Product.product_name,
            lowest_price.c.lowest_price,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .join(lowest_price, lowest_price.c.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(
            ProductPopularityMetric,
            (ProductPopularityMetric.product_id == Product.id)
            & (
                ProductPopularityMetric.window_days
                == RECOMMENDATION_FALLBACK_POPULARITY_WINDOW_DAYS
            ),
        )
        .outerjoin(
            ProductReviewMetric,
            ProductReviewMetric.product_id == Product.id,
        )
        .where(
            Product.is_active.is_(True),
            Product.is_recommendable.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            Seller.status == "ACTIVE",
            or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
        )
    )
    statement = _apply_purchase_condition_filters(
        statement,
        purchase_conditions,
        lowest_price.c.lowest_price,
    )

    avoided_ingredient_ids = _resolve_avoided_ingredient_ids(
        session,
        avoid_ingredients,
    )
    if avoided_ingredient_ids:
        blocked_product = (
            select(ProductIngredient.id)
            .where(
                ProductIngredient.product_id == Product.id,
                ProductIngredient.ingredient_id.in_(avoided_ingredient_ids),
            )
            .exists()
        )
        statement = statement.where(~blocked_product)

    rows = session.execute(
        statement.order_by(
            availability_rank.asc(),
            ProductPopularityMetric.popularity_score.desc().nulls_last(),
            ProductReviewMetric.review_count.desc().nulls_last(),
            Product.product_code.asc(),
        ).limit(max(1, limit))
    ).all()
    return _rows_to_product_candidates_without_thumbnails(rows)


def _build_product_candidate_statement(
    purchase_conditions: ParsedPurchaseConditions,
    *,
    recommendable_only: bool,
):
    lowest_price = func.min(ProductPrice.price)

    statement = (
        select(
            Product.id,
            Product.product_code,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            Product.product_name,
            lowest_price.label("lowest_price"),
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
        .group_by(
            Product.id,
            Product.product_code,
            Brand.brand_code,
            Brand.name,
            ProductCategory.category_code,
            Product.product_name,
        )
    )
    if recommendable_only:
        statement = statement.where(Product.is_recommendable.is_(True))

    if purchase_conditions.categories:
        statement = statement.where(
            ProductCategory.category_code.in_(
                category.category_code for category in purchase_conditions.categories
            )
        )

    if purchase_conditions.brands:
        statement = statement.where(
            Brand.brand_code.in_(brand.brand_code for brand in purchase_conditions.brands)
        )

    if purchase_conditions.price_min is not None:
        statement = statement.having(lowest_price >= purchase_conditions.price_min)
    if purchase_conditions.price_max is not None:
        statement = statement.having(lowest_price <= purchase_conditions.price_max)

    return statement, lowest_price


def _apply_purchase_condition_filters(
    statement,
    purchase_conditions: ParsedPurchaseConditions,
    lowest_price,
):
    if purchase_conditions.categories:
        statement = statement.where(
            ProductCategory.category_code.in_(
                category.category_code for category in purchase_conditions.categories
            )
        )
    if purchase_conditions.brands:
        statement = statement.where(
            Brand.brand_code.in_(
                brand.brand_code for brand in purchase_conditions.brands
            )
        )
    if purchase_conditions.price_min is not None:
        statement = statement.where(lowest_price >= purchase_conditions.price_min)
    if purchase_conditions.price_max is not None:
        statement = statement.where(lowest_price <= purchase_conditions.price_max)
    return statement


def _rows_to_product_candidates(session: Session, rows) -> list[ProductCandidate]:
    thumbnail_storage_keys = load_thumbnail_storage_keys(session, [int(row.id) for row in rows])
    return [
        ProductCandidate(
            db_product_id=int(row.id),
            product_id=row.product_code,
            brand_code=row.brand_code,
            brand=row.brand_name,
            category_code=row.category_code,
            name=row.product_name,
            thumbnail_url=thumbnail_storage_keys.get(int(row.id)),
            lowest_price=int(row.lowest_price),
        )
        for row in rows
    ]


def _rows_to_product_candidates_without_thumbnails(rows) -> list[ProductCandidate]:
    return [
        ProductCandidate(
            db_product_id=int(row.id),
            product_id=row.product_code,
            brand_code=row.brand_code,
            brand=row.brand_name,
            category_code=row.category_code,
            name=row.product_name,
            thumbnail_url=None,
            lowest_price=int(row.lowest_price),
        )
        for row in rows
    ]


def _resolve_avoided_ingredient_ids(
    session: Session,
    avoid_ingredients: list[str],
) -> tuple[int, ...]:
    avoid_terms = {
        _normalize_ingredient_match(value)
        for value in avoid_ingredients
        if _normalize_ingredient_match(value)
    }
    if not avoid_terms:
        return ()

    ingredient_rows = session.execute(
        select(
            Ingredient.id,
            Ingredient.ingredient_code,
            Ingredient.name_ko,
            Ingredient.name_en,
            Ingredient.normalized_name,
        ).where(Ingredient.is_active.is_(True))
    ).all()
    aliases_by_ingredient_id: dict[int, set[str]] = {}
    for ingredient_id, alias, normalized_alias in session.execute(
        select(
            IngredientAlias.ingredient_id,
            IngredientAlias.alias,
            IngredientAlias.normalized_alias,
        )
    ).all():
        aliases_by_ingredient_id.setdefault(int(ingredient_id), set()).update(
            {
                _normalize_ingredient_match(alias),
                _normalize_ingredient_match(normalized_alias),
            }
        )

    matched_ids: list[int] = []
    for row in ingredient_rows:
        ingredient_id = int(row.id)
        values = {
            _normalize_ingredient_match(value)
            for value in (
                row.ingredient_code,
                row.name_ko,
                row.name_en,
                row.normalized_name,
            )
            if value
        }
        values.update(aliases_by_ingredient_id.get(ingredient_id, set()))
        values.discard("")
        if any(
            avoid_term in value or value in avoid_term
            for avoid_term in avoid_terms
            for value in values
        ):
            matched_ids.append(ingredient_id)
    return tuple(matched_ids)


def _normalize_ingredient_match(value: str) -> str:
    return "".join(value.casefold().split())


def _dedupe_ints(values: list[int]) -> list[int]:
    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        int_value = int(value)
        if int_value in seen:
            continue
        seen.add(int_value)
        deduped.append(int_value)
    return deduped
