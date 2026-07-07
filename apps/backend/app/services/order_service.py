from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import (
    Cart,
    CartItem,
    Inventory,
    InventoryMovement,
    Order,
    OrderItem,
    OrderShippingAddress,
    OrderShippingGroup,
    Payment,
    Seller,
    SellerShippingPolicy,
    UserAddress,
)
from app.schemas.common import ApiError
from app.schemas.order import (
    DirectShippingAddressRequest,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderPaymentSummary,
)
from app.services.address_service import create_user_address
from app.schemas.address import UserAddressCreateRequest
from app.services.product_image_service import load_thumbnail_storage_keys


CART_STATUS_ACTIVE = "ACTIVE"
CART_STATUS_ORDERED = "ORDERED"
DEFAULT_CURRENCY = "KRW"
DEFAULT_BASE_SHIPPING_FEE = 3000
PAYMENT_EXPIRY_MINUTES = 15


@dataclass(frozen=True)
class _SelectedCartRow:
    item: CartItem
    product: Product
    brand: Brand
    category: ProductCategory
    seller: Seller
    price: ProductPrice
    inventory: Inventory
    thumbnail_storage_key: str | None

    @property
    def line_subtotal(self) -> int:
        return self.price.price * self.item.quantity


@dataclass(frozen=True)
class _ShippingAddressSnapshot:
    user_address_id: int | None
    recipient_name: str
    phone: str
    postal_code: str
    address1: str
    address2: str | None
    delivery_memo: str | None


@dataclass(frozen=True)
class _ShippingGroupSnapshot:
    seller_id: int
    seller_name_snapshot: str
    item_subtotal: int
    shipping_fee: int
    free_shipping_threshold_snapshot: int | None
    shipping_policy_snapshot_json: dict


