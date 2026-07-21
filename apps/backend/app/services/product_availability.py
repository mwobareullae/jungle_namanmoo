from dataclasses import dataclass

from sqlalchemy import case, or_
from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True)
class ProductAvailability:
    sales_status: str
    stock_status: str
    available_quantity: int | None
    in_stock: bool


def build_product_availability(
    *,
    inventory_exists: bool,
    sales_status: str | None,
    stock_quantity: int | None,
    reserved_quantity: int | None,
    safety_stock: int | None,
) -> ProductAvailability:
    if not inventory_exists:
        return ProductAvailability(
            sales_status="UNKNOWN",
            stock_status="UNKNOWN",
            available_quantity=None,
            in_stock=False,
        )

    normalized_sales_status = sales_status or "UNKNOWN"
    available_quantity = max(
        int(stock_quantity or 0)
        - int(reserved_quantity or 0)
        - int(safety_stock or 0),
        0,
    )
    if normalized_sales_status == "HIDDEN":
        stock_status = "HIDDEN"
    elif normalized_sales_status == "SOLD_OUT" or available_quantity <= 0:
        stock_status = "SOLD_OUT"
    elif available_quantity <= 5:
        stock_status = "LOW_STOCK"
    else:
        stock_status = "IN_STOCK"

    return ProductAvailability(
        sales_status=normalized_sales_status,
        stock_status=stock_status,
        available_quantity=available_quantity,
        in_stock=normalized_sales_status == "ON_SALE" and available_quantity > 0,
    )


def build_stock_status_sql_case(
    *,
    inventory_id: ColumnElement,
    sales_status: ColumnElement,
    stock_quantity: ColumnElement,
    reserved_quantity: ColumnElement,
    safety_stock: ColumnElement,
) -> ColumnElement:
    """SQL 집계·필터용 재고 상태 CASE. build_product_availability와 같은 우선순위·기준이다.

    두 곳(Python 값 계산, SQL 집계·필터)이 갈라지지 않도록 이 함수가 유일한 SQL 표현이다.
    """

    raw_available_quantity = stock_quantity - reserved_quantity - safety_stock
    available_quantity = case((raw_available_quantity < 0, 0), else_=raw_available_quantity)
    return case(
        (inventory_id.is_(None), "UNKNOWN"),
        (sales_status == "HIDDEN", "HIDDEN"),
        (or_(sales_status == "SOLD_OUT", available_quantity <= 0), "SOLD_OUT"),
        (available_quantity <= 5, "LOW_STOCK"),
        else_="IN_STOCK",
    )
