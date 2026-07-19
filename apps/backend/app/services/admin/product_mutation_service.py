"""관리자 상품 등록·수정 서비스 (P1-M3-A, Chunk 4).

성분·재고 수량·판매 상태·추천 가능 여부는 이 서비스에서 변경하지 않는다.
호출자는 서비스가 flush 한 뒤 commit/rollback을 책임진다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.schemas.admin.product import (
    AdminProductCreateRequest,
    AdminProductDetail,
    AdminProductUpdateRequest,
)
from app.schemas.common import ApiError
from app.services.admin.product_service import get_admin_product_detail
from app.services.product_pricing import (
    MAX_PRODUCT_PRICE,
    build_product_url,
    get_or_create_first_party_price_for_update,
)
from app.services.product_thumbnail import (
    normalize_thumbnail_storage_key,
    set_product_thumbnail,
)


FIRST_PARTY_SELLER_CODE = "mwobareullae"
PRODUCT_CODE_PREFIX = "prod_mwbl_"
PRODUCT_CODE_RETRY_LIMIT = 3
MAX_DESCRIPTION_LENGTH = 10_000
# 프론트 getStaticAssetUrl/getProductImageUrl(imageUrls.ts)의 absoluteUrlPattern과 동일 정의.
# storage_key는 CDN 버킷 내 상대 경로여야 한다 — 완성 URL을 그대로 받으면 프론트가
# CDN_BASE + "/resized/w400/" + storage_key 로 조합할 때 깨지고, product-image-response-contract.md
# 가 금지한 원본(예: 올리브영) URL 노출로 이어질 수 있다.




def create_admin_product(
    session: Session,
    request: AdminProductCreateRequest,
    *,
    now: datetime | None = None,
) -> AdminProductDetail:
    """비활성 상품과 HIDDEN/0 기본 재고, 자사몰 가격 1행을 함께 만든다."""

    timestamp = now or datetime.now(timezone.utc)
    seller = _load_first_party_seller(session)
    brand = _load_active_brand(session, request.brand_code)
    category = _load_active_category(session, request.category_code)
    name = _normalize_required_text(request.name, "name", max_length=512)
    price = _normalize_price(request.price)
    description = _normalize_description(request.description)
    thumbnail_storage_key = normalize_thumbnail_storage_key(request.thumbnail_storage_key)

    product = _insert_product_with_code_retry(
        session,
        seller=seller,
        brand=brand,
        category=category,
        name=name,
        description=description,
        released_at=request.released_at,
        timestamp=timestamp,
    )
    session.add(
        Inventory(
            product_id=product.id,
            stock_quantity=0,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="HIDDEN",
            inventory_source="ADMIN",
            updated_at=timestamp,
        )
    )
    session.add(
        ProductPrice(
            product_id=product.id,
            mall_name=seller.display_name,
            price=price,
            currency="KRW",
            product_url=build_product_url(product.product_code),
            is_lowest=True,
            collected_at=timestamp,
        )
    )
    if thumbnail_storage_key is not None:
        # 신규 상품이라 이 product_id 로는 아직 어떤 product_images 행도 없다 — 충돌 가능성 없이
        # 신규 상품도 수정·대량 연결 경로와 같은 공용 헬퍼로 동기화한다.
        set_product_thumbnail(session, product, thumbnail_storage_key)
    session.flush()
    return get_admin_product_detail(session, product.product_code)


def update_admin_product(
    session: Session,
    product_code: str,
    request: AdminProductUpdateRequest,
    *,
    now: datetime | None = None,
) -> AdminProductDetail:
    """명시된 기본정보만 수정하고 판매·재고 책임은 M4에 남겨둔다."""

    fields = request.model_fields_set
    if not fields:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", "At least one product field is required.")

    timestamp = now or datetime.now(timezone.utc)
    product = session.execute(
        select(Product).where(Product.product_code == product_code).with_for_update()
    ).scalar_one_or_none()
    if product is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")

    seller = _load_first_party_seller(session)
    if product.seller_id != seller.id:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")

    if "name" in fields:
        product.product_name = _normalize_required_text(request.name, "name", max_length=512)
    if "brand_code" in fields:
        product.brand_id = _load_active_brand(session, request.brand_code).id
    if "category_code" in fields:
        product.category_id = _load_active_category(session, request.category_code).id
    if "description" in fields:
        product.description = _normalize_description(request.description)
    if "released_at" in fields:
        product.released_at = request.released_at
    if "is_active" in fields:
        if request.is_active is None:
            raise ApiError(400, "INVALID_PRODUCT_FIELD", "is_active cannot be null.")
        if request.is_active:
            inventory = session.execute(
                select(Inventory).where(Inventory.product_id == product.id).with_for_update()
            ).scalar_one_or_none()
            if inventory is None or inventory.sales_status == "HIDDEN":
                raise ApiError(
                    409,
                    "PRODUCT_NOT_READY_FOR_ACTIVATION",
                    "판매 준비가 끝나지 않은 상품은 공개할 수 없습니다.",
                )
        product.is_active = request.is_active

    if "price" in fields:
        price = _normalize_price(request.price)
        price_row, _ = get_or_create_first_party_price_for_update(
            session,
            product=product,
            mall_name=seller.display_name,
            price=price,
            timestamp=timestamp,
        )
        price_row.price = price
        price_row.currency = "KRW"
        price_row.is_lowest = True
        price_row.product_url = build_product_url(product.product_code)
        price_row.collected_at = timestamp

    thumbnail_changed = False
    if "thumbnail_storage_key" in fields:
        thumbnail_changed = set_product_thumbnail(
            session, product, normalize_thumbnail_storage_key(request.thumbnail_storage_key)
        )

    if fields != {"thumbnail_storage_key"} or thumbnail_changed:
        product.updated_at = timestamp
    session.flush()
    return get_admin_product_detail(session, product.product_code)


def _insert_product_with_code_retry(
    session: Session,
    *,
    seller: Seller,
    brand: Brand,
    category: ProductCategory,
    name: str,
    description: str | None,
    released_at: datetime | None,
    timestamp: datetime,
    import_sku: str | None = None,
) -> Product:
    for _ in range(PRODUCT_CODE_RETRY_LIMIT):
        product = Product(
            product_code=_generate_product_code(),
            import_sku=import_sku,
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name=name,
            description=description,
            is_active=False,
            is_recommendable=False,
            released_at=released_at,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            # 코드 UNIQUE 충돌만 savepoint에서 롤백해 다른 후보로 재시도한다.
            with session.begin_nested():
                session.add(product)
                session.flush()
            return product
        except IntegrityError as exc:
            if not _is_product_code_conflict(exc):
                raise

    raise ApiError(409, "PRODUCT_CODE_CONFLICT", "상품 코드를 생성하지 못했습니다.")


def _load_first_party_seller(session: Session) -> Seller:
    seller = session.execute(
        select(Seller).where(Seller.seller_code == FIRST_PARTY_SELLER_CODE)
    ).scalar_one_or_none()
    if seller is None:
        raise ApiError(409, "SELLER_NOT_FOUND", "자사 셀러를 찾을 수 없습니다.")
    if seller.status != "ACTIVE":
        raise ApiError(409, "SELLER_INACTIVE", "자사 셀러가 비활성 상태입니다.")
    return seller


def _load_active_brand(session: Session, brand_code: str | None) -> Brand:
    normalized = _normalize_required_text(brand_code, "brand_code", max_length=64)
    brand = session.execute(select(Brand).where(Brand.brand_code == normalized)).scalar_one_or_none()
    if brand is None:
        raise ApiError(400, "BRAND_NOT_FOUND", "브랜드를 찾을 수 없습니다.")
    if not brand.is_active:
        raise ApiError(409, "BRAND_INACTIVE", "비활성 브랜드는 선택할 수 없습니다.")
    return brand


def _load_active_category(session: Session, category_code: str | None) -> ProductCategory:
    normalized = _normalize_required_text(category_code, "category_code", max_length=64)
    category = session.execute(
        select(ProductCategory).where(ProductCategory.category_code == normalized)
    ).scalar_one_or_none()
    if category is None:
        raise ApiError(400, "CATEGORY_NOT_FOUND", "카테고리를 찾을 수 없습니다.")
    if not category.is_active:
        raise ApiError(409, "CATEGORY_INACTIVE", "비활성 카테고리는 선택할 수 없습니다.")
    return category


def _normalize_required_text(value: str | None, field_name: str, *, max_length: int) -> str:
    normalized = value.strip() if value is not None else ""
    if not normalized or len(normalized) > max_length:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", f"Invalid {field_name}.")
    return normalized


def _normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > MAX_DESCRIPTION_LENGTH:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", "Invalid description.")
    return normalized or None


def _normalize_price(value: int | None) -> int:
    if value is None or value <= 0 or value > MAX_PRODUCT_PRICE:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", "price must be between 1 and 100,000,000.")
    return value


def _generate_product_code() -> str:
    return f"{PRODUCT_CODE_PREFIX}{uuid4().hex[:16]}"




def _is_product_code_conflict(exc: IntegrityError) -> bool:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name in {"products_product_code_key", "uq_products_product_code"}:
        return True
    return "products.product_code" in str(exc.orig).lower()
