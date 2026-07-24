from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, ProductPopularityMetric
from app.db.models.review import ProductReviewMetric
from app.schemas.product import PopularProductItem, PopularProductsResponse, ProductPopularityMetrics
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.product_availability import build_product_availability


DEFAULT_POPULAR_WINDOW_DAYS = 7
DEFAULT_POPULAR_LIMIT = 10
MAX_POPULAR_LIMIT = 100


def get_popular_products_response(
    session: Session,
    *,
    window_days: int = DEFAULT_POPULAR_WINDOW_DAYS,
    limit: int = DEFAULT_POPULAR_LIMIT,
    category_code: str | None = None,
    recommendable_only: bool = False,
) -> PopularProductsResponse:
    normalized_window_days = max(0, window_days)
    normalized_limit = max(1, min(MAX_POPULAR_LIMIT, limit))
    items = get_popular_product_items(
        session,
        window_days=normalized_window_days,
        limit=normalized_limit,
        category_code=category_code,
        recommendable_only=recommendable_only,
    )
    return PopularProductsResponse(window_days=normalized_window_days, items=items)


def get_popular_product_items(
    session: Session,
    *,
    window_days: int,
    limit: int,
    category_code: str | None = None,
    recommendable_only: bool = False,
) -> list[PopularProductItem]:
    price_subquery = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )

    statement = (
        select(
            Product.id.label("db_product_id"),
            Product.product_code.label("product_id"),
            Brand.name.label("brand"),
            Product.product_name.label("name"),
            ProductCategory.category_code.label("category_code"),
            ProductCategory.name.label("category_name"),
            price_subquery.c.lowest_price.label("lowest_price"),
            ProductPopularityMetric.view_count,
            ProductPopularityMetric.click_count,
            ProductPopularityMetric.cart_add_count,
            ProductPopularityMetric.order_count,
            ProductPopularityMetric.units_sold,
            ProductPopularityMetric.wishlist_add_count,
            ProductPopularityMetric.checkout_start_count,
            ProductPopularityMetric.paid_order_count,
            ProductPopularityMetric.home_product_impression_count,
            ProductPopularityMetric.home_product_click_count,
            ProductPopularityMetric.search_result_impression_count,
            ProductPopularityMetric.search_result_click_count,
            ProductPopularityMetric.wishlist_remove_count,
            ProductPopularityMetric.cart_remove_count,
            ProductPopularityMetric.cart_quantity_change_count,
            ProductPopularityMetric.payment_failed_count,
            ProductPopularityMetric.order_cancel_count,
            ProductReviewMetric.review_count.label("review_count"),
            ProductReviewMetric.average_rating.label("average_rating"),
            ProductPopularityMetric.popularity_score,
            ProductPopularityMetric.score_version,
            ProductPopularityMetric.computed_at,
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
        )
        .join(Product, ProductPopularityMetric.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(price_subquery, price_subquery.c.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(ProductReviewMetric, ProductReviewMetric.product_id == Product.id)
        .where(
            ProductPopularityMetric.window_days == window_days,
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
        )
        .order_by(
            ProductPopularityMetric.popularity_score.desc(),
            ProductPopularityMetric.order_count.desc(),
            ProductPopularityMetric.units_sold.desc(),
            ProductReviewMetric.review_count.desc().nulls_last(),
            Product.product_code.asc(),
        )
        .limit(limit)
    )
    if recommendable_only:
        statement = statement.where(Product.is_recommendable.is_(True))
    if category_code:
        statement = statement.where(ProductCategory.category_code == category_code)

    rows = session.execute(statement).all()
    db_product_ids = [int(row.db_product_id) for row in rows]
    thumbnail_storage_keys = load_thumbnail_storage_keys(session, db_product_ids)
    purchase_urls = _load_purchase_urls(session, db_product_ids)

    items: list[PopularProductItem] = []
    for row in rows:
        availability = build_product_availability(
            inventory_exists=row.inventory_id is not None,
            sales_status=row.sales_status,
            stock_quantity=row.stock_quantity,
            reserved_quantity=row.reserved_quantity,
            safety_stock=row.safety_stock,
        )
        items.append(PopularProductItem(
            product_id=row.product_id,
            brand=row.brand,
            name=row.name,
            category_code=row.category_code,
            category_name=row.category_name,
            thumbnail_url=thumbnail_storage_keys.get(int(row.db_product_id), ""),
            lowest_price=int(row.lowest_price or 0),
            purchase_url=purchase_urls.get(int(row.db_product_id)),
            popularity_score=float(row.popularity_score),
            score_version=row.score_version,
            computed_at=row.computed_at,
            metrics=ProductPopularityMetrics(
                view_count=int(row.view_count),
                click_count=int(row.click_count),
                cart_add_count=int(row.cart_add_count),
                order_count=int(row.order_count),
                units_sold=int(row.units_sold),
                wishlist_add_count=int(row.wishlist_add_count),
                checkout_start_count=int(row.checkout_start_count),
                paid_order_count=int(row.paid_order_count),
                home_product_impression_count=int(row.home_product_impression_count),
                home_product_click_count=int(row.home_product_click_count),
                search_result_impression_count=int(row.search_result_impression_count),
                search_result_click_count=int(row.search_result_click_count),
                wishlist_remove_count=int(row.wishlist_remove_count),
                cart_remove_count=int(row.cart_remove_count),
                cart_quantity_change_count=int(row.cart_quantity_change_count),
                payment_failed_count=int(row.payment_failed_count),
                order_cancel_count=int(row.order_cancel_count),
                review_count=int(row.review_count or 0),
                average_rating=float(row.average_rating) if row.average_rating is not None else None,
            ),
            sales_status=availability.sales_status,
            stock_status=availability.stock_status,
            available_quantity=availability.available_quantity,
            in_stock=availability.in_stock,
        ))
    return items


def _load_purchase_urls(session: Session, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(ProductPrice.product_id, ProductPrice.product_url)
        .where(ProductPrice.product_id.in_(product_ids))
        .order_by(ProductPrice.product_id.asc(), ProductPrice.is_lowest.desc(), ProductPrice.price.asc())
    ).all()
    urls_by_product_id: dict[int, str] = {}
    for product_id, product_url in rows:
        urls_by_product_id.setdefault(int(product_id), product_url)
    return urls_by_product_id
