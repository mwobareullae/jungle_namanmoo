from __future__ import annotations

from math import ceil
from typing import Any, Iterable

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, ProductPopularityMetric, Seller
from app.db.models.review import ProductReviewMetric
from app.schemas.product_listing import (
    BrandListItem,
    BrandListResponse,
    CategoryListItem,
    CategoryListResponse,
    ProductListingAppliedFilters,
    ProductListingItem,
    ProductListingPagination,
    ProductListingResponse,
    ProductListingSort,
)
from app.services.catalog_search_text import (
    CATEGORY_CODE_LABELS,
    CATEGORY_GROUP_BY_CODE,
    CATEGORY_GROUP_LABELS,
    category_group_for_code,
)
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.product_availability import build_product_availability


DEFAULT_PRODUCT_LISTING_PAGE = 1
DEFAULT_PRODUCT_LISTING_PAGE_SIZE = 20
MAX_PRODUCT_LISTING_PAGE_SIZE = 100
DEFAULT_BRAND_LIST_PAGE_SIZE = 50
POPULARITY_WINDOW_DAYS = 7


def get_product_listing_response(
    session: Session,
    *,
    page: int = DEFAULT_PRODUCT_LISTING_PAGE,
    page_size: int = DEFAULT_PRODUCT_LISTING_PAGE_SIZE,
    brand_codes: Iterable[str] = (),
    category_codes: Iterable[str] = (),
    category_groups: Iterable[str] = (),
    min_price: int | None = None,
    max_price: int | None = None,
    min_rating: float | None = None,
    in_stock: bool | None = None,
    sort: ProductListingSort = ProductListingSort.POPULAR,
) -> ProductListingResponse:
    normalized_brands = _normalize_values(brand_codes)
    normalized_categories = _normalize_values(category_codes)
    normalized_groups = _normalize_values(category_groups)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("min_price must not be greater than max_price")

    statement = _listing_statement().where(*_listing_eligibility())
    statement = _apply_filters(
        statement,
        brand_codes=normalized_brands,
        category_codes=normalized_categories,
        category_groups=normalized_groups,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        in_stock=in_stock,
    )
    total_items = int(session.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one())
    offset = (page - 1) * page_size
    rows = session.execute(statement.order_by(*_sort_columns(sort, statement)).offset(offset).limit(page_size)).all()
    thumbnail_keys = load_thumbnail_storage_keys(session, [int(row.product_db_id) for row in rows])

    return ProductListingResponse(
        items=[_row_to_item(row, thumbnail_keys) for row in rows],
        pagination=_pagination(page=page, page_size=page_size, total_items=total_items),
        applied_filters=ProductListingAppliedFilters(
            brand_codes=list(normalized_brands),
            category_codes=list(normalized_categories),
            category_groups=list(normalized_groups),
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
            in_stock=in_stock,
        ),
        sort=sort,
    )


