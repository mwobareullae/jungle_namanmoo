"""상품 대표 이미지와 검색용 thumbnail_url을 함께 관리하는 공용 서비스."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductImage
from app.schemas.common import ApiError


MAX_STORAGE_KEY_LENGTH = 500
THUMBNAIL_IMAGE_TYPE = "thumbnail"
THUMBNAIL_DISPLAY_ORDER = 0
_ABSOLUTE_URL_PATTERN = re.compile(r"^[a-z][a-z\d+.-]*://", re.IGNORECASE)


def normalize_thumbnail_storage_key(value: str | None) -> str | None:
    """M3-A 대표 이미지 입력을 상대 storage_key로 정규화한다."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_STORAGE_KEY_LENGTH:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", "Invalid thumbnail_storage_key.")
    if _ABSOLUTE_URL_PATTERN.match(normalized):
        raise ApiError(
            400,
            "INVALID_PRODUCT_FIELD",
            "thumbnail_storage_key must be a storage key, not an absolute URL.",
        )
    if ".." in normalized:
        raise ApiError(400, "INVALID_PRODUCT_FIELD", "thumbnail_storage_key must not contain '..'.")
    return normalized


def set_product_thumbnail(session: Session, product: Product, storage_key: str | None) -> bool:
    """대표 ProductImage와 Product.thumbnail_url을 동기화하고 flush한다.

    commit·rollback·재색인은 호출자 책임이다. 반환값은 실제 저장 상태가 바뀌었는지다.
    """
    existing = session.execute(
        select(ProductImage)
        .where(
            ProductImage.product_id == product.id,
            ProductImage.image_type == THUMBNAIL_IMAGE_TYPE,
            ProductImage.display_order == THUMBNAIL_DISPLAY_ORDER,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if storage_key is None:
        changed = existing is not None or product.thumbnail_url is not None
        if existing is not None:
            session.delete(existing)
        product.thumbnail_url = None
        session.flush()
        return changed

    changed = (
        existing is None
        or existing.storage_key != storage_key
        or product.thumbnail_url != storage_key
    )
    if existing is None:
        session.add(
            ProductImage(
                product_id=product.id,
                image_type=THUMBNAIL_IMAGE_TYPE,
                display_order=THUMBNAIL_DISPLAY_ORDER,
                storage_key=storage_key,
            )
        )
    else:
        existing.storage_key = storage_key
    product.thumbnail_url = storage_key

    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ApiError(
            409,
            "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT",
            "이미 같은 storage_key를 사용하는 이미지가 있습니다.",
        ) from exc
    return changed
