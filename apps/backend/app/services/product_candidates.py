from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.purchase_conditions import ParsedPurchaseConditions


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
) -> list[ProductCandidate]:
    statement, _ = _build_product_candidate_statement(purchase_conditions)

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
) -> list[ProductCandidate]:
    ordered_product_ids = _dedupe_ints(product_db_ids)
    if not ordered_product_ids:
        return []

    statement, _ = _build_product_candidate_statement(purchase_conditions)
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


def _build_product_candidate_statement(
    purchase_conditions: ParsedPurchaseConditions,
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
