from collections.abc import Iterable

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models.catalog import ProductImage


def load_thumbnail_storage_keys(
    session: Session,
    product_ids: Iterable[int],
) -> dict[int, str]:
    product_id_list = [int(product_id) for product_id in product_ids]
    if not product_id_list:
        return {}

    rows = session.execute(
        select(ProductImage.product_id, ProductImage.storage_key)
        .where(ProductImage.product_id.in_(product_id_list))
        .order_by(
            ProductImage.product_id.asc(),
            case((ProductImage.image_type == "thumbnail", 0), else_=1),
            ProductImage.display_order.asc(),
            ProductImage.id.asc(),
        )
    ).all()

    storage_keys_by_product_id: dict[int, str] = {}
    for product_id, storage_key in rows:
        storage_keys_by_product_id.setdefault(int(product_id), storage_key)
    return storage_keys_by_product_id
