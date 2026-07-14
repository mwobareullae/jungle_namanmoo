# Wishlist / Recent API Contract

Backend owner: R3 Wonwoo

## Scope

This contract covers logged-in user wishlist and recent-view APIs.

MVP policy:

- Wishlist is login-only.
- Recent views are login-only in the backend API.
- Anonymous recent behavior can stay in frontend local/session state or future event logs.
- Cart may support anonymous users later, but that belongs to the Cart/Checkout branch.
- These APIs do not update `product_popularity_metrics` directly.

## Product ID Rule

External API fields use `product_id` as the public product code, for example `prod_001`.

Database rows store the internal `products.id` FK.

## Image Rule

Product card `thumbnail_url` keeps the existing response field name, but its value is a `storage_key`, not a CDN absolute URL.

Wishlist and recent-view product availability follows [`product-card-availability-contract.md`](./product-card-availability-contract.md).

Frontend builds the final image URL with:

```text
VITE_IMAGE_CDN_BASE_URL + "/resized/w400/" + thumbnail_url
```

## Wishlist

### `GET /api/me/wishlist`

Requires login.

Query:

| Name | Type | Default | Description |
|---|---:|---:|---|
| `limit` | integer | `50` | 1 to 100 |

Response:

```json
{
  "items": [
    {
      "id": 1,
      "product_id": "prod_001",
      "added_at": "2026-07-05T12:00:00Z",
      "product": {
        "product_id": "prod_001",
        "brand": "브랜드",
        "name": "상품명",
        "category_code": "cream",
        "category_name": "크림",
        "thumbnail_url": "products/prod_001/thumbnail.jpg",
        "lowest_price": 19900,
        "sales_status": "ON_SALE",
        "stock_status": "IN_STOCK",
        "available_quantity": 12,
        "in_stock": true
      }
    }
  ]
}
```

Sort:

```text
added_at DESC, id DESC
```

### `POST /api/me/wishlist`

Requires login.

Request:

```json
{
  "product_id": "prod_001"
}
```

Behavior:

- `Product.is_active = true` product only.
- Repeating the same product is idempotent.
- Missing or inactive product returns `404 NOT_FOUND`.

Response: `WishlistItem`.

### `DELETE /api/me/wishlist/{product_id}`

Requires login.

Behavior:

- Idempotent.
- Deleting a missing wishlist row still returns success.

Response:

```json
{
  "success": true
}
```

## Recent Views

### `GET /api/me/recent`

Requires login.

Query:

| Name | Type | Default | Description |
|---|---:|---:|---|
| `limit` | integer | `50` | 1 to 100 |

Behavior:

- Returns rows viewed in the last 30 days.
- Old rows are not physically deleted in this API.

Response:

```json
{
  "items": [
    {
      "id": 1,
      "product_id": "prod_001",
      "viewed_at": "2026-07-05T12:00:00Z",
      "product": {
        "product_id": "prod_001",
        "brand": "브랜드",
        "name": "상품명",
        "category_code": "cream",
        "category_name": "크림",
        "thumbnail_url": "products/prod_001/thumbnail.jpg",
        "lowest_price": 19900
      }
    }
  ]
}
```

Sort:

```text
viewed_at DESC, id DESC
```

### `POST /api/me/recent`

Requires login.

Request:

```json
{
  "product_id": "prod_001"
}
```

Behavior:

- Frontend calls this when a logged-in user enters a product detail page.
- `GET /api/products/{product_id}` stays read-only and does not write recent-view rows.
- `user_id + product_id` is unique.
- Re-viewing the same product updates `viewed_at`.
- Missing or inactive product returns `404 NOT_FOUND`.

Response: `RecentViewItem`.

### `DELETE /api/me/recent/{product_id}`

Requires login.

Behavior:

- Idempotent.
- Deleting a missing recent-view row still returns success.

Response:

```json
{
  "success": true
}
```

## Frontend Notes

- Wishlist click while logged out should lead to login.
- Product detail page should call `POST /api/me/recent` only when the user is logged in.
- Wishlist/Recent response product images are storage keys.
- These APIs do not imply cart support. Anonymous cart is a separate Cart/Checkout decision.