def create_order(
    session: Session,
    user: User,
    request: OrderCreateRequest,
    idempotency_key: str | None,
) -> OrderCreateResponse:
    started_at = current_time()
    requested_item_count = len(request.cart_item_ids)
    try:
        normalized_key = _normalize_idempotency_key(idempotency_key)
        existing_order = _load_order_by_idempotency_key(session, user.id, normalized_key)
        if existing_order is not None:
            response = _to_order_response(session, existing_order)
            _log_order_create_completed(
                started_at,
                order=existing_order,
                payment_provider=response.payment.provider,
                requested_item_count=requested_item_count,
                reserved_item_count=existing_order.item_count,
                reserved_quantity_total=existing_order.total_quantity,
                seller_count=None,
                idempotent_replay=True,
            )
            return response

        selected_item_ids = _validate_cart_item_ids(request.cart_item_ids)
        shipping_address = _resolve_shipping_address(session, user, request)
        active_cart = _require_active_user_cart(session, user.id)
        selected_rows = _load_selected_cart_rows(session, active_cart.id, selected_item_ids)

        _validate_selected_rows(selected_rows)
        shipping_groups = _build_shipping_group_snapshots(session, selected_rows)
        subtotal = sum(row.line_subtotal for row in selected_rows)
        shipping_fee = sum(group.shipping_fee for group in shipping_groups)
        discount_total = 0
        total = subtotal + shipping_fee - discount_total
        currency = _resolve_currency(selected_rows)
        now = datetime.now(UTC)

        ordered_cart = _create_ordered_cart(session, user.id, now)
        order = Order(
            order_code=_generate_public_code("ord", now),
            user_id=user.id,
            cart_id=ordered_cart.id,
            idempotency_key=normalized_key,
            status="PENDING_PAYMENT",
            subtotal_amount=subtotal,
            shipping_fee=shipping_fee,
            discount_amount=discount_total,
            total_amount=total,
            currency=currency,
            item_count=len(selected_rows),
            total_quantity=sum(row.item.quantity for row in selected_rows),
            payment_expires_at=now + timedelta(minutes=PAYMENT_EXPIRY_MINUTES),
            ordered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()

        _reserve_inventory(session, selected_rows, order.order_code, now)
        _move_selected_items_to_ordered_cart(selected_rows, ordered_cart.id, now)
        _create_order_items(session, order.id, selected_rows, now)
        _create_shipping_address_snapshot(session, order.id, shipping_address)
        _create_shipping_group_snapshots(session, order.id, shipping_groups)
        _create_ready_payment(session, order, request.payment_provider, now)
        _touch_cart(active_cart, now)
        session.flush()
        response = _to_order_response(session, order)
        _log_order_create_completed(
            started_at,
            order=order,
            payment_provider=request.payment_provider,
            requested_item_count=requested_item_count,
            reserved_item_count=len(selected_rows),
            reserved_quantity_total=order.total_quantity,
            seller_count=len({int(row.seller.id) for row in selected_rows}),
            idempotent_replay=False,
        )
        return response
    except ApiError as exc:
        _log_order_create_failed(
            started_at,
            error_code=exc.code,
            requested_item_count=requested_item_count,
            payment_provider=request.payment_provider,
        )
        raise


def _normalize_idempotency_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")
    normalized = idempotency_key.strip()
    if not normalized:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")
    if len(normalized) > 128:
        raise ApiError(400, "IDEMPOTENCY_KEY_TOO_LONG", "Idempotency-Key must be 128 characters or fewer.")
    return normalized


def _load_order_by_idempotency_key(session: Session, user_id: int, idempotency_key: str) -> Order | None:
    return session.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def _validate_cart_item_ids(cart_item_ids: list[int]) -> list[int]:
    if not cart_item_ids:
        raise ApiError(400, "EMPTY_ORDER_SELECTION", "cart_item_ids is required.")
    if any(item_id <= 0 for item_id in cart_item_ids):
        raise ApiError(400, "INVALID_CART_ITEM_ID", "cart_item_ids must contain positive integers.")
    if len(set(cart_item_ids)) != len(cart_item_ids):
        raise ApiError(400, "DUPLICATE_CART_ITEM_ID", "cart_item_ids must not contain duplicates.")
    return cart_item_ids


def _resolve_shipping_address(
    session: Session,
    user: User,
    request: OrderCreateRequest,
) -> _ShippingAddressSnapshot:
    if request.address_id is not None and request.shipping_address is not None:
        raise ApiError(400, "SHIPPING_ADDRESS_CONFLICT", "Use either address_id or shipping_address.")
    if request.address_id is None and request.shipping_address is None:
        raise ApiError(400, "SHIPPING_ADDRESS_REQUIRED", "Shipping address is required.")
    if request.address_id is not None:
        return _load_saved_shipping_address(session, user.id, request.address_id)
    assert request.shipping_address is not None
    return _build_direct_shipping_address(session, user, request.shipping_address)


def _load_saved_shipping_address(
    session: Session,
    user_id: int,
    address_id: int,
) -> _ShippingAddressSnapshot:
    if address_id <= 0:
        raise ApiError(400, "INVALID_ADDRESS_ID", "address_id must be a positive integer.")
    row = session.execute(
        select(UserAddress).where(
            UserAddress.id == address_id,
            UserAddress.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "ADDRESS_NOT_FOUND", "Address was not found.")
    return _ShippingAddressSnapshot(
        user_address_id=row.id,
        recipient_name=row.recipient_name,
        phone=row.phone,
        postal_code=row.postal_code,
        address1=row.address1,
        address2=row.address2,
        delivery_memo=row.delivery_memo,
    )


def _build_direct_shipping_address(
    session: Session,
    user: User,
    request: DirectShippingAddressRequest,
) -> _ShippingAddressSnapshot:
    snapshot = _ShippingAddressSnapshot(
        user_address_id=None,
        recipient_name=_required_text(request.recipient_name, "recipient_name"),
        phone=_required_text(request.phone, "phone"),
        postal_code=_required_text(request.postal_code, "postal_code"),
        address1=_required_text(request.address1, "address1"),
        address2=_optional_text(request.address2),
        delivery_memo=_optional_text(request.delivery_memo),
    )
    if not request.save_to_address_book:
        return snapshot

    saved = create_user_address(
        session,
        user,
        UserAddressCreateRequest(
            recipient_name=snapshot.recipient_name,
            phone=snapshot.phone,
            postal_code=snapshot.postal_code,
            address1=snapshot.address1,
            address2=snapshot.address2,
            delivery_memo=snapshot.delivery_memo,
            is_default=request.set_as_default,
        ),
    )
    return _ShippingAddressSnapshot(
        user_address_id=saved.id,
        recipient_name=snapshot.recipient_name,
        phone=snapshot.phone,
        postal_code=snapshot.postal_code,
        address1=snapshot.address1,
        address2=snapshot.address2,
        delivery_memo=snapshot.delivery_memo,
    )


def _require_active_user_cart(session: Session, user_id: int) -> Cart:
    cart = session.execute(
        select(Cart)
        .where(
            Cart.user_id == user_id,
            Cart.status == CART_STATUS_ACTIVE,
        )
        .order_by(Cart.updated_at.desc(), Cart.id.desc())
    ).scalars().first()
    if cart is None:
        raise ApiError(400, "EMPTY_CART", "Cart is empty.")
    return cart


def _load_selected_cart_rows(
    session: Session,
    cart_id: int,
    selected_item_ids: list[int],
) -> list[_SelectedCartRow]:
    rows = session.execute(
        select(CartItem, Product, Brand, ProductCategory, Seller)
        .join(Product, CartItem.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, CartItem.seller_id == Seller.id)
        .where(
            CartItem.cart_id == cart_id,
            CartItem.id.in_(selected_item_ids),
        )
        .order_by(CartItem.created_at.asc(), CartItem.id.asc())
    ).all()
    if len(rows) != len(selected_item_ids):
        raise ApiError(404, "CART_ITEM_NOT_FOUND", "Selected cart item was not found.")

    product_ids = [int(product.id) for _, product, _, _, _ in rows]
    thumbnails = load_thumbnail_storage_keys(session, product_ids)
    prices = _load_primary_prices(session, product_ids)
    inventories = _load_inventories_for_update(session, product_ids)

    selected_rows: list[_SelectedCartRow] = []
    for item, product, brand, category, seller in rows:
        price = prices.get(int(product.id))
        inventory = inventories.get(int(product.id))
        if price is None:
            raise ApiError(409, "PRICE_UNAVAILABLE", "Product price is unavailable.")
        if inventory is None:
            raise ApiError(409, "STOCK_UNKNOWN", "Product stock is unavailable.")
        selected_rows.append(
            _SelectedCartRow(
                item=item,
                product=product,
                brand=brand,
                category=category,
                seller=seller,
                price=price,
                inventory=inventory,
                thumbnail_storage_key=thumbnails.get(int(product.id)),
            )
        )
    return selected_rows


def _validate_selected_rows(selected_rows: list[_SelectedCartRow]) -> None:
    for row in selected_rows:
        if not row.product.is_active or not row.brand.is_active or not row.category.is_active:
            raise ApiError(409, "PRODUCT_UNAVAILABLE", "Product is not available.")
        if row.seller.status != "ACTIVE":
            raise ApiError(409, "SELLER_UNAVAILABLE", "Seller is not available.")
        if row.inventory.sales_status != "ON_SALE":
            raise ApiError(409, "NOT_ON_SALE", "Product is not on sale.")
        available = _available_quantity(row.inventory)
        if available <= 0:
            raise ApiError(409, "OUT_OF_STOCK", "Product is out of stock.")
        if available < row.item.quantity:
            raise ApiError(409, "INSUFFICIENT_STOCK", "Requested quantity exceeds available stock.")


def _load_primary_prices(session: Session, product_ids: list[int]) -> dict[int, ProductPrice]:
    rows = session.execute(
        select(ProductPrice)
        .where(ProductPrice.product_id.in_(product_ids))
        .order_by(
            ProductPrice.product_id.asc(),
            ProductPrice.is_lowest.desc(),
            ProductPrice.price.asc(),
            ProductPrice.id.asc(),
        )
    ).scalars()
    prices: dict[int, ProductPrice] = {}
    for row in rows:
        prices.setdefault(int(row.product_id), row)
    return prices


def _load_inventories_for_update(session: Session, product_ids: list[int]) -> dict[int, Inventory]:
    rows = session.execute(
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .with_for_update()
    ).scalars()
    return {int(row.product_id): row for row in rows}


def _build_shipping_group_snapshots(
    session: Session,
    selected_rows: list[_SelectedCartRow],
) -> list[_ShippingGroupSnapshot]:
    subtotals_by_seller: dict[int, int] = {}
    seller_names: dict[int, str] = {}
    for row in selected_rows:
        seller_id = int(row.seller.id)
        subtotals_by_seller[seller_id] = subtotals_by_seller.get(seller_id, 0) + row.line_subtotal
        seller_names[seller_id] = row.seller.display_name

    policies = _load_shipping_policies(session, list(subtotals_by_seller))
    groups: list[_ShippingGroupSnapshot] = []
    for seller_id, item_subtotal in subtotals_by_seller.items():
        policy = policies.get(seller_id)
        base_shipping_fee = policy.base_shipping_fee if policy else DEFAULT_BASE_SHIPPING_FEE
        free_shipping_threshold = policy.free_shipping_threshold if policy else None
        shipping_fee = (
            0
            if free_shipping_threshold is not None and item_subtotal >= free_shipping_threshold
            else base_shipping_fee
        )
        groups.append(
            _ShippingGroupSnapshot(
                seller_id=seller_id,
                seller_name_snapshot=seller_names[seller_id],
                item_subtotal=item_subtotal,
                shipping_fee=shipping_fee,
                free_shipping_threshold_snapshot=free_shipping_threshold,
                shipping_policy_snapshot_json={
                    "policy_name": policy.policy_name if policy else "default",
                    "base_shipping_fee": base_shipping_fee,
                    "free_shipping_threshold": free_shipping_threshold,
                },
            )
        )
    return groups


def _load_shipping_policies(session: Session, seller_ids: list[int]) -> dict[int, SellerShippingPolicy]:
    if not seller_ids:
        return {}
    rows = session.execute(
        select(SellerShippingPolicy)
        .where(
            SellerShippingPolicy.seller_id.in_(seller_ids),
            SellerShippingPolicy.is_active.is_(True),
        )
        .order_by(SellerShippingPolicy.seller_id.asc(), SellerShippingPolicy.id.asc())
    ).scalars()
    policies: dict[int, SellerShippingPolicy] = {}
    for row in rows:
        policies.setdefault(int(row.seller_id), row)
    return policies


def _create_ordered_cart(session: Session, user_id: int, now: datetime) -> Cart:
    cart = Cart(
        user_id=user_id,
        status=CART_STATUS_ORDERED,
        created_at=now,
        updated_at=now,
    )
    session.add(cart)
    session.flush()
    return cart


def _reserve_inventory(
    session: Session,
    selected_rows: list[_SelectedCartRow],
    order_code: str,
    now: datetime,
) -> None:
    for row in selected_rows:
        row.inventory.reserved_quantity += row.item.quantity
        row.inventory.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=row.inventory.id,
                product_id=row.product.id,
                movement_type="RESERVE",
                quantity_delta=row.item.quantity,
                stock_after=row.inventory.stock_quantity,
                reason="order pending payment reservation",
                reference_type="order",
                reference_id=order_code,
                created_at=now,
            )
        )


