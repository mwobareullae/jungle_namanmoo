from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Order, OrderItem
from app.db.models.review import ProductReview, ProductReviewProfileLabel
from app.schemas.common import ApiError
from app.schemas.review import (
    ProductReviewAuthor,
    ProductReviewCreateRequest,
    ProductReviewItem,
    ProductReviewMutationResponse,
    ProductReviewProfileLabel as ProductReviewProfileLabelSchema,
    ProductReviewUpdateRequest,
)
from app.services.review_query_service import get_product_review_summary
from app.services.review_rollup import rollup_product_review_metrics
from app.services.skin_profile_service import load_skin_profile_for_user


FIRST_PARTY_REVIEW_SOURCE = "mubarelle"
FIRST_PARTY_PROFILE_MAPPING_VERSION = "saved_skin_profile_v1"

_SKIN_TYPE_CODES = {
    "건성": "dry",
    "지성": "oily",
    "복합성": "combination",
    "중성": "normal",
    "수부지": "combination",
}
_SENSITIVITY_CODES = {
    "낮음": "low",
    "보통": "medium",
    "높음": "high",
}


def create_purchase_review(
    session: Session,
    *,
    product_code: str,
    current_user: User,
    request: ProductReviewCreateRequest,
) -> ProductReviewMutationResponse:
    order_item, product = _load_owned_order_item(
        session,
        order_item_id=request.order_item_id,
        user_id=int(current_user.id),
    )
    if product.product_code != product_code:
        raise ApiError(
            400,
            "REVIEW_PRODUCT_MISMATCH",
            "주문 상품과 리뷰 대상 상품이 일치하지 않습니다.",
        )
    if order_item.status != "DELIVERED":
        raise ApiError(
            409,
            "REVIEW_NOT_ELIGIBLE",
            "배송완료 상품만 리뷰를 작성할 수 있습니다.",
        )

    _lock_product(session, int(product.id))
    existing = session.scalar(
        select(ProductReview)
        .where(
            ProductReview.order_item_id == int(order_item.id),
            ProductReview.review_type == "GENERAL",
        )
        .with_for_update()
    )
    if existing is not None and existing.status != "DELETED":
        raise ApiError(
            409,
            "REVIEW_ALREADY_EXISTS",
            "해당 주문 상품에는 이미 리뷰가 있습니다.",
        )

    now = datetime.now(UTC)
    review = existing or ProductReview(
        review_code=_new_review_code(),
        product_id=int(product.id),
        user_id=int(current_user.id),
        order_item_id=int(order_item.id),
        source=FIRST_PARTY_REVIEW_SOURCE,
        status="PUBLISHED",
        review_type="GENERAL",
    )
    if existing is None:
        session.add(review)

    review.product_id = int(product.id)
    review.user_id = int(current_user.id)
    review.order_item_id = int(order_item.id)
    review.source = FIRST_PARTY_REVIEW_SOURCE
    review.source_review_id = review.review_code
    review.status = "PUBLISHED"
    review.review_type = "GENERAL"
    review.rating = int(request.rating)
    review.review_text = request.review_text
    review.reviewed_at = now
    review.option_text = None
    review.is_repurchase_review = request.is_repurchase_review
    review.verified_purchase = True
    review.helpful_count = 0
    review.source_has_photo = False
    review.source_badge_labels_json = None
    review.source_metadata_json = None
    review.source_collected_at = None
    review.source_content_hash = None
    review.profile_mapping_version = FIRST_PARTY_PROFILE_MAPPING_VERSION
    review.published_at = now
    review.deleted_at = None
    review.updated_at = now

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            409,
            "REVIEW_ALREADY_EXISTS",
            "해당 주문 상품에는 이미 리뷰가 있습니다.",
        ) from exc

    session.execute(
        delete(ProductReviewProfileLabel).where(
            ProductReviewProfileLabel.review_id == int(review.id)
        )
    )
    profile_labels = _snapshot_profile_labels(
        session,
        review_id=int(review.id),
        user_id=int(current_user.id),
    )
    session.add_all(profile_labels)
    rollup_product_review_metrics(session, product_id=int(product.id), computed_at=now)
    session.commit()

    return ProductReviewMutationResponse(
        review=_to_review_item(review, profile_labels, current_user),
        review_id=review.review_code,
        product_id=product.product_code,
        status=review.status,
        review_summary=get_product_review_summary(session, int(product.id)),
    )


