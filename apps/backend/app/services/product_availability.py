from dataclasses import dataclass


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