def _move_selected_items_to_ordered_cart(
    selected_rows: list[_SelectedCartRow],
    ordered_cart_id: int,
    now: datetime,
) -> None:
    for row in selected_rows:
        row.item.cart_id = ordered_cart_id
        row.item.updated_at = now


def _create_order_items(
    session: Session,
    order_id: int,
    selected_rows: list[_SelectedCartRow],
    now: datetime,
) -> None:
    for row in selected_rows:
        session.add(
            OrderItem(
                order_id=order_id,
                cart_item_id=row.item.id,
                product_id=row.product.id,
                seller_id=row.seller.id,
                product_name_snapshot=row.product.product_name,
                brand_name_snapshot=row.brand.name,
                seller_name_snapshot=row.seller.display_name,
                thumbnail_storage_key_snapshot=row.thumbnail_storage_key,
                unit_price=row.price.price,
                quantity=row.item.quantity,
                line_subtotal=row.line_subtotal,
                line_discount_amount=0,
                line_total=row.line_subtotal,
                currency=row.price.currency,
                status="ORDERED",
                source=row.item.source,
                recommendation_id=row.item.recommendation_id,
                recommendation_rank=row.item.recommendation_rank,
                created_at=now,
                updated_at=now,
            )
        )


def _create_shipping_address_snapshot(
    session: Session,
    order_id: int,
    snapshot: _ShippingAddressSnapshot,
) -> None:
    session.add(
        OrderShippingAddress(
            order_id=order_id,
            user_address_id=snapshot.user_address_id,
            recipient_name=snapshot.recipient_name,
            phone=snapshot.phone,
            postal_code=snapshot.postal_code,
            address1=snapshot.address1,
            address2=snapshot.address2,
            delivery_memo=snapshot.delivery_memo,
        )
    )