def update_purchase_review(
    session: Session,
    *,
    review_code: str,
    current_user: User,
    request: ProductReviewUpdateRequest,
) -> ProductReviewMutationResponse:
    review, product = _load_owned_review_for_update(
        session,
        review_code=review_code,
        user_id=int(current_user.id),
    )
    if review.status != "PUBLISHED":
        raise ApiError(
            409,
            "REVIEW_NOT_EDITABLE",
            "공개 중인 본인 리뷰만 수정할 수 있습니다.",
        )

    now = datetime.now(UTC)
    if "rating" in request.model_fields_set:
        review.rating = request.rating
    if "review_text" in request.model_fields_set:
        review.review_text = request.review_text
    if "is_repurchase_review" in request.model_fields_set:
        review.is_repurchase_review = request.is_repurchase_review
    review.updated_at = now

    labels = _load_profile_label_rows(session, int(review.id))
    rollup_product_review_metrics(session, product_id=int(product.id), computed_at=now)
    session.commit()
    return ProductReviewMutationResponse(
        review=_to_review_item(review, labels, current_user),
        review_id=review.review_code,
        product_id=product.product_code,
        status=review.status,
        review_summary=get_product_review_summary(session, int(product.id)),
    )


def delete_purchase_review(
    session: Session,
    *,
    review_code: str,
    current_user: User,
) -> ProductReviewMutationResponse:
    review, product = _load_owned_review_for_update(
        session,
        review_code=review_code,
        user_id=int(current_user.id),
        allow_deleted=True,
    )
    if review.status != "DELETED":
        now = datetime.now(UTC)
        review.status = "DELETED"
        review.rating = None
        review.review_text = None
        review.option_text = None
        review.is_repurchase_review = None
        review.verified_purchase = None
        review.helpful_count = 0
        review.source_has_photo = None
        review.source_badge_labels_json = None
        review.source_metadata_json = None
        review.source_collected_at = None
        review.source_content_hash = None
        review.profile_mapping_version = None
        review.published_at = None
        review.deleted_at = now
        review.updated_at = now
        session.execute(
            delete(ProductReviewProfileLabel).where(
                ProductReviewProfileLabel.review_id == int(review.id)
            )
        )
        rollup_product_review_metrics(session, product_id=int(product.id), computed_at=now)
        session.commit()

    return ProductReviewMutationResponse(
        review=None,
        review_id=review.review_code,
        product_id=product.product_code,
        status="DELETED",
        review_summary=get_product_review_summary(session, int(product.id)),
    )


def _load_owned_order_item(
    session: Session,
    *,
    order_item_id: int,
    user_id: int,
) -> tuple[OrderItem, Product]:
    row = session.execute(
        select(OrderItem, Product)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(
            OrderItem.id == order_item_id,
            Order.user_id == user_id,
        )
    ).first()
    if row is None:
        raise ApiError(
            404,
            "REVIEW_ORDER_ITEM_NOT_FOUND",
            "리뷰를 작성할 주문 상품을 찾을 수 없습니다.",
        )
    order_item, product = row
    return order_item, product


def _load_owned_review_for_update(
    session: Session,
    *,
    review_code: str,
    user_id: int,
    allow_deleted: bool = False,
) -> tuple[ProductReview, Product]:
    identity = session.execute(
        select(ProductReview.product_id)
        .where(
            ProductReview.review_code == review_code,
            ProductReview.user_id == user_id,
            ProductReview.source == FIRST_PARTY_REVIEW_SOURCE,
        )
    ).scalar_one_or_none()
    if identity is None:
        raise ApiError(404, "REVIEW_NOT_FOUND", "리뷰를 찾을 수 없습니다.")
    _lock_product(session, int(identity))
    row = session.execute(
        select(ProductReview, Product)
        .join(Product, Product.id == ProductReview.product_id)
        .where(
            ProductReview.review_code == review_code,
            ProductReview.user_id == user_id,
            ProductReview.source == FIRST_PARTY_REVIEW_SOURCE,
        )
        .with_for_update()
    ).first()
    if row is None:
        raise ApiError(404, "REVIEW_NOT_FOUND", "리뷰를 찾을 수 없습니다.")
    review, product = row
    if review.status == "DELETED" and not allow_deleted:
        raise ApiError(404, "REVIEW_NOT_FOUND", "리뷰를 찾을 수 없습니다.")
    return review, product


