# Order / Payment API Contract

Backend owner: R3 Wonwoo

## Purpose

This document fixes the backend contract for order creation, inventory reservation, Toss payment, and order lookup.

It follows the current commerce direction:

- Use `product_id`, not `offer_id`.
- Checkout and order are based on selected `cart_item_ids`, not always the whole cart.
- Order/payment APIs require login.
- Prices, stock, shipping fee, and order totals are recalculated by the backend.
- Product, seller, price, shipping, and address values needed for CS/order history are snapshotted at order time.

## Scope

Included in this stage:

- Saved address APIs.
- Selected-cart-item checkout preview.
- Order creation.
- Inventory reservation on order creation.
- Toss payment-window request and server-side payment confirmation.
- Toss payment confirm request/response boundary validation.
- Toss payment attempt tracking and uncertain-state recovery.
- Toss webhook receipt with duplicate-event protection.
- Toss payment lookup reconciliation.
- Toss cancellation processing for `CANCEL_REQUESTED` orders.
- Payment expiration handling through service logic and confirm-time checks.
- Order list/detail.
- Pre-payment cancel.
- Post-payment cancel/refund/return/exchange request statuses.

Deferred / advanced:

- Toss production webhook registration and provider-side signature configuration.
- Partial refund automation.
- Partial refund automation.
- Return pickup and exchange shipment automation.
- Scheduler/worker for automatic payment expiry sweep.

## Key Decisions

- Actual order/payment requires an authenticated user.
- Anonymous users may browse, run skin test, add cart items, and see checkout preview.
- Frontend must call `POST /api/cart/merge` after login before creating an order.
- `POST /api/orders` requires an `Idempotency-Key` header.
- The idempotency key is unique per `user_id + idempotency_key`.
- Frontend should generate the key once per order attempt with `crypto.randomUUID()`.
- Order API routes use `order_code`, not the internal DB id.
- Payment API routes use `payment_code`, not the internal DB id.
- Inventory is reserved when the order is created.
- Inventory is actually deducted only after payment approval.
- Failed, expired, or canceled pending payments release reserved inventory.
- New order requests accept only the `TOSS` provider.
- Legacy Mock confirm/fail routes are disabled and always return `410 MOCK_PAYMENT_DISABLED`.
- Toss webhook payloads never directly finalize payment; the backend verifies the payment through the Toss lookup API.
- `CONFIRMING` and `UNKNOWN` payments retain inventory reservations until lookup reconciliation confirms a terminal result.

## Order Flow

```text
1. User selects cart items in frontend.
2. Frontend calls POST /api/checkout/preview with selected cart_item_ids.
3. Frontend calls POST /api/orders with the same selected cart_item_ids.
4. Backend creates PENDING_PAYMENT order and READY payment.
5. Backend reserves inventory.
6. Frontend opens the Toss payment window with order_code/payment_code.
7. Payment confirm succeeds or fails.
8. Backend updates order, payment, inventory, inventory_movements, and payment_events.
```

## Status Enums

### `orders.status`

```text
PENDING_PAYMENT
PAID
PAYMENT_FAILED
EXPIRED
CANCELED
PREPARING_SHIPMENT
SHIPPED
DELIVERED
CANCEL_REQUESTED
REFUND_REQUESTED
REFUNDED
RETURN_REQUESTED
RETURNED
EXCHANGE_REQUESTED
EXCHANGED
```

### `order_items.status`

```text
ORDERED
CANCELED
PREPARING_SHIPMENT
SHIPPED
DELIVERED
RETURN_REQUESTED
RETURNED
EXCHANGE_REQUESTED
EXCHANGED
REFUND_REQUESTED
REFUNDED
```

### `payments.status`

```text
READY
CONFIRMING
UNKNOWN
APPROVED
FAILED
CANCELED
EXPIRED
REFUND_REQUESTED
REFUNDED
PARTIALLY_REFUNDED
```

### `payments.provider`

```text
MOCK
TOSS
```

`MOCK` remains in the database and historical service code only for existing records and migration compatibility. New order requests reject it with `UNSUPPORTED_PAYMENT_PROVIDER`, and its public confirm/fail routes return `410 MOCK_PAYMENT_DISABLED`.

The following values also remain reserved in the current database enum for compatibility, but new order requests reject them with `UNSUPPORTED_PAYMENT_PROVIDER`:

```text
KAKAO_PAY
NAVER_PAY
```