def _create_shipping_group_snapshots(
    session: Session,
    order_id: int,
    shipping_groups: list[_ShippingGroupSnapshot],
) -> None:
    for group in shipping_groups:
        session.add(
            OrderShippingGroup(
                order_id=order_id,
                seller_id=group.seller_id,
                seller_name_snapshot=group.seller_name_snapshot,
                item_subtotal=group.item_subtotal,
                shipping_fee=group.shipping_fee,
                free_shipping_threshold_snapshot=group.free_shipping_threshold_snapshot,
                shipping_policy_snapshot_json=group.shipping_policy_snapshot_json,
            )
        )


def _create_ready_payment(
    session: Session,
    order: Order,
    provider: str,
    now: datetime,
) -> None:
    session.add(
        Payment(
            payment_code=_generate_public_code("pay", now),
            order_id=order.id,
            provider=provider,
            status="READY",
            amount=order.total_amount,
            currency=order.currency,
            provider_order_id=order.order_code,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _to_order_response(session: Session, order: Order) -> OrderCreateResponse:
    payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    return OrderCreateResponse(
        order_code=order.order_code,
        status=order.status,
        payment=OrderPaymentSummary(
            payment_code=payment.payment_code,
            provider=payment.provider,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
        ),
        subtotal=order.subtotal_amount,
        shipping_fee=order.shipping_fee,
        discount_total=order.discount_amount,
        total=order.total_amount,
        currency=order.currency,
        payment_expires_at=order.payment_expires_at,
    )


def _available_quantity(inventory: Inventory) -> int:
    return max(
        inventory.stock_quantity - inventory.reserved_quantity - inventory.safety_stock,
        0,
    )


def _resolve_currency(selected_rows: list[_SelectedCartRow]) -> str:
    for row in selected_rows:
        if row.price.currency:
            return row.price.currency
    return DEFAULT_CURRENCY


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ApiError(400, "INVALID_SHIPPING_ADDRESS", f"{field_name} is required.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _generate_public_code(prefix: str, now: datetime) -> str:
    return f"{prefix}_{now.strftime('%Y%m%d')}_{secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8]}"


def _touch_cart(cart: Cart, now: datetime) -> None:
    cart.updated_at = now


def _log_order_create_completed(
    started_at: float,
    *,
    order: Order,
    payment_provider: str,
    requested_item_count: int,
    reserved_item_count: int,
    reserved_quantity_total: int,
    seller_count: int | None,
    idempotent_replay: bool,
) -> None:
    log_performance_event(
        "order_create_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "requested_item_count": requested_item_count,
            "selected_item_count": order.item_count,
            "reserved_item_count": reserved_item_count,
            "reserved_quantity_total": reserved_quantity_total,
            "seller_count": seller_count,
            "subtotal_amount": order.subtotal_amount,
            "shipping_fee": order.shipping_fee,
            "total_amount": order.total_amount,
            "payment_provider": payment_provider,
            "order_status": order.status,
            "idempotent_replay": idempotent_replay,
        },
    )


def _log_order_create_failed(
    started_at: float,
    *,
    error_code: str,
    requested_item_count: int,
    payment_provider: str,
) -> None:
    log_performance_event(
        "order_create_failed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "requested_item_count": requested_item_count,
            "payment_provider": payment_provider,
            "error_code": error_code,
        },
    )
