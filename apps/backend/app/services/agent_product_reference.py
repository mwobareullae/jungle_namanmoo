from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.schemas.common import ApiError
from app.db.models.auth import User
from app.services.popular_products_service import DEFAULT_POPULAR_WINDOW_DAYS, get_popular_product_items
from app.services.recommendation_pipeline import MAX_PAGE_SIZE, get_recommendation_response
from app.services.user_activity_service import (
    MAX_ACTIVITY_LIMIT,
    get_recent_views_response,
    get_wishlist_response,
)


ProductReferenceSource = Literal["current_product", "popular", "recommendation", "wishlist", "recent"]


@dataclass(frozen=True)
class ResolvedProductReference:
    product_id: str
    source: ProductReferenceSource | Literal["explicit"]
    rank: int | None = None
    recommendation_id: str | None = None

    @property
    def label(self) -> str:
        if self.source == "popular" and self.rank is not None:
            return f"인기 {self.rank}위 상품을"
        if self.source == "recommendation" and self.rank is not None:
            return f"추천 결과 {self.rank}위 상품을"
        return "상품을"


def resolve_product_reference(
    session: Session,
    *,
    product_id: str | None,
    source: ProductReferenceSource | None,
    rank: int | None,
    current_product_id: str | None,
    recommendation_id: str | None,
    user: User | None = None,
    position: Literal["first", "last"] | None = None,
) -> ResolvedProductReference:
    if product_id and source:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "상품을 지정하는 방식은 하나만 선택해 주세요.")
    if product_id:
        return ResolvedProductReference(product_id=product_id, source="explicit")
    if source is None:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_REQUIRED", "담을 상품을 확인할 수 없어요.")
    if position is not None and source not in {"wishlist", "recent"}:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "마지막 상품 위치는 찜·최근 본 목록에서만 사용할 수 있어요.")

    normalized_rank = rank or 1
    if normalized_rank < 1 or normalized_rank > MAX_PAGE_SIZE:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "상품 순위는 1 이상 50 이하로 알려주세요.")

    if source == "current_product":
        if not current_product_id:
            raise ApiError(400, "AGENT_PRODUCT_REFERENCE_REQUIRED", "현재 보고 있는 상품을 확인할 수 없어요.")
        return ResolvedProductReference(product_id=current_product_id, source=source)

    if source == "popular":
        popular_products = get_popular_product_items(
            session,
            window_days=DEFAULT_POPULAR_WINDOW_DAYS,
            limit=normalized_rank,
            recommendable_only=False,
        )
        if len(popular_products) < normalized_rank:
            raise ApiError(404, "AGENT_POPULAR_PRODUCTS_NOT_FOUND", "해당 순위의 인기 상품을 찾지 못했어요.")
        return ResolvedProductReference(
            product_id=popular_products[normalized_rank - 1].product_id,
            source=source,
            rank=normalized_rank,
        )

    if source == "recommendation":
        if not recommendation_id:
            raise ApiError(400, "AGENT_RECOMMENDATION_CONTEXT_REQUIRED", "추천 결과를 먼저 확인해 주세요.")
        recommendation = get_recommendation_response(
            session,
            recommendation_id,
            page=1,
            page_size=MAX_PAGE_SIZE,
        )
        if len(recommendation.products) < normalized_rank:
            raise ApiError(404, "AGENT_PRODUCT_REFERENCE_NOT_FOUND", "추천 결과에서 해당 순위의 상품을 찾지 못했어요.")
        return ResolvedProductReference(
            product_id=recommendation.products[normalized_rank - 1].product_id,
            source=source,
            rank=normalized_rank,
            recommendation_id=recommendation.recommendation_id,
        )

    if source in {"wishlist", "recent"}:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        activity = (
            get_wishlist_response(session, user, limit=MAX_ACTIVITY_LIMIT)
            if source == "wishlist"
            else get_recent_views_response(session, user, limit=MAX_ACTIVITY_LIMIT)
        )
        selected_index = len(activity.items) - 1 if position == "last" else normalized_rank - 1
        if selected_index < 0 or selected_index >= len(activity.items):
            raise ApiError(404, "AGENT_PRODUCT_REFERENCE_NOT_FOUND", "해당 목록의 상품을 찾지 못했어요.")
        return ResolvedProductReference(
            product_id=activity.items[selected_index].product_id,
            source=source,
            rank=selected_index + 1,
        )

    raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "지원하지 않는 상품 선택 방식이에요.")