def get_categories_response(session: Session) -> CategoryListResponse:
    statement = (
        select(
            ProductCategory.category_code,
            ProductCategory.name,
            func.count(Product.id).label("product_count"),
        )
        .outerjoin(Product, Product.category_id == ProductCategory.id)
        .outerjoin(Brand, Product.brand_id == Brand.id)
        .outerjoin(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(
            ProductCategory.is_active.is_(True),
            or_(Product.id.is_(None), and_(*_listing_eligibility())),
        )
        .group_by(ProductCategory.id, ProductCategory.category_code, ProductCategory.name)
        .order_by(func.count(Product.id).desc(), ProductCategory.name.asc(), ProductCategory.category_code.asc())
    )
    category_rows = {row.category_code: row for row in session.execute(statement).all()}
    known_category_codes = tuple(CATEGORY_CODE_LABELS)
    additional_category_codes = tuple(
        sorted(category_code for category_code in category_rows if category_code not in CATEGORY_CODE_LABELS)
    )

    def to_category_list_item(category_code: str) -> CategoryListItem:
        row = category_rows.get(category_code)
        group = category_group_for_code(category_code)
        return CategoryListItem(
            code=category_code,
            name=CATEGORY_CODE_LABELS.get(category_code, row.name if row is not None else category_code),
            group=group,
            group_name=CATEGORY_GROUP_LABELS.get(group, "기타"),
            product_count=int(row.product_count) if row is not None else 0,
        )

    return CategoryListResponse(
        items=[to_category_list_item(category_code) for category_code in (*known_category_codes, *additional_category_codes)]
    )


def get_brands_response(
    session: Session,
    *,
    page: int,
    page_size: int,
    query: str | None,
) -> BrandListResponse:
    statement = (
        select(Brand.brand_code, Brand.name, func.count(Product.id).label("product_count"))
        .outerjoin(Product, Product.brand_id == Brand.id)
        .outerjoin(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(Brand.is_active.is_(True), or_(Product.id.is_(None), and_(*_listing_eligibility())))
        .group_by(Brand.id, Brand.brand_code, Brand.name)
    )
    normalized_query = (query or "").strip().casefold()
    if normalized_query:
        pattern = f"%{_escape_like(normalized_query)}%"
        statement = statement.where(
            or_(
                func.lower(Brand.brand_code).like(pattern, escape="\\"),
                func.lower(Brand.name).like(pattern, escape="\\"),
            )
        )
    total_items = int(session.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one())
    rows = session.execute(
        statement.order_by(func.count(Product.id).desc(), Brand.name.asc(), Brand.brand_code.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return BrandListResponse(
        items=[BrandListItem(code=row.brand_code, name=row.name, product_count=int(row.product_count)) for row in rows],
        pagination=_pagination(page=page, page_size=page_size, total_items=total_items),
    )


def _listing_statement() -> Any:
    lowest_price = (
        select(ProductPrice.product_id.label("product_id"), func.min(ProductPrice.price).label("lowest_price"))
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    return (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Product.released_at,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            lowest_price.c.lowest_price,
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
            ProductReviewMetric.average_rating,
            ProductReviewMetric.review_count,
            ProductPopularityMetric.popularity_score,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(lowest_price, lowest_price.c.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(
            ProductPopularityMetric,
            (ProductPopularityMetric.product_id == Product.id)
            & (ProductPopularityMetric.window_days == POPULARITY_WINDOW_DAYS),
        )
        .outerjoin(ProductReviewMetric, ProductReviewMetric.product_id == Product.id)
    )


def _listing_eligibility() -> tuple[Any, ...]:
    return (
        Product.is_active.is_(True),
        Brand.is_active.is_(True),
        ProductCategory.is_active.is_(True),
        Seller.status == "ACTIVE",
        or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
    )


def _apply_filters(
    statement: Any,
    *,
    brand_codes: tuple[str, ...],
    category_codes: tuple[str, ...],
    category_groups: tuple[str, ...],
    min_price: int | None,
    max_price: int | None,
    min_rating: float | None,
    in_stock: bool | None,
) -> Any:
    if brand_codes:
        statement = statement.where(Brand.brand_code.in_(brand_codes))
    effective_category_codes = set(category_codes)
    for group in category_groups:
        effective_category_codes.update(code for code, value in CATEGORY_GROUP_BY_CODE.items() if value == group)
    if effective_category_codes:
        statement = statement.where(ProductCategory.category_code.in_(sorted(effective_category_codes)))
    lowest_price = _column(statement, "lowest_price")
    if min_price is not None:
        statement = statement.where(lowest_price >= min_price)
    if max_price is not None:
        statement = statement.where(lowest_price <= max_price)
    if min_rating is not None:
        statement = statement.where(ProductReviewMetric.average_rating >= min_rating)
    if in_stock is True:
        statement = statement.where(_in_stock_condition())
    if in_stock is False:
        statement = statement.where(or_(Inventory.id.is_(None), ~_in_stock_condition()))
    return statement


def _sort_columns(sort: ProductListingSort, statement: Any) -> tuple[Any, ...]:
    stable_id = Product.product_code.asc()
    availability = case(
        (_in_stock_condition(), 0),
        (Inventory.sales_status == "SOLD_OUT", 2),
        else_=1,
    ).asc()
    lowest_price = _column(statement, "lowest_price")
    if sort == ProductListingSort.NEWEST:
        return (availability, func.coalesce(Product.released_at, Product.created_at).desc(), stable_id)
    if sort == ProductListingSort.PRICE_LOW:
        return (availability, lowest_price.asc().nulls_last(), stable_id)
    if sort == ProductListingSort.PRICE_HIGH:
        return (availability, lowest_price.desc().nulls_last(), stable_id)
    if sort == ProductListingSort.RATING:
        return (availability, ProductReviewMetric.average_rating.desc().nulls_last(), ProductReviewMetric.review_count.desc(), stable_id)
    if sort == ProductListingSort.REVIEW_COUNT:
        return (availability, ProductReviewMetric.review_count.desc().nulls_last(), ProductReviewMetric.average_rating.desc().nulls_last(), stable_id)
    return (availability, ProductPopularityMetric.popularity_score.desc().nulls_last(), ProductReviewMetric.review_count.desc().nulls_last(), stable_id)


def _row_to_item(row: Any, thumbnail_keys: dict[int, str]) -> ProductListingItem:
    availability = build_product_availability(
        inventory_exists=row.inventory_id is not None,
        sales_status=row.sales_status,
        stock_quantity=row.stock_quantity,
        reserved_quantity=row.reserved_quantity,
        safety_stock=row.safety_stock,
    )
    return ProductListingItem(
        product_id=row.product_code,
        brand_code=row.brand_code,
        brand=row.brand_name,
        name=row.product_name,
        category_code=row.category_code,
        category_group=category_group_for_code(row.category_code),
        category_name=CATEGORY_CODE_LABELS.get(row.category_code, row.category_name),
        thumbnail_url=thumbnail_keys.get(int(row.product_db_id), ""),
        lowest_price=int(row.lowest_price) if row.lowest_price is not None else None,
        rating=float(row.average_rating) if row.average_rating is not None else None,
        review_count=int(row.review_count or 0),
        sales_status=availability.sales_status,
        in_stock=availability.in_stock,
        stock_status=availability.stock_status,
        available_quantity=availability.available_quantity,
        released_at=row.released_at,
    )


def _row_in_stock(row: Any) -> bool:
    if row.inventory_id is None or row.sales_status != "ON_SALE":
        return False
    return int(row.stock_quantity or 0) - int(row.reserved_quantity or 0) - int(row.safety_stock or 0) > 0


def _in_stock_condition() -> Any:
    return and_(
        Inventory.sales_status == "ON_SALE",
        (Inventory.stock_quantity - Inventory.reserved_quantity - Inventory.safety_stock) > 0,
    )


def _pagination(*, page: int, page_size: int, total_items: int) -> ProductListingPagination:
    total_pages = ceil(total_items / page_size) if total_items else 0
    return ProductListingPagination(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1 and total_pages > 0,
    )


def _normalize_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _column(statement: Any, name: str) -> Any:
    for column in statement.selected_columns:
        if column.key == name:
            return column
    raise KeyError(name)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
