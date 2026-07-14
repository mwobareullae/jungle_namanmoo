"""관리자 상품 조회·등록·수정 스키마 (P1-M3-A).

신규 테이블 없이 기존 products/brands/product_categories/product_prices/
inventories/product_images 에서 파생한다. 성분·검수/색인 상태(reviewStatus/
indexStatus)는 실 데이터 출처가 없어 응답에 포함하지 않는다(계약 §2).
판매·재고 상태는 product_availability.build_product_availability 로 계산해
docs/api/product-card-availability-contract.md 와 정합을 맞춘다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# 판매·재고 상태 값은 product_availability.build_product_availability 출력과 정합. 계약 고정.
AdminSalesStatus = Literal["ON_SALE", "SOLD_OUT", "HIDDEN", "UNKNOWN"]
AdminStockStatus = Literal["IN_STOCK", "LOW_STOCK", "SOLD_OUT", "HIDDEN", "UNKNOWN"]


class AdminProductAvailability(BaseModel):
    sales_status: AdminSalesStatus = Field(..., description="Inventory.sales_status, 재고 행 없으면 UNKNOWN")
    stock_status: AdminStockStatus = Field(..., description="가용 재고로 계산")
    available_quantity: int | None = Field(..., description="max(stock-reserved-safety,0), 재고 없으면 None")
    in_stock: bool


class AdminProductListItem(BaseModel):
    product_code: str
    name: str = Field(..., description="products.product_name")
    brand_code: str
    brand: str = Field(..., description="brands.name")
    category_code: str
    category_name: str
    price: int | None = Field(..., description="자사몰 product_prices.price(상품당 1행). 없으면 None")
    is_active: bool = Field(..., description="고객 노출 여부(products.is_active)")
    is_recommendable: bool
    availability: AdminProductAvailability
    stock_quantity: int | None = Field(..., description="재고 수량(참고용). 재고 행 없으면 None")
    image_count: int
    thumbnail_url: str = Field(
        ...,
        description="대표 이미지 storage_key(product_images 기준, thumbnail 우선). 없으면 ''. 프론트가 CDN URL로 조합.",
    )
    updated_at: datetime


class AdminProductPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class AdminProductListResponse(BaseModel):
    items: list[AdminProductListItem]
    pagination: AdminProductPagination


class AdminProductDetail(AdminProductListItem):
    # thumbnail_url(대표 storage_key)은 AdminProductListItem 에서 상속. 이미지 목록 전체가
    # 필요해지면 별도 필드로 확장(계약 §9: 대표 storage_key까지가 M3-A 범위).
    seller_code: str
    seller_name: str = Field(..., description="Seller.display_name")
    description: str | None
    released_at: datetime | None
    created_at: datetime


class AdminProductCreateRequest(BaseModel):
    """관리자 상품 등록 요청.

    product_code·seller·판매/재고 상태·추천 가능 여부·product_url은 서버가
    계약값으로 생성한다. 성분과 재고 수량은 M3-A 요청에 포함하지 않는다.
    """

    name: str
    brand_code: str
    category_code: str
    price: int
    description: str | None = None
    released_at: datetime | None = None


class AdminProductUpdateRequest(BaseModel):
    """관리자 상품 기본정보 부분 수정 요청.

    sales_status·재고 수량·추천 가능 여부는 다른 운영 단계의 책임이므로 받지
    않는다. 명시적으로 전달한 필드만 변경한다.
    """

    name: str | None = None
    brand_code: str | None = None
    category_code: str | None = None
    price: int | None = None
    description: str | None = None
    released_at: datetime | None = None
    is_active: bool | None = None
