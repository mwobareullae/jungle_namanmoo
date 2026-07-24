from app.services.product_availability import build_product_availability


def test_marks_zero_available_quantity_as_sold_out() -> None:
    availability = build_product_availability(
        inventory_exists=True,
        sales_status="ON_SALE",
        stock_quantity=5,
        reserved_quantity=3,
        safety_stock=2,
    )

    assert availability.stock_status == "SOLD_OUT"
    assert availability.available_quantity == 0
    assert availability.in_stock is False


def test_keeps_unknown_inventory_distinct_from_sold_out() -> None:
    availability = build_product_availability(
        inventory_exists=False,
        sales_status=None,
        stock_quantity=None,
        reserved_quantity=None,
        safety_stock=None,
    )

    assert availability.sales_status == "UNKNOWN"
    assert availability.stock_status == "UNKNOWN"
    assert availability.available_quantity is None
    assert availability.in_stock is False


def test_marks_small_available_quantity_as_low_stock_but_purchasable() -> None:
    availability = build_product_availability(
        inventory_exists=True,
        sales_status="ON_SALE",
        stock_quantity=8,
        reserved_quantity=2,
        safety_stock=1,
    )

    assert availability.stock_status == "LOW_STOCK"
    assert availability.available_quantity == 5
    assert availability.in_stock is True
