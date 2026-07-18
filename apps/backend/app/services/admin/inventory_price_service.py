"""관리자 재고·가격 조회 서비스 (P1-M4, Chunk 1).

상품 기본 CRUD의 page 방식 목록과 분리해, 재고 운영에 필요한 cursor·파생 재고
상태·재고 이력만 제공한다. 읽기 전용 서비스이므로 transaction commit은 호출자가
필요로 하지 않는다.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, InventoryMovement, Seller
from app.schemas.admin.inventory_price import (
    AdminInventoryAdjustmentResponse,
    AdminInventoryHistoryResponse,
    AdminInventoryMovementItem,
    AdminInventoryPriceListItem,
    AdminInventoryPriceListResponse,
)
from app.schemas.admin.product import AdminProductAvailability
from app.schemas.common import ApiError
from app.services.product_availability import build_product_availability


DEFAULT_LIMIT = 50
MAX_LIMIT = 100
HISTORY_LIMIT = 20
INVENTORY_STOCK_MAX = 1_000_000

VALID_SALES_STATUS_FILTERS = frozenset({"ON_SALE", "SOLD_OUT", "HIDDEN"})
VALID_STOCK_STATUS_FILTERS = frozenset({"IN_STOCK", "LOW_STOCK", "SOLD_OUT", "HIDDEN"})
CURSOR_VERSION = 1


def list_admin_inventory_prices(
    session: Session,
    *,
    query: str | None,
    sales_status: str | None,
    stock_status: str | None,
    limit: int,
    cursor: str | None,
) -> AdminInventoryPriceListResponse:
    """재고·가격 운영 목록을 cursor 방식으로 반환한다.

    재고 행이 없는 기존 예외 상품은 목록에 ``UNKNOWN``으로 남긴다. 이는 운영자가
    데이터 이상을 확인할 수 있게 하기 위한 것이며, ``UNKNOWN`` 전용 필터는 제공하지
    않는다. 재고 저장은 Chunk 2에서 명시적으로 거절한다.
    """

    normalized_query = _normalize_query(query)
    normalized_sales_status = _normalize_sales_status(sales_status)
    normalized_stock_status = _normalize_stock_status(stock_status)
    normalized_limit = _normalize_limit(limit)
    cursor_timestamp, cursor_product_id = _decode_cursor(
        cursor,
        query=normalized_query,
        sales_status=normalized_sales_status,
        stock_status=normalized_stock_status,
    )

    statement, stock_status_sql = _base_statement()
    if normalized_query:
        statement = statement.where(Product.product_name.ilike(f"%{normalized_query}%"))
    if normalized_sales_status:
        statement = statement.where(Inventory.sales_status == normalized_sales_status)
    if normalized_stock_status:
        statement = statement.where(stock_status_sql == normalized_stock_status)
    if cursor_timestamp is not None and cursor_product_id is not None:
        statement = statement.where(
            or_(
                Product.updated_at < cursor_timestamp,
                (Product.updated_at == cursor_timestamp) & (Product.id < cursor_product_id),
            )
        )

    rows = session.execute(
        statement.order_by(Product.updated_at.desc(), Product.id.desc()).limit(normalized_limit + 1)
    ).all()
    visible_rows = list(rows[:normalized_limit])
    prices_by_product_id = _load_first_party_prices(session, visible_rows)
    items = [
        _to_list_item(row, price=prices_by_product_id.get(int(row.product_db_id)))
        for row in visible_rows
    ]
    next_cursor = (
        _encode_cursor(
            visible_rows[-1],
            query=normalized_query,
            sales_status=normalized_sales_status,
            stock_status=normalized_stock_status,
        )
        if len(rows) > normalized_limit and visible_rows
        else None
    )
    return AdminInventoryPriceListResponse(items=items, next_cursor=next_cursor)


def get_admin_inventory_history(session: Session, *, product_code: str) -> AdminInventoryHistoryResponse:
    """선택 상품의 실제 재고 변동 이력 최신 20건을 반환한다.

    관리자 조정뿐 아니라 주문 예약·결제·취소가 만든 ``InventoryMovement``도 함께
    반환해, 현재 재고가 바뀐 이유를 운영자가 확인할 수 있게 한다.
    """

    normalized_code = product_code.strip()
    product = session.execute(select(Product).where(Product.product_code == normalized_code)).scalar_one_or_none()
    if product is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")

    rows = session.execute(
        select(InventoryMovement)
        .where(InventoryMovement.product_id == product.id)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(HISTORY_LIMIT)
    ).scalars()
    return AdminInventoryHistoryResponse(
        product_code=product.product_code,
        items=[
            AdminInventoryMovementItem(
                movement_type=row.movement_type,
                quantity_delta=row.quantity_delta,
                stock_after=row.stock_after,
                reason=row.reason,
                reference_type=row.reference_type,
                reference_id=row.reference_id,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


def adjust_admin_inventory(
    session: Session,
    *,
    product_code: str,
    stock_quantity: int,
    reason: str,
    now: datetime | None = None,
) -> AdminInventoryAdjustmentResponse:
    """관리자 재고를 절대 수량으로 조정하고 ``ADMIN_ADJUST`` 이력을 남긴다.

    주문·결제·취소·환불과 같은 ``Inventory FOR UPDATE`` 잠금을 사용한다. 이 함수는
    flush까지만 수행하며 commit과 ES 동기화는 라우트 책임이다.
    """

    normalized_code = product_code.strip()
    product = session.execute(select(Product).where(Product.product_code == normalized_code)).scalar_one_or_none()
    if product is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다.")

    inventory = session.execute(
        select(Inventory).where(Inventory.product_id == product.id).with_for_update()
    ).scalar_one_or_none()
    if inventory is None:
        raise ApiError(404, "INVENTORY_ROW_NOT_FOUND", "상품의 재고 행을 찾을 수 없습니다.")

    normalized_stock_quantity = _normalize_adjusted_stock_quantity(stock_quantity)
    normalized_reason = _normalize_adjustment_reason(reason)
    previous_stock_quantity = int(inventory.stock_quantity)
    availability = _availability_for_inventory(inventory)

    if normalized_stock_quantity == previous_stock_quantity:
        return AdminInventoryAdjustmentResponse(
            changed=False,
            product_code=product.product_code,
            stock_quantity=previous_stock_quantity,
            reserved_quantity=int(inventory.reserved_quantity),
            safety_stock=int(inventory.safety_stock),
            availability=availability,
            updated_at=inventory.updated_at,
            movement=None,
        )

    if normalized_stock_quantity - int(inventory.reserved_quantity) - int(inventory.safety_stock) < 0:
        raise ApiError(
            409,
            "INVENTORY_AVAILABLE_QUANTITY_NEGATIVE",
            "예약 수량과 안전 재고보다 낮게 재고를 설정할 수 없습니다.",
        )

    timestamp = now or datetime.now(UTC)
    inventory.stock_quantity = normalized_stock_quantity
    inventory.updated_at = timestamp
    movement = InventoryMovement(
        inventory_id=inventory.id,
        product_id=product.id,
        movement_type="ADMIN_ADJUST",
        quantity_delta=normalized_stock_quantity - previous_stock_quantity,
        stock_after=normalized_stock_quantity,
        reason=normalized_reason,
        reference_type="admin_inventory",
        reference_id=product.product_code,
        created_at=timestamp,
    )
    session.add(movement)
    session.flush()

    return AdminInventoryAdjustmentResponse(
        changed=True,
        product_code=product.product_code,
        stock_quantity=normalized_stock_quantity,
        reserved_quantity=int(inventory.reserved_quantity),
        safety_stock=int(inventory.safety_stock),
        availability=_availability_for_inventory(inventory),
        updated_at=inventory.updated_at,
        movement=AdminInventoryMovementItem(
            movement_type=movement.movement_type,
            quantity_delta=movement.quantity_delta,
            stock_after=movement.stock_after,
            reason=movement.reason,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            created_at=movement.created_at,
        ),
    )


def _base_statement() -> tuple[Any, Any]:
    """재고 운영용 페이지 조회 query와 파생 재고 상태 SQL을 만든다.

    가격은 페이지에 포함된 상품 ID만 별도 조회한다. 전체 ``product_prices``를 먼저
    집계하면 50개 목록을 위해 수만 행을 매번 읽게 되기 때문이다.
    """

    raw_available_quantity = (
        Inventory.stock_quantity - Inventory.reserved_quantity - Inventory.safety_stock
    )
    available_quantity = case(
        (raw_available_quantity < 0, 0),
        else_=raw_available_quantity,
    )
    # build_product_availability()과 같은 우선순위다. SQL 필터에는 DB 조건식이 필요해
    # 아래 표현을 쓰고, 최종 응답은 반드시 공통 Python 함수로 계산한다.
    stock_status = case(
        (Inventory.id.is_(None), "UNKNOWN"),
        (Inventory.sales_status == "HIDDEN", "HIDDEN"),
        (
            or_(Inventory.sales_status == "SOLD_OUT", available_quantity <= 0),
            "SOLD_OUT",
        ),
        (available_quantity <= 5, "LOW_STOCK"),
        else_="IN_STOCK",
    )
    statement = (
        select(
            Product.id.label("product_db_id"),
            Product.product_code,
            Product.product_name,
            Product.is_active,
            Product.updated_at,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            Seller.display_name.label("seller_name"),
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
    )
    return statement, stock_status


def _load_first_party_prices(session: Session, rows: list[Any]) -> dict[int, int]:
    if not rows:
        return {}
    seller_name_by_product_id = {
        int(row.product_db_id): str(row.seller_name)
        for row in rows
    }
    price_rows = session.execute(
        select(ProductPrice.product_id, ProductPrice.mall_name, ProductPrice.price)
        .where(
            ProductPrice.product_id.in_(seller_name_by_product_id),
            ProductPrice.currency == "KRW",
            ProductPrice.is_lowest.is_(True),
        )
    ).all()
    prices: dict[int, int] = {}
    for row in price_rows:
        product_id = int(row.product_id)
        if row.mall_name != seller_name_by_product_id.get(product_id):
            continue
        price = int(row.price)
        existing = prices.get(product_id)
        prices[product_id] = price if existing is None else min(existing, price)
    return prices


def _to_list_item(row: Any, *, price: int | None) -> AdminInventoryPriceListItem:
    availability = build_product_availability(
        inventory_exists=row.inventory_id is not None,
        sales_status=row.sales_status,
        stock_quantity=row.stock_quantity,
        reserved_quantity=row.reserved_quantity,
        safety_stock=row.safety_stock,
    )
    return AdminInventoryPriceListItem(
        product_code=row.product_code,
        name=row.product_name,
        brand_code=row.brand_code,
        brand=row.brand_name,
        category_code=row.category_code,
        category_name=row.category_name,
        is_active=row.is_active,
        price=price,
        stock_quantity=row.stock_quantity,
        reserved_quantity=row.reserved_quantity,
        safety_stock=row.safety_stock,
        availability=AdminProductAvailability(
            sales_status=availability.sales_status,
            stock_status=availability.stock_status,
            available_quantity=availability.available_quantity,
            in_stock=availability.in_stock,
        ),
        updated_at=row.updated_at,
    )


def _availability_for_inventory(inventory: Inventory) -> AdminProductAvailability:
    availability = build_product_availability(
        inventory_exists=True,
        sales_status=inventory.sales_status,
        stock_quantity=inventory.stock_quantity,
        reserved_quantity=inventory.reserved_quantity,
        safety_stock=inventory.safety_stock,
    )
    return AdminProductAvailability(
        sales_status=availability.sales_status,
        stock_status=availability.stock_status,
        available_quantity=availability.available_quantity,
        in_stock=availability.in_stock,
    )


def _normalize_adjusted_stock_quantity(stock_quantity: int) -> int:
    if isinstance(stock_quantity, bool) or not isinstance(stock_quantity, int):
        raise ApiError(400, "INVALID_INVENTORY_STOCK", "재고는 0 이상 1,000,000 이하의 정수여야 합니다.")
    if stock_quantity < 0 or stock_quantity > INVENTORY_STOCK_MAX:
        raise ApiError(400, "INVALID_INVENTORY_STOCK", "재고는 0 이상 1,000,000 이하의 정수여야 합니다.")
    return stock_quantity


def _normalize_adjustment_reason(reason: str) -> str:
    normalized = reason.strip() if isinstance(reason, str) else ""
    if not normalized or len(normalized) > 500:
        raise ApiError(400, "INVALID_INVENTORY_ADJUSTMENT_REASON", "재고 조정 사유는 1~500자로 입력해 주세요.")
    return normalized


def _normalize_query(query: str | None) -> str:
    return (query or "").strip()


def _normalize_sales_status(sales_status: str | None) -> str | None:
    if sales_status is None or not sales_status.strip():
        return None
    normalized = sales_status.strip().upper()
    if normalized not in VALID_SALES_STATUS_FILTERS:
        raise ApiError(400, "INVALID_INVENTORY_SALES_STATUS", "유효하지 않은 판매 상태입니다.")
    return normalized


def _normalize_stock_status(stock_status: str | None) -> str | None:
    if stock_status is None or not stock_status.strip():
        return None
    normalized = stock_status.strip().upper()
    if normalized not in VALID_STOCK_STATUS_FILTERS:
        raise ApiError(400, "INVALID_INVENTORY_STOCK_STATUS", "유효하지 않은 재고 상태입니다.")
    return normalized


def _normalize_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError(400, "INVALID_LIMIT", "limit은 1 이상 100 이하여야 합니다.")
    return limit


def _encode_cursor(
    row: Any,
    *,
    query: str,
    sales_status: str | None,
    stock_status: str | None,
) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "u": row.updated_at.isoformat(),
        "id": int(row.product_db_id),
        "q": query,
        "ss": sales_status or "",
        "ts": stock_status or "",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(
    cursor: str | None,
    *,
    query: str,
    sales_status: str | None,
    stock_status: str | None,
) -> tuple[datetime | None, int | None]:
    if cursor is None or not cursor.strip():
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(f"{cursor}{padding}".encode("ascii")))
        timestamp = datetime.fromisoformat(payload["u"])
        product_id = int(payload["id"])
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "유효하지 않은 cursor입니다.") from exc

    if (
        not isinstance(payload, dict)
        or payload.get("v") != CURSOR_VERSION
        or product_id <= 0
        or payload.get("q") != query
        or payload.get("ss") != (sales_status or "")
        or payload.get("ts") != (stock_status or "")
    ):
        raise ApiError(400, "INVALID_CURSOR", "유효하지 않은 cursor입니다.")
    return timestamp, product_id
