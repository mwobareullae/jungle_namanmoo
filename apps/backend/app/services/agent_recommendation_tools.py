import secrets
from typing import Literal, TypeAlias
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.schemas.agent import AgentChatResponse, AgentResponseItem, AgentUiAction
from app.schemas.common import dump_model
from app.schemas.recommendation import RecommendationRequest
from app.services.agent_policy import validate_result_item_count, validate_tool_ui_action
from app.services.recommendation_pipeline import (
    create_structured_recommendation_response,
)
from app.services.recommendation_intent import StructuredRecommendationIntent


CREATE_RECOMMENDATION_TOOL = "create_recommendation"

AgentConcernId: TypeAlias = Literal[
    "concern_acne",
    "concern_brightening_spots",
    "concern_pore",
    "concern_dry_barrier",
    "concern_wrinkle_elasticity",
    "concern_redness_irritation",
    "concern_sensitive",
    "concern_dead_skin_texture",
    "concern_blemish_mark",
    "concern_dull_uneven_tone",
    "concern_folliculitis",
    "concern_dark_circle",
]
AgentEffectId: TypeAlias = Literal[
    "effect_acne_sebum",
    "effect_calming",
    "effect_exfoliation",
    "effect_brightening",
    "effect_moisture_barrier",
    "effect_wrinkle",
]
AgentCategoryCode: TypeAlias = Literal["serum", "cream", "toner", "lotion"]


def create_agent_recommendation(
    session: Session,
    *,
    concern_text: str,
    current_user: User | None = None,
    conversation_id: str | None = None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    avoid_ingredients: list[str] | None = None,
    required_ingredient_names: list[str] | None = None,
    page_size: int = 10,
    concern_ids: list[AgentConcernId] | None = None,
    effect_ids: list[AgentEffectId] | None = None,
    excluded_concern_ids: list[AgentConcernId] | None = None,
    priority_effect_ids: list[AgentEffectId] | None = None,
    category_codes: list[AgentCategoryCode] | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
) -> AgentChatResponse:
    structured_intent = StructuredRecommendationIntent(
        concern_ids=tuple(concern_ids or ()),
        effect_ids=tuple(effect_ids or ()),
        excluded_concern_ids=tuple(excluded_concern_ids or ()),
        priority_effect_ids=tuple(priority_effect_ids or ()),
        category_codes=tuple(category_codes or ()),
        price_min=price_min,
        price_max=price_max,
    )
    recommendation = create_structured_recommendation_response(
        session,
        RecommendationRequest(
            concern_text=concern_text,
            skin_type=skin_type,
            sensitivity=sensitivity,
            avoid_ingredients=avoid_ingredients,
            required_ingredient_names=required_ingredient_names,
        ),
        current_user=current_user,
        page=1,
        page_size=page_size,
        structured_intent=structured_intent,
    )
    validate_result_item_count(CREATE_RECOMMENDATION_TOOL, len(recommendation.products))

    summary = recommendation.summary
    result_params = {
        "keyword": summary.concern_text,
        "search_mode": "ai",
        "page_size": str(page_size),
        "skin_type": summary.skin_type,
        "sensitivity": summary.sensitivity,
        "recommendation_id": recommendation.recommendation_id,
    }
    result_url = f"/search?{urlencode(result_params)}"
    if required_ingredient_names:
        result_url += "&" + urlencode(
            [("refine_ingredient", ingredient) for ingredient in required_ingredient_names]
        )
    action = AgentUiAction(
        type="show_products",
        target="product_results",
        payload={
            "recommendation_id": recommendation.recommendation_id,
            "concern_text": summary.concern_text,
            "skin_type": summary.skin_type,
            "sensitivity": summary.sensitivity,
            "required_ingredient_names": required_ingredient_names or [],
            "page_size": page_size,
            "result_url": result_url,
            "summary": dump_model(summary),
            "unmatched_terms": recommendation.unmatched_terms,
            "pagination": dump_model(recommendation.pagination),
            "products": [dump_model(product) for product in recommendation.products],
        },
    )
    validate_tool_ui_action(CREATE_RECOMMENDATION_TOOL, action)

    return AgentChatResponse(
        conversation_id=conversation_id or f"conv_{secrets.token_hex(8)}",
        message=f"조건에 맞는 추천 상품 {recommendation.pagination.total_items}개를 찾았어요.",
        tool_name=CREATE_RECOMMENDATION_TOOL,
        ui_action=action,
        items=[
            AgentResponseItem(
                item_type="product",
                id=product.product_id,
                title=product.name,
                subtitle=product.brand,
                image_storage_key=product.thumbnail_url or None,
                price=product.lowest_price,
                currency="KRW",
                metadata={
                    "rank": product.rank,
                    "total_score": product.total_score,
                    "recommendation_id": recommendation.recommendation_id,
                },
            )
            for product in recommendation.products
        ],
    )
