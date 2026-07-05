from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Cart, CartItem, Inventory, Seller, SellerShippingPolicy
from app.schemas.cart import (
    CartItem as CartItemSchema,
    CartMergeResponse,
    CartProduct,
    CartResponse,
    CartWarning,
    CheckoutShippingGroup,
    CheckoutPreviewResponse,
)
from app.schemas.common import ApiError
from app.services.product_image_service import load_thumbnail_storage_keys


ANONYMOUS_CART_COOKIE_NAME = "mwbl_cart"
ANONYMOUS_CART_TTL_DAYS = 30
CART_STATUS_ACTIVE = "ACTIVE"
CART_STATUS_MERGED = "MERGED"
MAX_CART_ITEM_QUANTITY = 99
DEFAULT_CART_CURRENCY = "KRW"
DEFAULT_BASE_SHIPPING_FEE = 3000


@dataclass(frozen=True)
class CartOperationResult:
    cart: CartResponse
    anonymous_cart_id: str | None = None


@dataclass(frozen=True)
class _PurchaseState:
    product: Product
    brand: Brand
    category: ProductCategory
    seller: Seller
    price: ProductPrice | None
    inventory: Inventory | None
    thumbnail_url: str

    @property
    def current_price(self) -> int | None:
        return self.price.price if self.price is not None else None

    @property
    def currency(self) -> str:
        return self.price.currency if self.price is not None else DEFAULT_CART_CURRENCY

    @property
    def sales_status(self) -> str:
        return self.inventory.sales_status if self.inventory is not None else "UNKNOWN"

    @property
    def available_quantity(self) -> int | None:
        if self.inventory is None:
            return None
        return max(
            self.inventory.stock_quantity - self.inventory.reserved_quantity - self.inventory.safety_stock,
            0,
        )

    @property
    def stock_status(self) -> str:
        available = self.available_quantity
        if self.inventory is None:
            return "UNKNOWN"
        if self.inventory.sales_status == "HIDDEN":
            return "HIDDEN"
        if self.inventory.sales_status == "SOLD_OUT" or available is None or available <= 0:
            return "SOLD_OUT"
        if available <= 5:
            return "LOW_STOCK"
        return "IN_STOCK"

    def can_purchase_quantity(self, quantity: int) -> bool:
        available = self.available_quantity
        return (
            self.product.is_active
            and self.brand.is_active
            and self.category.is_active
            and self.seller.status == "ACTIVE"
            and self.current_price is not None
            and self.sales_status == "ON_SALE"
            and available is not None
            and available >= quantity
        )


def get_cart_response(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
) -> CartResponse:
    cart = _load_active_cart(session, user, anonymous_cart_id)
    if cart is None:
        return _empty_cart_response(user)
    return _build_cart_response(session, cart, user)


def add_cart_item(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
    *,
    product_code: str,
    quantity: int,
    source: str | None,
    recommendation_id: str | None,
    recommendation_rank: int | None,
) -> CartOperationResult:
    state = _load_purchase_state(session, product_code)
    _raise_if_not_purchasable(state, quantity)

    cart, issued_anonymous_cart_id = _ensure_active_cart(session, user, anonymous_cart_id)
    now = datetime.now(UTC)
    existing = session.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == state.product.id,
        )
    ).scalar_one_or_none()

    if existing is None:
        item = CartItem(
            cart_id=cart.id,
            product_id=state.product.id,
            seller_id=state.seller.id,
            quantity=quantity,
            unit_price_snapshot=state.current_price or 0,
            currency=state.currency,
            source=source,
            recommendation_id=recommendation_id,
            recommendation_rank=recommendation_rank,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
    else:
        next_quantity = min(existing.quantity + quantity, MAX_CART_ITEM_QUANTITY)
        _raise_if_not_purchasable(state, next_quantity)
        existing.quantity = next_quantity
        existing.seller_id = state.seller.id
        existing.unit_price_snapshot = state.current_price or existing.unit_price_snapshot
        existing.currency = state.currency
        existing.source = source or existing.source
        existing.recommendation_id = recommendation_id or existing.recommendation_id
        existing.recommendation_rank = recommendation_rank or existing.recommendation_rank
        existing.updated_at = now

    _touch_cart(cart, now)
    session.flush()
    return CartOperationResult(
        cart=_build_cart_response(session, cart, user),
        anonymous_cart_id=issued_anonymous_cart_id,
    )


def update_cart_item_quantity(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
    *,
    item_id: int,
    quantity: int,
) -> CartResponse:
    cart = _require_active_cart(session, user, anonymous_cart_id)
    item = _load_cart_item(session, cart, item_id)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "Cart item was not found.")

    if quantity == 0:
        session.delete(item)
    else:
        state = _load_purchase_state_by_product_id(session, item.product_id)
        _raise_if_not_purchasable(state, quantity)
        item.quantity = quantity
        item.seller_id = state.seller.id
        item.currency = state.currency
        item.updated_at = datetime.now(UTC)

    _touch_cart(cart)
    session.flush()
    return _build_cart_response(session, cart, user)


