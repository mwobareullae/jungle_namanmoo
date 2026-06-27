from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.services.purchase_conditions import ParsedPurchaseConditions


@dataclass(frozen=True)
class ProductCandidate:
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
    lowest_price = func.min(ProductPrice.price)

    statement = (
        select(
            Product.product_code,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            Product.product_name,
            Product.thumbnail_url,
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
            Product.thumbnail_url,
        )
        .order_by(Product.id.asc())
        .limit(limit)
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

    rows = session.execute(statement).all()
    return [
        ProductCandidate(
            product_id=row.product_code,
            brand_code=row.brand_code,
            brand=row.brand_name,
            category_code=row.category_code,
            name=row.product_name,
            thumbnail_url=row.thumbnail_url,
            lowest_price=int(row.lowest_price),
        )
        for row in rows
    ]
