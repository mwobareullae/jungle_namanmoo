"""관리자 운영 대시보드 집계 서비스 (P1-M5, 조회 전용)."""

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductImage
from app.db.models.commerce import Inventory, OrderClaim
from app.schemas.admin.dashboard import (
    AdminDashboardClaimSummary,
    AdminDashboardProductStats,
    AdminDashboardStockStatusBreakdown,
    AdminDashboardSummaryResponse,
)
from app.services.admin.ingredient_mapping_service import get_ingredient_mapping_summary
from app.services.admin.order_claim_service import CLAIM_STATUS_REQUESTED
from app.services.admin.order_service import get_admin_order_summary
from app.services.product_availability import build_stock_status_sql_case


_STOCK_STATUSES = ("IN_STOCK", "LOW_STOCK", "SOLD_OUT", "HIDDEN", "UNKNOWN")


def get_admin_dashboard_summary(session: Session) -> AdminDashboardSummaryResponse:
    """기존 운영 데이터의 현재 상태를 한 번에 읽어 대시보드에 제공한다.

    재고 상태 CASE는 ``build_product_availability``와 같은 우선순위다. DB 집계에는
    SQL 식이 필요하므로 M4 목록 서비스와 동일하게 그 규칙을 SQL로 표현한다.
    """

    total_count, recommendable_count = session.execute(
        select(
            func.count(Product.id),
            func.count(Product.id).filter(Product.is_recommendable.is_(True)),
        )
    ).one()

    has_image = exists(select(ProductImage.id).where(ProductImage.product_id == Product.id))
    image_missing_count = session.execute(
        select(func.count(Product.id)).where(~has_image)
    ).scalar_one()

    stock_status = build_stock_status_sql_case(
        inventory_id=Inventory.id,
        sales_status=Inventory.sales_status,
        stock_quantity=Inventory.stock_quantity,
        reserved_quantity=Inventory.reserved_quantity,
        safety_stock=Inventory.safety_stock,
    ).label("stock_status")
    stock_rows = session.execute(
        select(stock_status, func.count(Product.id))
        .select_from(Product)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .group_by(stock_status)
    ).all()
    stock_counts = {status: 0 for status in _STOCK_STATUSES}
    for status, count in stock_rows:
        stock_counts[str(status)] = int(count)

    claim_pending_count = session.execute(
        select(func.count(OrderClaim.id)).where(OrderClaim.status == CLAIM_STATUS_REQUESTED)
    ).scalar_one()

    return AdminDashboardSummaryResponse(
        order_summary=get_admin_order_summary(session),
        ingredient_review_summary=get_ingredient_mapping_summary(session),
        product_stats=AdminDashboardProductStats(
            total_count=int(total_count),
            recommendable_count=int(recommendable_count),
            image_missing_count=int(image_missing_count),
        ),
        stock_status_breakdown=AdminDashboardStockStatusBreakdown(
            in_stock_count=stock_counts["IN_STOCK"],
            low_stock_count=stock_counts["LOW_STOCK"],
            sold_out_count=stock_counts["SOLD_OUT"],
            hidden_count=stock_counts["HIDDEN"],
            unknown_count=stock_counts["UNKNOWN"],
        ),
        claim_summary=AdminDashboardClaimSummary(pending_count=int(claim_pending_count)),
    )
