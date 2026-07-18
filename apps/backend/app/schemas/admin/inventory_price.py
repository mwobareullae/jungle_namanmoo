"""관리자 재고·가격 조회 스키마 (P1-M4, Chunk 1).

재고 상태 계산은 ``product_availability.build_product_availability``의 출력과
동일한 값을 반환한다. ``movement_type``은 안정적인 저장 코드를 그대로 내보내며,
화면용 한글 라벨은 프론트가 담당한다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.admin.product import AdminProductAvailability


class AdminInventoryPriceListItem(BaseModel):
    product_code: str
    name: str
    brand_code: str
    brand: str
    category_code: str
    category_name: str
    is_active: bool
    price: int | None = Field(..., description="자사 운영몰 KRW 가격. 행이 없으면 None")
    stock_quantity: int | None = Field(..., description="재고 행이 없으면 None")
    reserved_quantity: int | None = Field(..., description="재고 행이 없으면 None")
    safety_stock: int | None = Field(..., description="재고 행이 없으면 None. M4에서는 조회만 허용")
    availability: AdminProductAvailability
    updated_at: datetime


class AdminInventoryPriceListResponse(BaseModel):
    items: list[AdminInventoryPriceListItem]
    next_cursor: str | None


class AdminInventoryMovementItem(BaseModel):
    movement_type: str = Field(..., description="InventoryMovement 저장 코드. 프론트가 한글 라벨로 변환")
    quantity_delta: int
    stock_after: int
    reason: str | None
    reference_type: str | None
    reference_id: str | None
    created_at: datetime


class AdminInventoryHistoryResponse(BaseModel):
    product_code: str
    items: list[AdminInventoryMovementItem]


class AdminInventoryAdjustmentRequest(BaseModel):
    """절대 재고 수량을 설정하는 단건 관리자 조정 요청."""

    model_config = ConfigDict(extra="forbid")

    # 서비스가 trim·상한을 함께 검증해 API 오류 코드를 일관되게 반환한다.
    stock_quantity: int = Field(description="0 이상 1,000,000 이하의 절대 재고 수량")
    reason: str = Field(description="trim 후 1~500자의 필수 재고 조정 사유")


class AdminInventoryAdjustmentResponse(BaseModel):
    changed: bool = Field(description="기존 재고와 달라 실제 변경·이력이 생성됐는지 여부")
    product_code: str
    stock_quantity: int
    reserved_quantity: int
    safety_stock: int
    availability: AdminProductAvailability
    updated_at: datetime
    movement: AdminInventoryMovementItem | None = Field(
        ..., description="changed=true일 때 생성된 ADMIN_ADJUST 이력, no-op이면 None"
    )


class AdminInventoryPriceUpdateRequest(BaseModel):
    """자사 운영몰 절대 가격을 설정하는 단건 관리자 요청."""

    model_config = ConfigDict(extra="forbid")

    price: int = Field(description="1 이상 100,000,000 이하의 KRW 절대 가격")


class AdminInventoryPriceUpdateResponse(BaseModel):
    changed: bool = Field(description="가격 행을 새로 만들었거나 실제 가격을 바꿨는지 여부")
    product_code: str
    price: int
    currency: str
    is_lowest: bool
    collected_at: datetime
    updated_at: datetime = Field(description="실제 변경 시 갱신된 Product.updated_at")


class AdminProductSaleStartResponse(BaseModel):
    """HIDDEN 상품을 판매 가능한 상태로 전환한 결과."""

    product_code: str
    sales_status: str = Field(description="판매 시작 성공 시 ON_SALE")
    is_active: bool = Field(description="판매 시작 성공 시 true")
    started_at: datetime
