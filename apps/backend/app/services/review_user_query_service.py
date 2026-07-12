from __future__ import annotations

import math

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Order, OrderItem
from app.db.models.review import FIRST_PARTY_REVIEW_SOURCE, ProductReview
from app.schemas.review import (
    MyProductReviewItem,
    MyProductReviewsResponse,
    ReviewableOrderItem,
    ReviewableOrderItemsResponse,
)
from app.services.review_query_service import (
    load_review_profile_labels,
    to_review_item,
)


DEFAULT_MY_REVIEW_PAGE_SIZE = 20
MAX_MY_REVIEW_PAGE_SIZE = 50


def get_my_product_reviews(
    session: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
) -> MyProductReviewsResponse:
    normalized_page, normalized_page_size = _normalize_pagination(page, page_size)
    conditions = (
        ProductReview.user_id == int(current_user.id),
        ProductReview.source == FIRST_PARTY_REVIEW_SOURCE,
        ProductReview.status != "DELETED",
    )
    total_items = int(
        session.scalar(select(func.count(ProductReview.id)).where(*conditions)) or 0
    )
    rows = session.execute(
        select(ProductReview, Product, OrderItem)
        .join(Product, Product.id == ProductReview.product_id)
        .join(OrderItem, OrderItem.id == ProductReview.order_item_id)
        .where(*conditions)
        .order_by(ProductReview.reviewed_at.desc(), ProductReview.id.desc())
        .offset((normalized_page - 1) * normalized_page_size)
        .limit(normalized_page_size)
    ).all()
    labels_by_review_id = load_review_profile_labels(
        session,
        [int(review.id) for review, _, _ in rows],
    )
    items = [
        MyProductReviewItem(
            product_id=product.product_code,
            product_name=product.product_name,
            brand_name=order_item.brand_name_snapshot,
            thumbnail_storage_key=order_item.thumbnail_storage_key_snapshot,
            status=review.status,
            review=to_review_item(
                review,
                labels_by_review_id.get(int(review.id), []),
                author=current_user,
                current_user_id=int(current_user.id),
            ),
        )
        for review, product, order_item in rows
    ]
    return MyProductReviewsResponse(
        page=normalized_page,
        page_size=normalized_page_size,
        total_items=total_items,
        total_pages=_total_pages(total_items, normalized_page_size),
        items=items,
    )


def get_reviewable_order_items(
    session: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
) -> ReviewableOrderItemsResponse:
    normalized_page, normalized_page_size = _normalize_pagination(page, page_size)
    conditions = (
        Order.user_id == int(current_user.id),
        OrderItem.status == "DELIVERED",
    )
    total_items = int(
        session.scalar(
            select(func.count(OrderItem.id))
            .join(Order, Order.id == OrderItem.order_id)
            .where(*conditions)
        )
        or 0
    )
    rows = session.execute(
        select(OrderItem, Order, Product, ProductReview)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .outerjoin(
            ProductReview,
            and_(
                ProductReview.order_item_id == OrderItem.id,
                ProductReview.review_type == "GENERAL",
                ProductReview.source == FIRST_PARTY_REVIEW_SOURCE,
            ),
        )
        .where(*conditions)
        .order_by(Order.ordered_at.desc(), OrderItem.id.desc())
        .offset((normalized_page - 1) * normalized_page_size)
        .limit(normalized_page_size)
    ).all()
    items = [
        ReviewableOrderItem(
            order_item_id=int(order_item.id),
            order_code=order.order_code,
            product_id=product.product_code,
            product_name=order_item.product_name_snapshot,
            brand_name=order_item.brand_name_snapshot,
            thumbnail_storage_key=order_item.thumbnail_storage_key_snapshot,
            order_item_status=order_item.status,
            review_id=review.review_code if review is not None else None,
            review_status=review.status if review is not None else None,
            can_write=review is None or review.status == "DELETED",
        )
        for order_item, order, product, review in rows
    ]
    return ReviewableOrderItemsResponse(
        page=normalized_page,
        page_size=normalized_page_size,
        total_items=total_items,
        total_pages=_total_pages(total_items, normalized_page_size),
        items=items,
    )


def _normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
    return max(1, int(page)), max(1, min(int(page_size), MAX_MY_REVIEW_PAGE_SIZE))


def _total_pages(total_items: int, page_size: int) -> int:
    return math.ceil(total_items / page_size) if total_items else 0
