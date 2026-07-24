from collections.abc import Iterable

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models.catalog import ProductImage


MAX_PRODUCT_IMAGE_LOOKUP_IDS = 10_000


def load_thumbnail_storage_keys(
    session: Session,
    product_ids: Iterable[int],
) -> dict[int, str]:
    product_id_list = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if not product_id_list:
        return {}

    storage_keys_by_product_id: dict[int, str] = {}
    for chunk in _chunks(product_id_list, MAX_PRODUCT_IMAGE_LOOKUP_IDS):
        rows = session.execute(
            select(ProductImage.product_id, ProductImage.storage_key)
            .where(ProductImage.product_id.in_(chunk))
            .order_by(
                ProductImage.product_id.asc(),
                case((ProductImage.image_type == "thumbnail", 0), else_=1),
                ProductImage.display_order.asc(),
                ProductImage.id.asc(),
            )
        ).all()

        for product_id, storage_key in rows:
            storage_keys_by_product_id.setdefault(int(product_id), storage_key)
    return storage_keys_by_product_id


def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]