def remove_cart_item(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
    *,
    item_id: int,
) -> CartResponse:
    cart = _load_active_cart(session, user, anonymous_cart_id)
    if cart is None:
        return _empty_cart_response(user)

    item = _load_cart_item(session, cart, item_id)
    if item is not None:
        session.delete(item)
        _touch_cart(cart)
        session.flush()
    return _build_cart_response(session, cart, user)


def merge_anonymous_cart(
    session: Session,
    user: User,
    anonymous_cart_id: str | None,
) -> CartMergeResponse:
    if not anonymous_cart_id:
        return CartMergeResponse(
            merged=False,
            cart=get_cart_response(session, user, None),
        )

    anonymous_cart = _load_active_anonymous_cart(session, anonymous_cart_id)
    if anonymous_cart is None:
        return CartMergeResponse(
            merged=False,
            cart=get_cart_response(session, user, None),
        )

    user_cart = _load_active_user_cart(session, user.id)
    now = datetime.now(UTC)
    if user_cart is None:
        anonymous_cart.user_id = user.id
        anonymous_cart.anonymous_cart_id = None
        anonymous_cart.expires_at = None
        _touch_cart(anonymous_cart, now)
        session.flush()
        return CartMergeResponse(
            merged=True,
            cart=_build_cart_response(session, anonymous_cart, user),
        )

    _merge_cart_items(session, source_cart=anonymous_cart, target_cart=user_cart, now=now)
    anonymous_cart.status = CART_STATUS_MERGED
    anonymous_cart.merged_into_cart_id = user_cart.id
    _touch_cart(anonymous_cart, now)
    _touch_cart(user_cart, now)
    session.flush()
    return CartMergeResponse(
        merged=True,
        cart=_build_cart_response(session, user_cart, user),
    )


def get_checkout_preview(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
) -> CheckoutPreviewResponse:
    cart = _require_active_cart(session, user, anonymous_cart_id)
    cart_response = _build_cart_response(session, cart, user)
    if not cart_response.items:
        raise ApiError(400, "EMPTY_CART", "Cart is empty.")

    shipping_groups = _build_shipping_groups(session, cart, cart_response.items)
    shipping_fee = sum(group.shipping_fee for group in shipping_groups)
    can_checkout = not any(warning.severity == "BLOCKING" for warning in cart_response.warnings)
    return CheckoutPreviewResponse(
        cart_id=cart.id,
        items=cart_response.items,
        subtotal=cart_response.subtotal,
        shipping_fee=shipping_fee,
        shipping_groups=shipping_groups,
        total=cart_response.subtotal + shipping_fee,
        currency=cart_response.currency,
        can_checkout=can_checkout,
        warnings=cart_response.warnings,
    )