The active payment implementation is Toss. Sandbox or production mode is selected only by deployment credentials; the API contract is identical.

## Public Codes

Internal DB ids stay numeric and are not the frontend contract.

Public API identifiers:

```text
order_code: ord_YYYYMMDD_random
payment_code: pay_YYYYMMDD_random
```

Example:

```text
ord_20260705_k7x9q2m4
pay_20260705_p8a1z6cn
```

Payment providers should receive `order_code` as the provider order id.

## Selected Cart Item Rule

Checkout/order is not always "all items in the cart".

Frontend sends selected cart item ids:

```json
{
  "cart_item_ids": [12, 15, 18]
}
```

Rules:

- `cart_item_ids` is required for order creation.
- Empty `cart_item_ids` is invalid.
- Backend verifies every cart item belongs to the logged-in user's active cart.
- Selected items only are included in checkout/order.
- Unselected items remain in the active cart.
- After order creation, selected items must no longer appear in the user's active cart.
- Backend may move selected rows to an `ORDERED` cart for traceability; public behavior is that only unselected items remain in the active cart.

## Address APIs

Saved address book APIs are required because order creation may use `address_id`.

### `GET /api/me/addresses`

Returns the logged-in user's saved addresses.

### `POST /api/me/addresses`

Request:

```json
{
  "address_name": "Home",
  "recipient_name": "Kim Wonwoo",
  "phone": "01012345678",
  "postal_code": "12345",
  "address1": "Seoul ...",
  "address2": "101",
  "delivery_memo": "Leave at door",
  "is_default": true
}
```

Behavior:

- Requires login.
- If this is the user's first saved address, the backend sets it as default even when `is_default = false`.
- If `is_default = true`, unset the previous default address.

### `PATCH /api/me/addresses/{address_id}`

Updates one saved address owned by the current user.
If `is_default = true`, the address becomes the user's default address.
If saved addresses remain, the backend keeps exactly one default address.

### `DELETE /api/me/addresses/{address_id}`

Deletes one saved address owned by the current user.

The backend may reject deletion if an in-progress order still references the saved address. Existing orders use order shipping snapshots and must not change.
If the deleted address was the default address, the backend promotes the latest remaining saved address to default.

## `POST /api/checkout/preview`

Returns a read-only checkout preview for selected cart items.

Requires:

- Anonymous or logged-in user is allowed.
- For actual order creation, login is still required.

Request:

```json
{
  "cart_item_ids": [12, 15],
  "address_id": 3
}
```

`address_id` is optional for MVP shipping calculation because the default shipping policy is seller-based. It is included to support later address/region policies.

Behavior:

- Does not create order rows.
- Does not create payment rows.
- Does not reserve or deduct inventory.
- Revalidates product visibility, seller status, sales status, price, and available stock.
- Calculates shipping groups by seller.
- Default base shipping fee is `3000`.
- Product-level shipping fee is not part of the MVP default policy.

Response:

```json
{
  "cart_id": 1,
  "items": [
    {
      "id": 12,
      "product_id": "prod_001",
      "quantity": 2,
      "unit_price_snapshot": 19000,
      "current_unit_price": 19000,
      "currency": "KRW",
      "line_subtotal": 38000,
      "price_changed": false,
      "source": "ai_recommendation",
      "recommendation_id": "rec_123",
      "recommendation_rank": 1,
      "product": {
        "product_id": "prod_001",
        "brand": "Brand",
        "name": "Product Name",
        "category_code": "cream",
        "category_name": "Cream",
        "thumbnail_url": "products/prod_001/thumbnail.jpg",
        "current_price": 19000,
        "currency": "KRW",
        "sales_status": "ON_SALE",
        "stock_status": "IN_STOCK",
        "available_quantity": 10
      }
    }
  ],
  "subtotal": 38000,
  "shipping_fee": 3000,
  "discount_total": 0,
  "total": 41000,
  "currency": "KRW",
  "shipping_groups": [
    {
      "seller_code": "mwobareullae",
      "seller_name": "Mwobareullae",
      "item_subtotal": 38000,
      "base_shipping_fee": 3000,
      "free_shipping_threshold": null,
      "shipping_fee": 3000
    }
  ],
  "can_checkout": true,
  "warnings": []
}
```

## `POST /api/orders`

Creates a pending order and reserves inventory.

Requires:

- Login.
- `Idempotency-Key` header.

Header:

```http
Idempotency-Key: 58fd06a8-5f8b-4ed2-8c12-c3c43d51cd0a
```

