# Product Detail Purchase Info API

## Purpose

`GET /api/products/{product_id}` returns product detail data plus a small commerce summary in
`purchase_info`.

This field is for product detail, recommendation detail, cart handoff preparation, and frontend
purchase button state. It does not replace cart/order transaction checks.

## Response Field

`purchase_info` is additive. Existing fields such as `product`, `images`, `prices`, `ingredients`,
`evidence`, and `sources` remain unchanged.

```json
{
  "purchase_info": {
    "seller_code": "mwobareullae",
    "seller_name": "뭐바를래",
    "seller_type": "FIRST_PARTY",
    "price": 19900,
    "currency": "KRW",
    "purchase_url": "https://example.com/products/prod_001",
    "can_purchase": true,
    "sales_status": "ON_SALE",
    "stock_status": "LOW_STOCK",
    "available_quantity": 5
  }
}
```

## Calculation

- `price`, `currency`, `purchase_url`: first row from `product_prices`, ordered by
  `is_lowest desc`, then `price asc`.
- `available_quantity`: `stock_quantity - reserved_quantity - safety_stock`, floored at `0`.
- `can_purchase`: true only when product is active, seller is active, price exists,
  `sales_status=ON_SALE`, and `available_quantity > 0`.

## Stock Status

| Status | Meaning |
| --- | --- |
| `UNKNOWN` | No inventory row exists. |
| `HIDDEN` | Inventory sales status is hidden. |
| `SOLD_OUT` | Inventory is sold out or available quantity is `0`. |
| `LOW_STOCK` | Available quantity is `1` to `5`. |
| `IN_STOCK` | Available quantity is `6` or more. |

## Boundary

Frontend can use `purchase_info` to render price, seller, and button state.

Cart/order APIs must still re-check product, price, inventory, and transaction rules at write time.