def _ensure_active_cart(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
) -> tuple[Cart, str | None]:
    existing = _load_active_cart(session, user, anonymous_cart_id)
    if existing is not None:
        return existing, None

    now = datetime.now(UTC)
    if user is not None:
        cart = Cart(
            user_id=user.id,
            status=CART_STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        session.add(cart)
        session.flush()
        return cart, None

    issued_anonymous_cart_id = anonymous_cart_id or secrets.token_urlsafe(32)
    cart = Cart(
        anonymous_cart_id=issued_anonymous_cart_id,
        status=CART_STATUS_ACTIVE,
        expires_at=now + timedelta(days=ANONYMOUS_CART_TTL_DAYS),
        created_at=now,
        updated_at=now,
    )
    session.add(cart)
    session.flush()
    return cart, issued_anonymous_cart_id


def _require_active_cart(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
) -> Cart:
    cart = _load_active_cart(session, user, anonymous_cart_id)
    if cart is None:
        raise ApiError(400, "EMPTY_CART", "Cart is empty.")
    return cart


def _load_active_cart(
    session: Session,
    user: User | None,
    anonymous_cart_id: str | None,
) -> Cart | None:
    if user is not None:
        return _load_active_user_cart(session, user.id)
    if anonymous_cart_id:
        return _load_active_anonymous_cart(session, anonymous_cart_id)
    return None


def _load_active_user_cart(session: Session, user_id: int) -> Cart | None:
    return session.execute(
        select(Cart)
        .where(
            Cart.user_id == user_id,
            Cart.status == CART_STATUS_ACTIVE,
        )
        .order_by(Cart.updated_at.desc(), Cart.id.desc())
    ).scalars().first()


def _load_active_anonymous_cart(session: Session, anonymous_cart_id: str) -> Cart | None:
    now = datetime.now(UTC)
    return session.execute(
        select(Cart)
        .where(
            Cart.anonymous_cart_id == anonymous_cart_id,
            Cart.status == CART_STATUS_ACTIVE,
            (Cart.expires_at.is_(None) | (Cart.expires_at > now)),
        )
        .order_by(Cart.updated_at.desc(), Cart.id.desc())
    ).scalars().first()


def _load_cart_item(session: Session, cart: Cart, item_id: int) -> CartItem | None:
    return session.execute(
        select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id,
        )
    ).scalar_one_or_none()


def _merge_cart_items(
    session: Session,
    *,
    source_cart: Cart,
    target_cart: Cart,
    now: datetime,
) -> None:
    source_items = session.execute(
        select(CartItem).where(CartItem.cart_id == source_cart.id)
    ).scalars().all()
    target_items = {
        item.product_id: item
        for item in session.execute(
            select(CartItem).where(CartItem.cart_id == target_cart.id)
        ).scalars()
    }

    for source_item in source_items:
        target_item = target_items.get(source_item.product_id)
        if target_item is None:
            source_item.cart_id = target_cart.id
            source_item.updated_at = now
            target_items[source_item.product_id] = source_item
            continue
        target_item.quantity = min(
            target_item.quantity + source_item.quantity,
            MAX_CART_ITEM_QUANTITY,
        )
        target_item.updated_at = now
        session.delete(source_item)


def _build_cart_response(session: Session, cart: Cart, user: User | None) -> CartResponse:
    rows = session.execute(
        select(CartItem, Product, Brand, ProductCategory, Seller)
        .join(Product, CartItem.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, CartItem.seller_id == Seller.id)
        .where(CartItem.cart_id == cart.id)
        .order_by(CartItem.created_at.asc(), CartItem.id.asc())
    ).all()

    product_ids = [int(product.id) for _, product, _, _, _ in rows]
    thumbnails = load_thumbnail_storage_keys(session, product_ids)
    prices = _load_primary_prices(session, product_ids)
    inventories = _load_inventories(session, product_ids)

    items: list[CartItemSchema] = []
    warnings: list[CartWarning] = []
    for item, product, brand, category, seller in rows:
        state = _PurchaseState(
            product=product,
            brand=brand,
            category=category,
            seller=seller,
            price=prices.get(int(product.id)),
            inventory=inventories.get(int(product.id)),
            thumbnail_url=thumbnails.get(int(product.id), ""),
        )
        schema_item = _to_cart_item_schema(item, state)
        items.append(schema_item)
        warnings.extend(_build_item_warnings(schema_item, state))

    return CartResponse(
        cart_id=cart.id,
        owner_type="user" if user is not None else "anonymous",
        items=items,
        total_quantity=sum(item.quantity for item in items),
        subtotal=sum(item.line_subtotal for item in items),
        currency=_resolve_cart_currency(items),
        warnings=warnings,
    )


