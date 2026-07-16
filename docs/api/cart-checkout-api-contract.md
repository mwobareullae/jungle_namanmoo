# Cart / Checkout Preview API Contract

Backend owner: R3 Wonwoo

## Scope

This contract covers MVP cart and checkout preview APIs.

Included:

- Logged-in user cart
- Anonymous cart with backend-managed HttpOnly cookie
- Cart item add/update/delete
- Explicit anonymous cart merge after login
- Checkout preview price/stock revalidation

Excluded from this branch:

- Order creation
- Payment / Toss Payments
- Inventory deduction
- Payment webhook idempotency
- Popularity metric aggregation
- Event log emission

## Key Decisions

- Public API product key is `product_id`, mapped to `products.product_code`.
- Cart items do not use `offer_id`.
- One cart item row exists for one `cart_id + product_id`.
- Adding the same product increases quantity.
- `PATCH /cart/items/{item_id}` with `quantity = 0` deletes the item.
- Anonymous cart identity is stored in the `mwbl_cart` HttpOnly cookie.
- Cart data is stored in DB, not in browser localStorage.
- Checkout preview is read-only and does not create order/payment rows.
- MVP checkout preview uses seller shipping policy.
- Default seller shipping fee is `3000`.
- Shipping policy belongs to seller, not product.

## Image Rule

Product card `thumbnail_url` keeps the existing response field name, but its value is a `storage_key`, not a CDN absolute URL.

Frontend builds the final image URL with:

```text
VITE_IMAGE_CDN_BASE_URL + "/resized/w400/" + thumbnail_url
```

## Anonymous Cart Cookie

| Name | Value |
|---|---|
| Cookie name | `mwbl_cart` |
| Type | random opaque token |
| HttpOnly | yes |
| Max age | 30 days |
| Secure / SameSite | follows backend auth cookie settings |

## `GET /api/cart`

Returns the current active cart.

Behavior:

- Logged-in user: returns user's active cart.
- Anonymous user with `mwbl_cart`: returns anonymous active cart.
- Anonymous user without cart cookie: returns an empty cart and does not create a DB row.

Response:

```json
{
  "cart_id": 1,
  "owner_type": "anonymous",
  "items": [],
  "total_quantity": 0,
  "subtotal": 0,
  "currency": "KRW",
  "warnings": []
}
```

## `POST /api/cart/items`

Adds a product to the current cart.

Request:

```json
{
  "product_id": "prod_001",
  "quantity": 1,
  "source": "ai_recommendation",
  "recommendation_id": "rec_123",
  "recommendation_rank": 1
}
```

Behavior:

- Creates an active cart if none exists.
- For anonymous users, sets `mwbl_cart` cookie when a new anonymous cart is created.
- Validates product active state, seller status, price, sales status, and available stock.
- Same product add increases quantity.
- Stores add-time `unit_price_snapshot`.
- Missing product returns `404 NOT_FOUND`.
- Unpurchasable product returns `409` with a specific code such as `OUT_OF_STOCK`.

Response: `CartResponse`.

## `PATCH /api/cart/items/{item_id}`

Updates item quantity.

Request:

```json
{
  "quantity": 2
}
```

Behavior:

- `quantity = 0` deletes the item.
- Quantity must be 0 to 99.
- Positive quantity revalidates current stock/sales state.

Response: `CartResponse`.

## `DELETE /api/cart/items/{item_id}`

Deletes one cart item.

Behavior:

- Idempotent for already-missing rows in the current cart.

Response:

```json
{
  "success": true,
  "cart": {}
}
```

## `DELETE /api/cart/items/bulk`

Deletes multiple selected items from the current user's or anonymous cart.

Request:

```json
{
  "cart_item_ids": [101, 102]
}
```

The operation is idempotent for item IDs that are missing or do not belong to
the current cart. Duplicate IDs are removed once. The response includes the
actual deleted IDs and the refreshed cart snapshot. Each deleted item records
the same `cart_removed` event as single-item deletion.

Response:

```json
{
  "success": true,
  "deleted_item_ids": [101, 102],
  "cart": {}
}
```

## `POST /api/cart/merge`

Requires login.

Merges anonymous cart from `mwbl_cart` into the logged-in user's active cart.

Behavior:

- If no anonymous cart exists, returns current user cart with `merged = false`.
- If user has no active cart, anonymous cart becomes the user cart.
- If user already has an active cart, items are merged by `product_id`.
- Same-product quantities are summed and capped at 99.
- Deletes `mwbl_cart` cookie after the merge request.

Response:

```json
{
  "merged": true,
  "cart": {}
}
```

## `POST /api/checkout/preview`

Returns read-only checkout preview for the current cart.

Behavior:

- Does not create order rows.
- Does not create payment rows.
- Does not deduct inventory.
- Recalculates current price and stock.
- Returns blocking warnings for sold-out, hidden, stock unknown, or insufficient stock.
- Returns info warning for price changes.
- Calculates shipping fee by seller group.
- Default seller shipping fee is `3000`.
- Seller shipping policy can later be managed by admin.
- Product-level shipping fee is not part of the MVP default policy.

Response:

```json
{
  "cart_id": 1,
  "items": [],
  "subtotal": 19900,
  "shipping_fee": 3000,
  "shipping_groups": [
    {
      "seller_code": "mwobareullae",
      "seller_name": "뭐바를래",
      "item_subtotal": 19900,
      "base_shipping_fee": 3000,
      "free_shipping_threshold": null,
      "shipping_fee": 3000
    }
  ],
  "total": 22900,
  "currency": "KRW",
  "can_checkout": true,
  "warnings": []
}
```

## Frontend Notes

- Anonymous users can add products to cart.
- Checkout/order/payment page should still require login in the later Order/Payment branch.
- After login, frontend should call `POST /api/cart/merge`.
- Product image values are storage keys, not absolute URLs.
- Checkout button should be disabled when `can_checkout = false`.