Request using saved address:

```json
{
  "cart_item_ids": [12, 15],
  "address_id": 3,
  "payment_provider": "TOSS"
}
```

Request using direct shipping address:

```json
{
  "cart_item_ids": [12, 15],
  "shipping_address": {
    "address_name": "Home",
    "recipient_name": "Kim Wonwoo",
    "phone": "01012345678",
    "postal_code": "12345",
    "address1": "Seoul ...",
    "address2": "101",
    "delivery_memo": "Leave at door",
    "save_to_address_book": true,
    "set_as_default": false
  },
  "payment_provider": "TOSS"
}
```

Behavior:

- Validates ownership of selected cart items.
- Revalidates product, seller, price, sales status, and stock.
- Locks inventory rows for selected products.
- Increases `inventories.reserved_quantity`.
- Creates `orders.status = PENDING_PAYMENT`.
- Creates `payments.status = READY`.
- Creates `order_items` snapshots.
- Creates `order_shipping_addresses` snapshot.
- Creates `order_shipping_groups` snapshots.
- Records inventory reservation in `inventory_movements`.
- Returns existing order if the same user sends the same `Idempotency-Key` again.
- Payment must be completed before `payment_expires_at`.
- Rejects `KAKAO_PAY` and `NAVER_PAY` with `UNSUPPORTED_PAYMENT_PROVIDER`.

Response:

```json
{
  "order_code": "ord_20260705_k7x9q2m4",
  "status": "PENDING_PAYMENT",
  "payment": {
    "payment_code": "pay_20260705_p8a1z6cn",
    "provider": "TOSS",
    "status": "READY",
    "amount": 41000,
    "currency": "KRW"
  },
  "subtotal": 38000,
  "shipping_fee": 3000,
  "discount_total": 0,
  "total": 41000,
  "currency": "KRW",
  "payment_expires_at": "2026-07-05T12:15:00+09:00"
}
```

## Order Item Snapshot

`order_items` stores both references and order-time values.

Required snapshot fields:

```text
order_id
cart_item_id
product_id
seller_id
product_name_snapshot
brand_name_snapshot
seller_name_snapshot
thumbnail_storage_key_snapshot
unit_price
quantity
line_subtotal
line_discount_amount
line_total
status
recommendation_id
recommendation_rank
source
created_at
updated_at
```

Not required for order item snapshot:

- Full ingredient snapshot.
- Full effect snapshot.
- Full recommendation score breakdown.
- Full product detail description.
- Review/rating snapshot.

Past order detail should render from order snapshots, not from mutable current product fields.

## Shipping Group Snapshot

Shipping is seller-policy based.

Current MVP:

- One first-party seller.
- Base shipping fee: `3000`.
- Usually one shipping group per order.

Future:

- Checked brand sellers may create multiple seller shipping groups.

`order_shipping_groups` stores:

```text
order_id
seller_id
seller_name_snapshot
item_subtotal
shipping_fee
free_shipping_threshold_snapshot
shipping_policy_snapshot_json
```

`order_shipping_groups` is for shipping fee calculation and settlement snapshots.

`shipments` is separate and tracks carrier, invoice, tracking number, and delivery status.

## Shipping Address Snapshot

Saved address changes must not mutate past orders.

Order creation always creates an `order_shipping_addresses` snapshot:

```text
order_id
address_name
recipient_name
phone
postal_code
address1
address2
delivery_memo
```

If `shipping_address.save_to_address_book = true`, the backend also saves it to `user_addresses`.

## `GET /api/orders`

Returns the current user's order list.

Query params:

| Param | Meaning |
|---|---|
| `status` | Optional order status filter |
| `limit` | Page size |
| `cursor` | Cursor for pagination |

Response:

```json
{
  "items": [
    {
      "order_code": "ord_20260705_k7x9q2m4",
      "status": "PAID",
      "total": 41000,
      "currency": "KRW",
      "item_count": 2,
      "ordered_at": "2026-07-05T12:00:00+09:00",
      "paid_at": "2026-07-05T12:01:00+09:00",
      "thumbnail_storage_key": "products/prod_001/thumbnail.jpg",
      "title": "Product Name and 1 more"
    }
  ],
  "next_cursor": null
}
```

## `GET /api/orders/{order_code}`

Returns one order detail owned by the current user.

Response:

```json
{
  "order_code": "ord_20260705_k7x9q2m4",
  "status": "PAID",
  "subtotal": 38000,
  "shipping_fee": 3000,
  "discount_total": 0,
  "total": 41000,
  "currency": "KRW",
  "payment": {
    "payment_code": "pay_20260705_p8a1z6cn",
    "provider": "TOSS",
    "status": "APPROVED",
    "approved_at": "2026-07-05T12:01:00+09:00"
  },
  "items": [],
  "shipping_address": {},
  "shipping_groups": []
}
```

## `POST /api/orders/{order_code}/cancel`

Cancels or requests cancellation.

Behavior:

- If order is `PENDING_PAYMENT`, cancel immediately.
- Immediate cancel releases reserved inventory.
- Payment status becomes `CANCELED`.
- If order is already `PAID`, do not auto-refund in MVP.
- Paid orders move to `CANCEL_REQUESTED`.

Response:

```json
{
  "order_code": "ord_20260705_k7x9q2m4",
  "status": "CANCELED"
}
```

## `POST /api/payments/{payment_code}/mock/confirm`

Disabled legacy endpoint. It is retained only so old clients receive an explicit contract error instead of an ambiguous 404.

Requires:

- Login.
- The payment belongs to the current user's order.

Behavior: always returns HTTP `410` without changing payment, order, or inventory state.

Response:

```json
{
  "error": {
    "code": "MOCK_PAYMENT_DISABLED",
    "message": "Mock payment is disabled."
  }
}
```

## `POST /api/payments/{payment_code}/mock/fail`

Fails mock payment.

Behavior: always returns HTTP `410` without changing payment, order, or inventory state.

Response:

```json
{
  "error": {
    "code": "MOCK_PAYMENT_DISABLED",
    "message": "Mock payment is disabled."
  }
}
```

## `POST /api/payments/toss/confirm`

Toss sandbox confirm contract.

Backend env:

- `TOSS_SECRET_KEY`: TossPayments secret key. Keep the real sandbox/live key only in local `.env`, GitHub Secrets, or server env.

Request:

```json
{
  "payment_key": "tosspayments_payment_key",
  "order_code": "ord_20260705_k7x9q2m4",
  "amount": 41000
}
```

Behavior:

- Verifies current user owns the order.
- Verifies the payment provider is `TOSS`.
- Verifies order/payment status.
- Verifies amount equals backend order total.
- Verifies order is not expired.
- Accepts a `payment_key` of at most 200 characters and an `order_code` of at most 64 characters.
- Calls Toss confirm API.
- Requires the Toss response to contain matching `paymentKey`, `orderId`, and integer `totalAmount`, with `status = DONE`.
- Stores `provider_payment_key`.
- Stores a payment event with a deterministic SHA-256-based event id so provider key length cannot exceed the DB event-id limit.
- Applies the successful-payment DB transition after Toss approval.

Hardening deferred:

- Toss webhook URL registration and provider-side delivery configuration.
- Manual/admin payment repair flow.

## `POST /api/payments/toss/webhook`

The endpoint accepts a Toss payment-status notification and uses it only as a
reconciliation trigger. The request must contain `paymentKey` or `orderId`.
The optional `X-Toss-Webhook-Id` header, or the payload `eventId`, is used for
duplicate protection. If neither exists, the backend derives a deterministic
event id from the payload.

The payload is reduced to a non-sensitive summary and stored in
`payment_events` as `TOSS_WEBHOOK_RECEIVED`. The backend then calls the Toss
payment lookup API and applies the same reconciliation rules as the scheduled
service. A duplicate event returns success without repeating the lookup.

Example request:

```json
{
  "eventType": "PAYMENT_STATUS_CHANGED",
  "paymentKey": "tosspayments_payment_key",
  "orderId": "ord_20260705_k7x9q2m4",
  "status": "DONE"
}
```

Example response:

```json
{
  "accepted": true,
  "matched": true,
  "duplicate": false,
  "reconciled": 1,
  "unknown": 0
}
```

The webhook body alone is never treated as proof of payment success.

## Payment reconciliation CLI

```text
python -m app.cli.reconcile_pending_payments --limit 100
python -m app.cli.reconcile_pending_payments --limit 100 --dry-run
```

`DONE` changes the payment to `APPROVED`, the order to `PAID`, and confirms
reserved inventory. `ABORTED` and `EXPIRED` release the reservation and mark
the payment as failed. Query failures, mismatched order/amount, and unknown
provider statuses keep the payment in `UNKNOWN`.

## Payment Expiration

Default:

