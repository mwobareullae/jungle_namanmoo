"""관리자 상품 조회 응답 스키마 (P1-M3-A, 조회 전용).

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