def _build_shipping_groups(
    session: Session,
    cart: Cart,
    items: list[CartItemSchema],
) -> list[CheckoutShippingGroup]:
    if not items:
        return []

    item_subtotals = {item.id: item.line_subtotal for item in items}
    rows = session.execute(
        select(CartItem.id, Seller.id, Seller.seller_code, Seller.display_name)
        .join(Seller, CartItem.seller_id == Seller.id)
        .where(CartItem.cart_id == cart.id)
        .order_by(Seller.id.asc(), CartItem.id.asc())
    ).all()

    subtotals_by_seller_id: dict[int, int] = {}
    seller_payloads: dict[int, tuple[str, str]] = {}
    for item_id, seller_id, seller_code, seller_name in rows:
        seller_id = int(seller_id)
        subtotals_by_seller_id[seller_id] = subtotals_by_seller_id.get(seller_id, 0) + item_subtotals.get(
            int(item_id),
            0,
        )
        seller_payloads[seller_id] = (seller_code, seller_name)

    policies = _load_shipping_policies(session, list(subtotals_by_seller_id))
    groups: list[CheckoutShippingGroup] = []
    for seller_id, item_subtotal in subtotals_by_seller_id.items():
        seller_code, seller_name = seller_payloads[seller_id]
        policy = policies.get(seller_id)
        base_shipping_fee = policy.base_shipping_fee if policy else DEFAULT_BASE_SHIPPING_FEE
        free_shipping_threshold = policy.free_shipping_threshold if policy else None
        shipping_fee = (
            0
            if free_shipping_threshold is not None and item_subtotal >= free_shipping_threshold
            else base_shipping_fee
        )
        groups.append(
            CheckoutShippingGroup(
                seller_code=seller_code,
                seller_name=seller_name,
                item_subtotal=item_subtotal,
                base_shipping_fee=base_shipping_fee,
                free_shipping_threshold=free_shipping_threshold,
                shipping_fee=shipping_fee,
            )
        )
    return groups


def _load_shipping_policies(
    session: Session,
    seller_ids: list[int],
) -> dict[int, SellerShippingPolicy]:
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


def _empty_cart_response(user: User | None) -> CartResponse:
    return CartResponse(
        cart_id=None,
        owner_type="user" if user is not None else "anonymous",
        items=[],
        total_quantity=0,
        subtotal=0,
        currency=DEFAULT_CART_CURRENCY,
        warnings=[],
    )


def _to_cart_item_schema(item: CartItem, state: _PurchaseState) -> CartItemSchema:
    current_price = state.current_price
    line_subtotal = (current_price or item.unit_price_snapshot) * item.quantity
    return CartItemSchema(
        id=item.id,
        product_id=state.product.product_code,
        quantity=item.quantity,
        unit_price_snapshot=item.unit_price_snapshot,
        current_unit_price=current_price,
        currency=state.currency,
        line_subtotal=line_subtotal,
        price_changed=current_price is not None and current_price != item.unit_price_snapshot,
        source=item.source,
        recommendation_id=item.recommendation_id,
        recommendation_rank=item.recommendation_rank,
        added_at=item.created_at,
        updated_at=item.updated_at,
        product=CartProduct(
            product_id=state.product.product_code,
            brand=state.brand.name,
            name=state.product.product_name,
            category_code=state.category.category_code,
            category_name=state.category.name,
            thumbnail_url=state.thumbnail_url,
            current_price=current_price,
            currency=state.currency,
            sales_status=state.sales_status,
            stock_status=state.stock_status,
            available_quantity=state.available_quantity,
        ),
    )