```text
payment_expires_at = order.created_at + 15 minutes
```

Rules:

- Payment confirm after expiry must not approve the order.
- Expired pending order releases reserved inventory.
- Implement `expire_pending_orders(now)` service function.
- Scheduler/worker can call it later.
- MVP does not require a scheduler before the service function and confirm-time expiry check exist.

## Inventory Rules

On order creation:

```text
available_quantity = stock_quantity - reserved_quantity
```

For each selected item:

- Lock the inventory row.
- Check `available_quantity >= quantity`.
- Increase `reserved_quantity`.
- Write `inventory_movements` with reservation reason.

On payment success:

- Decrease `reserved_quantity`.
- Decrease `stock_quantity`.
- Write sale movement.

On payment fail, expiry, or pre-payment cancel:

- Decrease `reserved_quantity`.
- Do not decrease `stock_quantity`.
- Write release movement.

## Payment Events

`payment_events` stores payment state transitions and external provider payload summaries.

Recommended fields:

```text
payment_id
order_id
event_type
event_id
provider
provider_payment_key
provider_order_id
amount
status_before
status_after
raw_payload_json
created_at
```

Idempotency:

```text
UNIQUE(provider, event_id)
```

If the provider has no event id, use a generated deterministic fallback from provider, provider payment key, event type, and status.

`raw_payload_json` must not store card number, password, resident number, or other sensitive values.

## Post-Payment CS Scope

MVP state support:

- `CANCEL_REQUESTED`
- `REFUND_REQUESTED`
- `RETURN_REQUESTED`
- `EXCHANGE_REQUESTED`

MVP automation boundary:

- Pre-payment cancel is immediate.
- Payment fail/expiry releases reserved inventory.
- Toss payment success deducts inventory.
- Paid order claim requests are stored in claim tables with status and event history.
- Refund execution, return pickup, and exchange reshipment remain later admin/PG/shipment work.

## Cancellation processing

`POST /api/orders/{order_code}/cancel` does not call an external payment
provider. For a paid order it records `CANCEL_REQUESTED` and returns. The
operational processor then handles full cancellation:

```text
python -m app.cli.cancel_requested_orders --limit 100
python -m app.cli.cancel_requested_orders --limit 100 --reason "customer requested cancellation"
python -m app.cli.cancel_requested_orders --limit 100 --dry-run
```

Historical `MOCK` rows are processed locally only for backward compatibility. New `TOSS` payments call the Toss cancel API and are finalized only when the response has `status = CANCELED`. A
network failure, provider error, missing payment key, or invalid response
keeps the order at `CANCEL_REQUESTED` and records an `UNKNOWN` cancel attempt
for a later retry. Full cancellation marks the order and order items as
`CANCELED`, marks the payment as `CANCELED`, and restores the sold quantity to
inventory with a `SALE_CANCEL` movement.

## Order claim API

Only delivered orders can create a return, exchange, or refund claim. The
claim window is seven days from `delivered_at`, and partial item quantities are
allowed. Active claim quantities are subtracted from the remaining claimable
quantity.

```text
GET  /api/orders/{order_code}/claim-eligibility
POST /api/order-claims
GET  /api/order-claims
GET  /api/order-claims/{claim_code}
POST /api/order-claims/{claim_code}/withdraw
```

Creating a claim records `REQUESTED` state and does not execute a refund,
inventory restoration, pickup, or exchange shipment. Those operations require
later administrator processing. Users can withdraw only a `REQUESTED` claim.

Order list and detail responses expose `shipped_at` and `delivered_at`. These
values are null until the corresponding fulfillment status is recorded.

## Frontend Responsibilities

- Use `cart_item_ids` selected by user.
- If the user clicks checkout while anonymous, redirect to login first.
- After login, call `POST /api/cart/merge`.
- Generate one `Idempotency-Key` UUID per order attempt.
- Reuse the same idempotency key for retry/double-click of the same attempt.
- Do not trust frontend price, stock, or shipping fee.
- Render backend checkout preview and order response totals.
- Use `order_code` and `payment_code` in frontend routes/API calls.
- Build product image CDN URL from `thumbnail_storage_key_snapshot` or existing storage-key image fields.

## Later Revisit

Revisit these after the Toss payment and core order/inventory flow are stable:

- Toss/Kakao external API transaction boundary.
- External payment success but DB transition failure recovery.
- Scheduler/worker for expired orders.
- Partial cancel and partial refund.
- Return/exchange logistics.
