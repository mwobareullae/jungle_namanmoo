from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import RecentView, Wishlist
from app.schemas.common import ApiError
from app.schemas.user_activity import (
    RecentViewItem,
    RecentViewsResponse,
    UserActivityProduct,
    WishlistItem,
    WishlistResponse,
)
from app.services.product_image_service import load_thumbnail_storage_keys


DEFAULT_ACTIVITY_LIMIT = 50
MAX_ACTIVITY_LIMIT = 100
RECENT_VIEW_RETENTION_DAYS = 30


def get_wishlist_response(
    session: Session,
    user: User,
    *,
    limit: int = DEFAULT_ACTIVITY_LIMIT,
) -> WishlistResponse:
    rows = _load_wishlist_rows(session, user.id, _normalize_limit(limit))
    thumbnails = load_thumbnail_storage_keys(session, [int(row.db_product_id) for row in rows])
    return WishlistResponse(
        items=[
            WishlistItem(
                id=int(row.activity_id),
                product_id=row.product_code,
                added_at=row.activity_at,
                product=_to_activity_product(row, thumbnails.get(int(row.db_product_id), "")),
            )
            for row in rows
        ]
    )


def add_wishlist_item(session: Session, user: User, product_code: str) -> WishlistItem:
    product = _load_active_product(session, product_code)
    existing = session.execute(
        select(Wishlist).where(
            Wishlist.user_id == user.id,
            Wishlist.product_id == product.id,
        )
    ).scalar_one_or_none()
    if existing is None:
        now = datetime.now(UTC)
        existing = Wishlist(
            user_id=user.id,
            product_id=product.id,
            added_at=now,
            created_at=now,
        )
        session.add(existing)
        session.flush()

    rows = _load_wishlist_rows(session, user.id, DEFAULT_ACTIVITY_LIMIT, product_db_id=product.id)
    if not rows:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")
    thumbnails = load_thumbnail_storage_keys(session, [product.id])
    row = rows[0]
    return WishlistItem(
        id=int(row.activity_id),
        product_id=row.product_code,
        added_at=row.activity_at,
        product=_to_activity_product(row, thumbnails.get(int(row.db_product_id), "")),
    )


def remove_wishlist_item(session: Session, user: User, product_code: str) -> bool:
    product = _load_product(session, product_code)
    if product is None:
        return True
    row = session.execute(
        select(Wishlist).where(
            Wishlist.user_id == user.id,
            Wishlist.product_id == product.id,
        )
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)
        session.flush()
    return True


def get_recent_views_response(
    session: Session,
    user: User,
    *,
    limit: int = DEFAULT_ACTIVITY_LIMIT,
) -> RecentViewsResponse:
    rows = _load_recent_view_rows(session, user.id, _normalize_limit(limit))
    thumbnails = load_thumbnail_storage_keys(session, [int(row.db_product_id) for row in rows])
    return RecentViewsResponse(
        items=[
            RecentViewItem(
                id=int(row.activity_id),
                product_id=row.product_code,
                viewed_at=row.activity_at,
                product=_to_activity_product(row, thumbnails.get(int(row.db_product_id), "")),
            )
            for row in rows
        ]
    )


def upsert_recent_view(session: Session, user: User, product_code: str) -> RecentViewItem:
    product = _load_active_product(session, product_code)
    now = datetime.now(UTC)
    existing = session.execute(
        select(RecentView).where(
            RecentView.user_id == user.id,
            RecentView.product_id == product.id,
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = RecentView(
            user_id=user.id,
            product_id=product.id,
            viewed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(existing)
    else:
        existing.viewed_at = now
        existing.updated_at = now
    session.flush()

    rows = _load_recent_view_rows(session, user.id, DEFAULT_ACTIVITY_LIMIT, product_db_id=product.id)
    if not rows:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")
    thumbnails = load_thumbnail_storage_keys(session, [product.id])
    row = rows[0]
    return RecentViewItem(
        id=int(row.activity_id),
        product_id=row.product_code,
        viewed_at=row.activity_at,
        product=_to_activity_product(row, thumbnails.get(int(row.db_product_id), "")),
    )


def remove_recent_view(session: Session, user: User, product_code: str) -> bool:
    product = _load_product(session, product_code)
    if product is None:
        return True
    row = session.execute(
        select(RecentView).where(
            RecentView.user_id == user.id,
            RecentView.product_id == product.id,
        )
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)
        session.flush()
    return True


def _load_wishlist_rows(
    session: Session,
    user_id: int,
    limit: int,
    *,
    product_db_id: int | None = None,
):
    statement = (
        _activity_product_statement(
            Wishlist.__table__,
            Wishlist.id.label("activity_id"),
            Wishlist.added_at.label("activity_at"),
        )
        .where(Wishlist.user_id == user_id)
        .order_by(Wishlist.added_at.desc(), Wishlist.id.desc())
        .limit(limit)
    )
    if product_db_id is not None:
        statement = statement.where(Wishlist.product_id == product_db_id)
    return session.execute(statement).all()


def _load_recent_view_rows(
    session: Session,
    user_id: int,
    limit: int,
    *,
    product_db_id: int | None = None,
):
    cutoff = datetime.now(UTC) - timedelta(days=RECENT_VIEW_RETENTION_DAYS)
    statement = (
        _activity_product_statement(
            RecentView.__table__,
            RecentView.id.label("activity_id"),
            RecentView.viewed_at.label("activity_at"),
        )
        .where(
            RecentView.user_id == user_id,
            RecentView.viewed_at >= cutoff,
        )
        .order_by(RecentView.viewed_at.desc(), RecentView.id.desc())
        .limit(limit)
    )
    if product_db_id is not None:
        statement = statement.where(RecentView.product_id == product_db_id)
    return session.execute(statement).all()


def _activity_product_statement(activity_table, activity_id, activity_at):
    price_subquery = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    return (
        select(
            activity_id,
            activity_at,
            Product.id.label("db_product_id"),
            Product.product_code,
            Brand.name.label("brand"),
            Product.product_name.label("name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            price_subquery.c.lowest_price.label("lowest_price"),
        )
        .join(Product, activity_table.c.product_id == Product.id)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(price_subquery, price_subquery.c.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
    )


def _to_activity_product(row, thumbnail_url: str) -> UserActivityProduct:
    return UserActivityProduct(
        product_id=row.product_code,
        brand=row.brand,
        name=row.name,
        category_code=row.category_code,
        category_name=row.category_name,
        thumbnail_url=thumbnail_url,
        lowest_price=int(row.lowest_price or 0),
    )


def _load_active_product(session: Session, product_code: str) -> Product:
    product = _load_product(session, product_code, active_only=True)
    if product is None:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")
    return product


def _load_product(session: Session, product_code: str, *, active_only: bool = False) -> Product | None:
    statement = select(Product).where(Product.product_code == product_code)
    if active_only:
        statement = statement.where(Product.is_active.is_(True))
    return session.execute(statement).scalar_one_or_none()


def _normalize_limit(limit: int) -> int:
    return max(1, min(MAX_ACTIVITY_LIMIT, limit))
