from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from sqlalchemy.orm import Session

from app.schemas.agent import AgentLastToolResult
from app.schemas.common import ApiError
from app.db.models.auth import User
from app.services.popular_products_service import DEFAULT_POPULAR_WINDOW_DAYS, get_popular_product_items
from app.services.recommendation_pipeline import MAX_PAGE_SIZE, get_recommendation_response
from app.services.user_activity_service import (
    MAX_ACTIVITY_LIMIT,
    get_recent_views_response,
    get_wishlist_response,
)


ProductReferenceSource = Literal[
    "current_product",
    "popular",
    "recommendation",
    "wishlist",
    "recent",
    "last_tool_result",
]

_LAST_TOOL_RESULT_REFERENCE_TOOLS = frozenset({"add_to_cart", "prepare_product_checkout"})
_POSITIONAL_REFERENCE_PATTERN = re.compile(
    r"(?P<last>마지막(?:\s*(?:상품|제품|거|것))?)"
    r"|(?P<ordinal>첫\s*번째|첫번째|첫째|두\s*번째|두번째|둘째|세\s*번째|세번째|셋째|"
    r"네\s*번째|네번째|넷째|다섯\s*번째|다섯번째|여섯\s*번째|여섯번째|"
    r"일곱\s*번째|일곱번째|여덟\s*번째|여덟번째|아홉\s*번째|아홉번째|"
    r"열\s*번째|열번째|\d{1,2}\s*(?:번째|번))"
)
_KOREAN_ORDINAL_RANKS = {
    "첫번째": 1,
    "첫째": 1,
    "두번째": 2,
    "둘째": 2,
    "세번째": 3,
    "셋째": 3,
    "네번째": 4,
    "넷째": 4,
    "다섯번째": 5,
    "여섯번째": 6,
    "일곱번째": 7,
    "여덟번째": 8,
    "아홉번째": 9,
    "열번째": 10,
}


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
    last_tool_result: AgentLastToolResult | None = None,
) -> ResolvedProductReference:
    if product_id and source:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "상품을 지정하는 방식은 하나만 선택해 주세요.")
    if product_id:
        return ResolvedProductReference(product_id=product_id, source="explicit")
    if source is None:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_REQUIRED", "담을 상품을 확인할 수 없어요.")
    if position is not None and source not in {"wishlist", "recent", "last_tool_result"}:
        raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "상품 위치를 적용할 수 없는 목록이에요.")

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

    if source == "last_tool_result":
        product_items = [
            item for item in (last_tool_result.items if last_tool_result is not None else [])
            if item.item_type == "product"
        ]
        selected_index = len(product_items) - 1 if position == "last" else normalized_rank - 1
        if selected_index < 0 or selected_index >= len(product_items):
            raise ApiError(404, "AGENT_PRODUCT_REFERENCE_NOT_FOUND", "직전 결과에서 해당 상품을 찾지 못했어요.")
        return ResolvedProductReference(
            product_id=product_items[selected_index].id,
            source=source,
            rank=selected_index + 1,
        )

    raise ApiError(400, "AGENT_PRODUCT_REFERENCE_INVALID", "지원하지 않는 상품 선택 방식이에요.")


def apply_last_tool_result_reference(
    *,
    tool_name: str,
    arguments: dict,
    user_message: str,
    last_tool_result: AgentLastToolResult | None,
) -> dict:
    """Prefer a deterministic ordinal reference over an inferred product ID."""
    if tool_name not in _LAST_TOOL_RESULT_REFERENCE_TOOLS or last_tool_result is None:
        return arguments

    selector = _extract_position_selector(user_message)
    if selector is None:
        return arguments

    explicit_product_id = arguments.get("product_id")
    if isinstance(explicit_product_id, str) and explicit_product_id in user_message:
        return arguments

    normalized = dict(arguments)
    normalized["product_id"] = None
    normalized["reference_source"] = "last_tool_result"
    if selector[0] == "position":
        normalized["reference_position"] = selector[1]
        normalized["reference_rank"] = None
    else:
        normalized["reference_rank"] = selector[1]
        normalized["reference_position"] = None
    return normalized


def _extract_position_selector(
    message: str,
) -> tuple[Literal["position"], Literal["last"]] | tuple[Literal["rank"], int] | None:
    match = _POSITIONAL_REFERENCE_PATTERN.search(message)
    if match is None:
        return None
    if match.group("last"):
        return ("position", "last")

    normalized = re.sub(r"\s+", "", match.group("ordinal") or "")
    if normalized in _KOREAN_ORDINAL_RANKS:
        return ("rank", _KOREAN_ORDINAL_RANKS[normalized])
    numeric = re.match(r"(?P<rank>\d{1,2})", normalized)
    return ("rank", int(numeric.group("rank"))) if numeric else None
