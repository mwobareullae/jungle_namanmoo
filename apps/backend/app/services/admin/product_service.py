"""관리자 상품 조회 서비스 (P1-M3-A, 조회 전용).

고객 product_listing_service 는 `_listing_eligibility()`(is_active·비HIDDEN 등)로
판매 가능한 상품만 노출한다. 관리자는 비활성·숨김·검수 대상까지 전부 봐야 하므로
그 eligibility 필터를 적용하지 않는 별도 쿼리를 쓴다. 판매·재고 상태 계산만
공통 build_product_availability 로 재사용해 가용성 계약과 정합을 맞춘다.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.schemas.admin.product import (
    AdminProductAvailability,
    AdminProductDetail,
    AdminProductListItem,
    AdminProductListResponse,
    AdminProductPagination,
)
from app.schemas.common import ApiError
from app.services.product_availability import build_product_availability
from app.services.product_image_service import load_thumbnail_storage_keys


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _base_statement() -> Any:
    # 자사몰 가격은 상품당 1행이지만, 방어적으로 min 을 써서 상품당 단일 행을 보장한다.
    lowest_price = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    image_count = (
        select(
            ProductImage.product_id.label("product_id"),
            func.count(ProductImage.id).label("image_count"),
        )
        .group_by(ProductImage.product_id)
        .subquery()
    )
    return (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Product.is_active,
            Product.is_recommendable,
            Product.description,
            Product.released_at,
            Product.created_at,
            Product.updated_at,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            Seller.seller_code,
            Seller.display_name.label("seller_name"),
            lowest_price.c.price.label("price"),
            Inventory.id.label("inventory_id"),
            Inventory.sales_status,
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            func.coalesce(image_count.c.image_count, 0).label("image_count"),
        )
        # brand/category/seller 는 NOT NULL FK 라 inner join
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(lowest_price, lowest_price.c.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(image_count, image_count.c.product_id == Product.id)
    )


def _apply_filters(
    statement: Any,
    *,
    query: str | None,
    brand_code: str | None,
    category_code: str | None,
    is_active: bool | None,
    sales_status: str | None,
) -> Any:
    if query and query.strip():
        statement = statement.where(Product.product_name.ilike(f"%{query.strip()}%"))
    if brand_code:
        statement = statement.where(Brand.brand_code == brand_code)
    if category_code:
        statement = statement.where(ProductCategory.category_code == category_code)
    if is_active is not None:
        statement = statement.where(Product.is_active.is_(is_active))
    if sales_status == "UNKNOWN":
        # UNKNOWN 은 Inventory.sales_status 값이 아니라 "재고 행 자체가 없는" 상품이다
        # (CheckConstraint 상 sales_status 는 ON_SALE/SOLD_OUT/HIDDEN 만 존재).
        statement = statement.where(Inventory.id.is_(None))
    elif sales_status:
        statement = statement.where(Inventory.sales_status == sales_status)
    return statement


def list_admin_products(
    session: Session,
    *,
    query: str | None = None,
    brand_code: str | None = None,
    category_code: str | None = None,
    is_active: bool | None = None,
    sales_status: str | None = None,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> AdminProductListResponse:
    normalized_page = page if page >= 1 else DEFAULT_PAGE
    normalized_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    filtered = _apply_filters(
        _base_statement(),
        query=query,
        brand_code=brand_code,
        category_code=category_code,
        is_active=is_active,
        sales_status=sales_status,
    )

    total_items = session.execute(
        select(func.count()).select_from(filtered.subquery())
    ).scalar_one()

    rows = session.execute(
        filtered.order_by(Product.updated_at.desc(), Product.id.desc())
        .limit(normalized_page_size)
        .offset((normalized_page - 1) * normalized_page_size)
    ).all()

    thumbnails = load_thumbnail_storage_keys(session, [row.product_db_id for row in rows])

    total_pages = max((total_items + normalized_page_size - 1) // normalized_page_size, 1)
    return AdminProductListResponse(
        items=[_to_list_item(row, thumbnails.get(row.product_db_id, "")) for row in rows],
        pagination=AdminProductPagination(
            page=normalized_page,
            page_size=normalized_page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=normalized_page < total_pages,
            has_prev=normalized_page > 1,
        ),
    )


def get_admin_product_detail(session: Session, product_code: str) -> AdminProductDetail:
    row = session.execute(
        _base_statement().where(Product.product_code == product_code)
    ).first()
    if row is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")
    thumbnail = load_thumbnail_storage_keys(session, [row.product_db_id]).get(row.product_db_id, "")
    return AdminProductDetail(
        **_list_item_fields(row, thumbnail),
        seller_code=row.seller_code,
        seller_name=row.seller_name,
        description=row.description,
        released_at=row.released_at,
        created_at=row.created_at,
    )


def _availability(row: Any) -> AdminProductAvailability:
    result = build_product_availability(
        inventory_exists=row.inventory_id is not None,
        sales_status=row.sales_status,
        stock_quantity=row.stock_quantity,
        reserved_quantity=row.reserved_quantity,
        safety_stock=row.safety_stock,
    )
    return AdminProductAvailability(
        sales_status=result.sales_status,
        stock_status=result.stock_status,
        available_quantity=result.available_quantity,
        in_stock=result.in_stock,
    )


def _list_item_fields(row: Any, thumbnail_storage_key: str) -> dict[str, Any]:
    return {
        "product_code": row.product_code,
        "name": row.product_name,
        "brand_code": row.brand_code,
        "brand": row.brand_name,
        "category_code": row.category_code,
        "category_name": row.category_name,
        "price": row.price,
        "is_active": row.is_active,
        "is_recommendable": row.is_recommendable,
        "availability": _availability(row),
        "stock_quantity": row.stock_quantity,
        "image_count": row.image_count,
        "thumbnail_url": thumbnail_storage_key,
        "updated_at": row.updated_at,
    }


def _to_list_item(row: Any, thumbnail_storage_key: str) -> AdminProductListItem:
    return AdminProductListItem(**_list_item_fields(row, thumbnail_storage_key))