def _lock_product(session: Session, product_id: int) -> None:
    session.execute(
        select(Product.id).where(Product.id == product_id).with_for_update()
    ).scalar_one()


def _snapshot_profile_labels(
    session: Session,
    *,
    review_id: int,
    user_id: int,
) -> list[ProductReviewProfileLabel]:
    profile = load_skin_profile_for_user(session, user_id)
    if profile is None:
        return []

    labels: list[ProductReviewProfileLabel] = []
    skin_type_code = _SKIN_TYPE_CODES.get(profile.skin_type)
    if skin_type_code is not None:
        labels.append(
            _profile_label(
                review_id,
                dimension="SKIN_TYPE",
                value_code=skin_type_code,
                source_label=profile.skin_type,
                confidence=_profile_confidence(profile.skin_type_confidence),
            )
        )
    sensitivity_code = _SENSITIVITY_CODES.get(profile.sensitivity)
    if sensitivity_code is not None:
        labels.append(
            _profile_label(
                review_id,
                dimension="SENSITIVITY",
                value_code=sensitivity_code,
                source_label=profile.sensitivity,
                confidence=_profile_confidence(profile.sensitivity_confidence),
            )
        )

    concern_profile = profile.concern_profile_json
    concerns = concern_profile.get("concerns") if isinstance(concern_profile, dict) else None
    if isinstance(concerns, list):
        for concern in _dedupe_strings(concerns):
            labels.append(
                _profile_label(
                    review_id,
                    dimension="SKIN_CONCERN",
                    value_code=concern,
                    source_label=concern,
                    confidence=Decimal("0.7500"),
                )
            )
    return labels


def _load_profile_label_rows(
    session: Session,
    review_id: int,
) -> list[ProductReviewProfileLabel]:
    return list(
        session.execute(
            select(ProductReviewProfileLabel)
            .where(ProductReviewProfileLabel.review_id == review_id)
            .order_by(
                ProductReviewProfileLabel.dimension,
                ProductReviewProfileLabel.value_code,
            )
        ).scalars()
    )


def _profile_label(
    review_id: int,
    *,
    dimension: str,
    value_code: str,
    source_label: str,
    confidence: Decimal,
) -> ProductReviewProfileLabel:
    return ProductReviewProfileLabel(
        review_id=review_id,
        dimension=dimension,
        value_code=value_code,
        source_label=source_label,
        mapping_source="saved_skin_profile",
        mapping_confidence=confidence,
    )


def _profile_confidence(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("1.0000")
    return min(max(value, Decimal("0")), Decimal("1")).quantize(Decimal("0.0001"))


def _dedupe_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _to_review_item(
    review: ProductReview,
    profile_labels: list[ProductReviewProfileLabel],
    current_user: User,
) -> ProductReviewItem:
    return ProductReviewItem(
        review_id=review.review_code,
        rating=review.rating,
        review_text=review.review_text,
        reviewed_at=review.reviewed_at,
        option_text=review.option_text,
        review_type=review.review_type,
        is_repurchase_review=review.is_repurchase_review,
        verified_purchase=review.verified_purchase,
        helpful_count=int(review.helpful_count or 0),
        badges=[],
        author=ProductReviewAuthor(
            display_name=_masked_display_name(current_user.display_name),
        ),
        profile_labels=[
            ProductReviewProfileLabelSchema(
                dimension=label.dimension,
                value_code=label.value_code,
                display_label=label.source_label,
            )
            for label in sorted(
                profile_labels,
                key=lambda item: (item.dimension, item.value_code),
            )
        ],
        media=[],
    )


def _masked_display_name(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return "구매자"
    if len(normalized) == 1:
        return f"{normalized}*"
    return f"{normalized[0]}{'*' * (len(normalized) - 1)}"


def _new_review_code() -> str:
    return f"rev_{uuid4().hex[:20]}"
