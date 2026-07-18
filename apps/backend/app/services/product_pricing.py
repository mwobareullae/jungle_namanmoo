"""자사 운영몰 가격 행의 조회·생성 공통 규칙."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductPrice
from app.schemas.common import ApiError


MAX_PRODUCT_PRICE = 100_000_000


def build_product_url(product_code: str) -> str:
    """자사 상품 상세 URL을 결정적으로 만든다."""

    return f"/product-detail?id={quote(product_code, safe='')}"


def load_first_party_price_for_update(
    session: Session,
    *,
    product_id: int,
    mall_name: str,
) -> ProductPrice | None:
    """자사 가격 행을 잠그고, 중복 데이터는 명시적으로 거절한다."""

    rows = session.execute(
        select(ProductPrice)
        .where(ProductPrice.product_id == product_id, ProductPrice.mall_name == mall_name)
        .with_for_update()
    ).scalars().all()
    if len(rows) > 1:
        raise ApiError(409, "PRODUCT_PRICE_INCONSISTENT", "자사몰 가격 행이 중복되어 있습니다.")
    return rows[0] if rows else None


def get_or_create_first_party_price_for_update(
    session: Session,
    *,
    product: Product,
    mall_name: str,
    price: int,
    timestamp: datetime,
) -> tuple[ProductPrice, bool]:
    """잠근 자사 가격 행을 반환하고, 없으면 M3-A 규칙으로 생성한다."""

    price_row = load_first_party_price_for_update(
        session,
        product_id=product.id,
        mall_name=mall_name,
    )
    if price_row is not None:
        return price_row, False

    price_row = ProductPrice(
        product_id=product.id,
        mall_name=mall_name,
        price=price,
        currency="KRW",
        product_url=build_product_url(product.product_code),
        is_lowest=True,
        collected_at=timestamp,
    )
    session.add(price_row)
    return price_row, True
