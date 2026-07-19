"""관리자 운영 대시보드 집계 응답 스키마 (P1-M5, 조회 전용)."""

from pydantic import BaseModel

from app.schemas.admin.ingredient_mapping import IngredientMappingSummary
from app.schemas.admin.order import AdminOrderSummary


class AdminDashboardProductStats(BaseModel):
    total_count: int
    recommendable_count: int
    image_missing_count: int


class AdminDashboardStockStatusBreakdown(BaseModel):
    in_stock_count: int
    low_stock_count: int
    sold_out_count: int
    hidden_count: int
    unknown_count: int


class AdminDashboardClaimSummary(BaseModel):
    pending_count: int


class AdminDashboardSummaryResponse(BaseModel):
    """기존 운영 데이터만 묶은 단일 대시보드 응답.

    ``order_summary``와 ``ingredient_review_summary``는 각각 기존 관리자 API의
    summary 스키마를 그대로 재사용한다. 대시보드가 새로운 상태 의미를 만들지 않는다.
    """

    order_summary: AdminOrderSummary
    ingredient_review_summary: IngredientMappingSummary
    product_stats: AdminDashboardProductStats
    stock_status_breakdown: AdminDashboardStockStatusBreakdown
    claim_summary: AdminDashboardClaimSummary