def _build_item_warnings(item: CartItemSchema, state: _PurchaseState) -> list[CartWarning]:
    warnings: list[CartWarning] = []
    if item.price_changed:
        warnings.append(
            CartWarning(
                code="PRICE_CHANGED",
                message="Product price changed after it was added to the cart.",
                severity="INFO",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    if not state.product.is_active or not state.brand.is_active or not state.category.is_active:
        warnings.append(
            CartWarning(
                code="PRODUCT_UNAVAILABLE",
                message="Product is no longer available.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    if state.seller.status != "ACTIVE":
        warnings.append(
            CartWarning(
                code="SELLER_UNAVAILABLE",
                message="Seller is no longer available.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    if state.current_price is None:
        warnings.append(
            CartWarning(
                code="PRICE_UNAVAILABLE",
                message="Product price is unavailable.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    if state.sales_status != "ON_SALE":
        warnings.append(
            CartWarning(
                code="NOT_ON_SALE",
                message="Product is not on sale.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    available = state.available_quantity
    if available is None:
        warnings.append(
            CartWarning(
                code="STOCK_UNKNOWN",
                message="Product stock is unavailable.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    elif available <= 0:
        warnings.append(
            CartWarning(
                code="OUT_OF_STOCK",
                message="Product is out of stock.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    elif available < item.quantity:
        warnings.append(
            CartWarning(
                code="INSUFFICIENT_STOCK",
                message="Cart quantity is greater than available stock.",
                severity="BLOCKING",
                product_id=item.product_id,
                item_id=item.id,
            )
        )
    return warnings


def _load_purchase_state(session: Session, product_code: str) -> _PurchaseState:
    row = session.execute(
        select(Product, Brand, ProductCategory, Seller)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .where(Product.product_code == product_code)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Product was not found.")

    product, brand, category, seller = row
    thumbnails = load_thumbnail_storage_keys(session, [product.id])
    return _PurchaseState(
        product=product,
        brand=brand,
        category=category,
        seller=seller,
        price=_load_primary_price(session, product.id),
        inventory=_load_inventory(session, product.id),
        thumbnail_url=thumbnails.get(int(product.id), ""),
    )


def _load_purchase_state_by_product_id(session: Session, product_id: int) -> _PurchaseState:
    product_code = session.execute(
        select(Product.product_code).where(Product.id == product_id)
    ).scalar_one_or_none()
    if product_code is None:
        raise ApiError(404, "NOT_FOUND", "Product was not found.")
    return _load_purchase_state(session, product_code)


def _raise_if_not_purchasable(state: _PurchaseState, quantity: int) -> None:
    if not state.product.is_active or not state.brand.is_active or not state.category.is_active:
        raise ApiError(409, "PRODUCT_UNAVAILABLE", "Product is not available.")
    if state.seller.status != "ACTIVE":
        raise ApiError(409, "SELLER_UNAVAILABLE", "Seller is not available.")
    if state.current_price is None:
        raise ApiError(409, "PRICE_UNAVAILABLE", "Product price is unavailable.")
    available = state.available_quantity
    if available is None:
        raise ApiError(409, "STOCK_UNKNOWN", "Product stock is unavailable.")
    if state.sales_status != "ON_SALE":
        raise ApiError(409, "NOT_ON_SALE", "Product is not on sale.")
    if available <= 0:
        raise ApiError(409, "OUT_OF_STOCK", "Product is out of stock.")
    if available < quantity:
        raise ApiError(409, "INSUFFICIENT_STOCK", "Requested quantity exceeds available stock.")


def _load_primary_price(session: Session, product_id: int) -> ProductPrice | None:
    return session.execute(
        select(ProductPrice)
        .where(ProductPrice.product_id == product_id)
        .order_by(ProductPrice.is_lowest.desc(), ProductPrice.price.asc(), ProductPrice.id.asc())
    ).scalars().first()


def _load_primary_prices(session: Session, product_ids: list[int]) -> dict[int, ProductPrice]:
    if not product_ids:
        return {}
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


def _load_inventory(session: Session, product_id: int) -> Inventory | None:
    return session.execute(
        select(Inventory).where(Inventory.product_id == product_id)
    ).scalar_one_or_none()


def _load_inventories(session: Session, product_ids: list[int]) -> dict[int, Inventory]:
    if not product_ids:
        return {}
    rows = session.execute(
        select(Inventory).where(Inventory.product_id.in_(product_ids))
    ).scalars()
    return {int(row.product_id): row for row in rows}


def _resolve_cart_currency(items: list[CartItemSchema]) -> str:
    for item in items:
        if item.currency:
            return item.currency
    return DEFAULT_CART_CURRENCY


def _touch_cart(cart: Cart, now: datetime | None = None) -> None:
    cart.updated_at = now or datetime.now(UTC)
