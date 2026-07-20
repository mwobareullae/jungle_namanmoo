"""관리자 운영 대시보드 집계 서비스 (P1-M5, 조회 전용)."""

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductImage
from app.db.models.commerce import Inventory
from app.schemas.admin.dashboard import (
    AdminDashboardProductStats,
    AdminDashboardStockStatusBreakdown,
    AdminDashboardSummaryResponse,
)
from app.services.admin.ingredient_mapping_service import get_ingredient_mapping_summary
from app.services.admin.order_service import get_admin_order_summary


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

    raw_available_quantity = (
        Inventory.stock_quantity - Inventory.reserved_quantity - Inventory.safety_stock
    )
    available_quantity = case((raw_available_quantity < 0, 0), else_=raw_available_quantity)
    stock_status = case(
        (Inventory.id.is_(None), "UNKNOWN"),
        (Inventory.sales_status == "HIDDEN", "HIDDEN"),
        (or_(Inventory.sales_status == "SOLD_OUT", available_quantity <= 0), "SOLD_OUT"),
        (available_quantity <= 5, "LOW_STOCK"),
        else_="IN_STOCK",
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
    )
