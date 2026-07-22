from datetime import UTC, datetime
import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.performance_logging import log_performance_event
from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.schemas.agent import AgentChatResponse, AgentLastToolResult, AgentToolName
from app.schemas.common import ApiError, dump_model
from app.services.agent_order_tools import (
    CANCEL_RECENT_ORDER_TOOL,
    FILTER_ORDER_HISTORY_TOOL,
    ORDER_STATUS_LOOKUP_TOOL,
    filter_order_history,
    lookup_order_status,
    prepare_recent_order_cancel,
)
from app.services.agent_commerce_tools import (
    ADD_TO_CART_TOOL,
    GET_CART_TOOL,
    PREPARE_CHECKOUT_TOOL,
    PREPARE_PRODUCT_CHECKOUT_TOOL,
    PREPARE_ORDER_TOOL,
    add_agent_cart_item,
    get_agent_cart,
    prepare_agent_checkout,
    prepare_agent_product_checkout,
    prepare_agent_order,
)
from app.services.agent_cart_composer import COMPOSE_CART_TOOL, prepare_composed_cart
from app.services.agent_address_tools import REGISTER_SHIPPING_ADDRESS_TOOL, register_shipping_address
from app.services.agent_policy import AgentToolPolicy, get_tool_policy, validate_tool_access
from app.services.agent_product_reference import ProductReferenceSource
from app.services.agent_recommendation_tools import (
    AgentCategoryCode,
    AgentConcernId,
    AgentEffectId,
    CREATE_RECOMMENDATION_TOOL,
    create_agent_recommendation,
)
from app.services.agent_product_tools import (
    COMPARE_PRODUCTS_TOOL,
    FIND_SIMILAR_PRODUCTS_TOOL,
    REFINE_PRODUCT_RESULTS_TOOL,
    compare_products,
    find_similar_products,
    refine_product_results,
)
from app.services.agent_review_tools import PREPARE_REVIEW_DRAFT_TOOL, prepare_review_draft
from app.services.agent_claim_tools import PREPARE_CLAIM_DRAFT_TOOL, prepare_claim_draft
from app.services.agent_bulk_wishlist import (
    BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
    prepare_bulk_wishlist_by_popular_ingredient,
)


class OrderStatusLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)


class FilterOrderHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_months: Literal[1, 3, 6, 12] | None = None
    status: Literal[
        "ALL",
        "PENDING_PAYMENT",
        "PAID",
        "PREPARING_SHIPMENT",
        "SHIPPED",
        "DELIVERED",
    ] | None = None


class CreateRecommendationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concern_text: str = Field(..., min_length=1, max_length=2000)
    skin_type: Literal["건성", "지성", "복합성", "수부지", "중성"] | None = None
    sensitivity: Literal["낮음", "보통", "높음"] | None = None
    avoid_ingredients: list[str] | None = Field(default=None, max_length=50)
    required_ingredient_names: list[str] | None = Field(default=None, max_length=20)
    page_size: int = Field(default=10, ge=1, le=20)
    concern_ids: list[AgentConcernId] | None = Field(default=None, max_length=12)
    effect_ids: list[AgentEffectId] | None = Field(default=None, max_length=6)
    excluded_concern_ids: list[AgentConcernId] | None = Field(default=None, max_length=12)
    priority_effect_ids: list[AgentEffectId] | None = Field(default=None, max_length=6)
    category_codes: list[AgentCategoryCode] | None = Field(default=None, max_length=4)
    price_min: int | None = Field(default=None, ge=0, le=100_000_000)
    price_max: int | None = Field(default=None, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def validate_price_range(self) -> "CreateRecommendationArgs":
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must be less than or equal to price_max")
        return self


class CancelRecentOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)


class FindSimilarProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., min_length=1, max_length=128)
    limit: int = Field(default=10, ge=1, le=10)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)


class CompareProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(..., min_length=2, max_length=5)


class RefineProductResultsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str | None = Field(default=None, max_length=128)
    base_product_ids: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=10, ge=1, le=10)
    page: int = Field(default=1, ge=1)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    category_code: str | None = Field(default=None, max_length=80)
    skin_type: str | None = Field(default=None, max_length=40)
    sensitivity: str | None = Field(default=None, max_length=40)
    effect_keywords: list[str] | None = Field(default=None, max_length=20)
    required_ingredient_names: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validate_result_source(self) -> "RefineProductResultsArgs":
        if not self.recommendation_id and not self.base_product_ids:
            raise ValueError("recommendation_id or base_product_ids is required")
        return self


class GetCartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddToCartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = Field(default=None, min_length=1, max_length=128)
    quantity: int = Field(default=1, ge=1, le=99)
    recommendation_id: str | None = Field(default=None, max_length=128)
    recommendation_rank: int | None = Field(default=None, ge=1)
    reference_source: ProductReferenceSource | None = None
    reference_rank: int | None = Field(default=None, ge=1, le=50)
    reference_position: Literal["first", "last"] | None = None

    @model_validator(mode="after")
    def validate_product_reference(self) -> "AddToCartArgs":
        if self.product_id and self.reference_source:
            raise ValueError("product_id and reference_source cannot be used together")
        if self.reference_rank is not None and self.reference_position is not None:
            raise ValueError("reference_rank and reference_position cannot be used together")
        if not self.product_id and not self.reference_source:
            raise ValueError("product_id or reference_source is required")
        return self


class PrepareProductCheckoutArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = Field(default=None, min_length=1, max_length=128)
    quantity: int = Field(default=1, ge=1, le=99)
    recommendation_id: str | None = Field(default=None, max_length=128)
    recommendation_rank: int | None = Field(default=None, ge=1)
    reference_source: ProductReferenceSource | None = None
    reference_rank: int | None = Field(default=None, ge=1, le=50)
    reference_position: Literal["first", "last"] | None = None

    @model_validator(mode="after")
    def validate_product_reference(self) -> "PrepareProductCheckoutArgs":
        if self.product_id and self.reference_source:
            raise ValueError("product_id and reference_source cannot be used together")
        if self.reference_rank is not None and self.reference_position is not None:
            raise ValueError("reference_rank and reference_position cannot be used together")
        if not self.product_id and not self.reference_source:
            raise ValueError("product_id or reference_source is required")
        return self


class CheckoutArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cart_item_ids: list[int] | None = Field(default=None, max_length=100)
    address_id: int | None = Field(default=None, ge=1)


class RegisterShippingAddressArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    postal_code: str = Field(..., min_length=1, max_length=20)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: str | None = Field(default=None, max_length=255)
    delivery_memo: str | None = Field(default=None, max_length=255)
    is_default: bool = False
    continue_checkout: bool = True
    cart_item_ids: list[int] | None = Field(default=None, max_length=100)


class ComposeCartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(..., min_length=1, max_length=4)
    max_budget: int = Field(..., ge=1_000, le=10_000_000)
    skin_type: str | None = Field(default=None, max_length=40)
    sensitivity: str | None = Field(default=None, max_length=40)


class PrepareReviewDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)
    product_id: str | None = Field(default=None, max_length=128)
    rating: int = Field(..., ge=1, le=5)
    review_text: str = Field(..., min_length=1, max_length=2000)
    is_repurchase_review: bool = False


class PrepareClaimDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)
    order_item_id: int | None = Field(default=None, ge=1)
    claim_type: Literal["RETURN", "EXCHANGE", "REFUND"]
    reason_code: Literal["CHANGE_OF_MIND", "DEFECTIVE", "WRONG_ITEM", "OTHER"]
    reason_detail: str | None = Field(default=None, max_length=2000)


class BulkWishlistByPopularIngredientArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_name: str | None = Field(default=None, min_length=1, max_length=160)
    ingredient_names: list[str] | None = Field(default=None, min_length=1, max_length=5)
    ingredient_match_mode: Literal["all", "any"] = "all"
    category: str | None = Field(default=None, min_length=1, max_length=80)
    price_min: int | None = Field(default=None, ge=0, le=10_000_000)
    price_max: int | None = Field(default=None, ge=0, le=10_000_000)
    skin_type: Literal["건성", "지성", "복합성", "수부지", "중성"] | None = None
    sensitivity: Literal["낮음", "보통", "높음"] | None = None
    # The service emits a user-facing explanation for rank 51+ instead of
    # silently shrinking it. The wider schema ceiling only rejects nonsense.
    rank_limit: int = Field(default=20, ge=1, le=1000, description="Use ranks 1 through 50.")
    window_days: Literal[1, 7, 30] = 7

    @model_validator(mode="after")
    def validate_criteria(self) -> "BulkWishlistByPopularIngredientArgs":
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise ValueError("price_min must not exceed price_max")
        if not any(
            (
                self.ingredient_name,
                self.ingredient_names,
                self.skin_type,
                self.sensitivity,
                self.category,
                self.price_min is not None,
                self.price_max is not None,
            )
        ):
            raise ValueError("one wishlist criterion is required")
        return self


ToolArgs = (
    CreateRecommendationArgs
    | FilterOrderHistoryArgs
    | OrderStatusLookupArgs
    | CancelRecentOrderArgs
    | FindSimilarProductsArgs
    | CompareProductsArgs
    | RefineProductResultsArgs
    | GetCartArgs
    | AddToCartArgs
    | PrepareProductCheckoutArgs
    | CheckoutArgs
    | RegisterShippingAddressArgs
    | ComposeCartArgs
    | PrepareReviewDraftArgs
    | PrepareClaimDraftArgs
    | BulkWishlistByPopularIngredientArgs
)
TOOL_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    CREATE_RECOMMENDATION_TOOL: CreateRecommendationArgs,
    FILTER_ORDER_HISTORY_TOOL: FilterOrderHistoryArgs,
    ORDER_STATUS_LOOKUP_TOOL: OrderStatusLookupArgs,
    CANCEL_RECENT_ORDER_TOOL: CancelRecentOrderArgs,
    FIND_SIMILAR_PRODUCTS_TOOL: FindSimilarProductsArgs,
    COMPARE_PRODUCTS_TOOL: CompareProductsArgs,
    REFINE_PRODUCT_RESULTS_TOOL: RefineProductResultsArgs,
    GET_CART_TOOL: GetCartArgs,
    ADD_TO_CART_TOOL: AddToCartArgs,
    PREPARE_PRODUCT_CHECKOUT_TOOL: PrepareProductCheckoutArgs,
    PREPARE_CHECKOUT_TOOL: CheckoutArgs,
    PREPARE_ORDER_TOOL: CheckoutArgs,
    REGISTER_SHIPPING_ADDRESS_TOOL: RegisterShippingAddressArgs,
    COMPOSE_CART_TOOL: ComposeCartArgs,
    PREPARE_REVIEW_DRAFT_TOOL: PrepareReviewDraftArgs,
    PREPARE_CLAIM_DRAFT_TOOL: PrepareClaimDraftArgs,
    BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL: BulkWishlistByPopularIngredientArgs,
}


def execute_agent_tool(
    session: Session,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    user: User | None = None,
    conversation_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    anonymous_user_id: str | None = None,
    anonymous_cart_id: str | None = None,
    current_product_id: str | None = None,
    last_tool_result: AgentLastToolResult | None = None,
) -> AgentChatResponse:
    started_at = time.perf_counter()
    policy = get_tool_policy(tool_name)
    raw_arguments = arguments or {}
    try:
        validate_tool_access(tool_name, user_id=user.id if user is not None else None)
    except ApiError as exc:
        latency_ms = _elapsed_ms(started_at)
        _record_pre_execution_tool_call(
            session,
            tool_name=tool_name,
            arguments=raw_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            error=exc,
            status="REJECTED",
            confirmation_required=policy.requires_confirmation,
            latency_ms=latency_ms,
        )
        _log_pre_execution_failure(
            tool_name=tool_name,
            status="REJECTED",
            error=exc,
            policy=policy,
            request_id=request_id,
            user=user,
            latency_ms=latency_ms,
        )
        raise

    try:
        parsed_arguments = _parse_tool_arguments(tool_name, raw_arguments)
    except ApiError as exc:
        latency_ms = _elapsed_ms(started_at)
        _record_pre_execution_tool_call(
            session,
            tool_name=tool_name,
            arguments=raw_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            error=exc,
            status="FAILED",
            confirmation_required=policy.requires_confirmation,
            latency_ms=latency_ms,
        )
        _log_pre_execution_failure(
            tool_name=tool_name,
            status="FAILED",
            error=exc,
            policy=policy,
            request_id=request_id,
            user=user,
            latency_ms=latency_ms,
        )
        raise

    try:
        response = _execute_parsed_tool(
            session,
            tool_name=tool_name,
            arguments=parsed_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            anonymous_cart_id=anonymous_cart_id,
            current_product_id=current_product_id,
            last_tool_result=last_tool_result,
        )
    except ApiError as exc:
        latency_ms = _elapsed_ms(started_at)
        _record_failed_tool_call(
            session,
            tool_name=tool_name,
            arguments=parsed_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            error=exc,
            latency_ms=latency_ms,
        )
        log_performance_event(
            "agent_tool_failed",
            request_id=request_id,
            duration_ms=latency_ms,
            metadata={
                "tool_name": tool_name,
                "status": "FAILED",
                "confirmation_required": policy.requires_confirmation,
                "error_code": exc.code,
                "user_authenticated": user is not None,
            },
        )
        raise

    latency_ms = _elapsed_ms(started_at)
    if not policy.requires_confirmation or not response.requires_confirmation:
        _record_executed_tool_call(
            session,
            response=response,
            arguments=parsed_arguments,
            user=user,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            latency_ms=latency_ms,
        )
        status = "EXECUTED"
    else:
        status = "AWAITING_CONFIRMATION"
    log_performance_event(
        "agent_tool_completed",
        request_id=request_id,
        duration_ms=latency_ms,
        metadata={
            "tool_name": response.tool_name or tool_name,
            "status": status,
            "confirmation_required": policy.requires_confirmation,
            "tool_call_id": response.tool_call_id,
            "item_count": len(response.items),
            "ui_action_type": response.ui_action.type,
            "user_authenticated": user is not None,
        },
    )
    return response


def list_agent_tool_names() -> list[AgentToolName]:
    return list(TOOL_ARGUMENT_MODELS.keys())  # type: ignore[return-value]


def _parse_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> ToolArgs:
    model = TOOL_ARGUMENT_MODELS.get(tool_name)
    if model is None:
        raise ApiError(400, "UNKNOWN_AGENT_TOOL", "지원하지 않는 에이전트 기능이에요.")
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise ApiError(400, "AGENT_TOOL_ARGUMENT_INVALID", "요청 내용을 실행 가능한 형식으로 해석하지 못했어요.") from exc


def _execute_parsed_tool(
    session: Session,
    *,
    tool_name: str,
    arguments: ToolArgs,
    user: User | None,
    conversation_id: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    anonymous_cart_id: str | None,
    current_product_id: str | None,
    last_tool_result: AgentLastToolResult | None,
) -> AgentChatResponse:
    if tool_name == CREATE_RECOMMENDATION_TOOL:
        args = _require_args(arguments, CreateRecommendationArgs)
        return create_agent_recommendation(
            session,
            concern_text=args.concern_text,
            current_user=user,
            conversation_id=conversation_id,
            skin_type=args.skin_type,
            sensitivity=args.sensitivity,
            avoid_ingredients=args.avoid_ingredients,
            required_ingredient_names=args.required_ingredient_names,
            page_size=args.page_size,
            concern_ids=args.concern_ids,
            effect_ids=args.effect_ids,
            excluded_concern_ids=args.excluded_concern_ids,
            priority_effect_ids=args.priority_effect_ids,
            category_codes=args.category_codes,
            price_min=args.price_min,
            price_max=args.price_max,
        )

    if tool_name == FILTER_ORDER_HISTORY_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, FilterOrderHistoryArgs)
        return filter_order_history(
            user,
            conversation_id=conversation_id,
            period_months=args.period_months,
            status=args.status,
        )

    if tool_name == ORDER_STATUS_LOOKUP_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, OrderStatusLookupArgs)
        return lookup_order_status(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
        )

    if tool_name == CANCEL_RECENT_ORDER_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, CancelRecentOrderArgs)
        return prepare_recent_order_cancel(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    if tool_name == FIND_SIMILAR_PRODUCTS_TOOL:
        args = _require_args(arguments, FindSimilarProductsArgs)
        return find_similar_products(
            session,
            product_id=args.product_id,
            conversation_id=conversation_id,
            limit=args.limit,
            min_price=args.min_price,
            max_price=args.max_price,
        )

    if tool_name == COMPARE_PRODUCTS_TOOL:
        args = _require_args(arguments, CompareProductsArgs)
        return compare_products(
            session,
            product_ids=args.product_ids,
            conversation_id=conversation_id,
        )

    if tool_name == REFINE_PRODUCT_RESULTS_TOOL:
        args = _require_args(arguments, RefineProductResultsArgs)
        return refine_product_results(
            session,
            base_product_ids=args.base_product_ids,
            recommendation_id=args.recommendation_id,
            conversation_id=conversation_id,
            limit=args.limit,
            page=args.page,
            min_price=args.min_price,
            max_price=args.max_price,
            category_code=args.category_code,
            skin_type=args.skin_type,
            sensitivity=args.sensitivity,
            effect_keywords=args.effect_keywords,
            required_ingredient_names=args.required_ingredient_names,
        )

    if tool_name == GET_CART_TOOL:
        _require_args(arguments, GetCartArgs)
        return get_agent_cart(
            session,
            user,
            anonymous_cart_id=anonymous_cart_id,
            conversation_id=conversation_id,
        )

    if tool_name == ADD_TO_CART_TOOL:
        args = _require_args(arguments, AddToCartArgs)
        return add_agent_cart_item(
            session,
            user,
            anonymous_cart_id=anonymous_cart_id,
            conversation_id=conversation_id,
            product_id=args.product_id,
            quantity=args.quantity,
            recommendation_id=args.recommendation_id,
            recommendation_rank=args.recommendation_rank,
            reference_source=args.reference_source,
            reference_rank=args.reference_rank,
            reference_position=args.reference_position,
            current_product_id=current_product_id,
            last_tool_result=last_tool_result,
        )

    if tool_name == PREPARE_PRODUCT_CHECKOUT_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, PrepareProductCheckoutArgs)
        return prepare_agent_product_checkout(
            session,
            user,
            conversation_id=conversation_id,
            product_id=args.product_id,
            quantity=args.quantity,
            recommendation_id=args.recommendation_id,
            recommendation_rank=args.recommendation_rank,
            reference_source=args.reference_source,
            reference_rank=args.reference_rank,
            reference_position=args.reference_position,
            current_product_id=current_product_id,
            last_tool_result=last_tool_result,
        )

    if tool_name in {PREPARE_CHECKOUT_TOOL, PREPARE_ORDER_TOOL}:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, CheckoutArgs)
        if tool_name == PREPARE_CHECKOUT_TOOL:
            return prepare_agent_checkout(
                session,
                user,
                conversation_id=conversation_id,
                cart_item_ids=args.cart_item_ids,
                address_id=args.address_id,
            )
        return prepare_agent_order(
            session,
            user,
            conversation_id=conversation_id,
            cart_item_ids=args.cart_item_ids,
            address_id=args.address_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    if tool_name == REGISTER_SHIPPING_ADDRESS_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, RegisterShippingAddressArgs)
        return register_shipping_address(
            session,
            user,
            conversation_id=conversation_id,
            recipient_name=args.recipient_name,
            phone=args.phone,
            postal_code=args.postal_code,
            address1=args.address1,
            address2=args.address2,
            delivery_memo=args.delivery_memo,
            is_default=args.is_default,
            continue_checkout=args.continue_checkout,
            cart_item_ids=args.cart_item_ids,
        )

    if tool_name == COMPOSE_CART_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, ComposeCartArgs)
        return prepare_composed_cart(
            session,
            user,
            conversation_id=conversation_id,
            categories=args.categories,
            max_budget=args.max_budget,
            skin_type=args.skin_type,
            sensitivity=args.sensitivity,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    if tool_name == PREPARE_REVIEW_DRAFT_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, PrepareReviewDraftArgs)
        return prepare_review_draft(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
            product_id=args.product_id,
            rating=args.rating,
            review_text=args.review_text,
            is_repurchase_review=args.is_repurchase_review,
        )

    if tool_name == PREPARE_CLAIM_DRAFT_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, PrepareClaimDraftArgs)
        return prepare_claim_draft(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
            order_item_id=args.order_item_id,
            claim_type=args.claim_type,
            reason_code=args.reason_code,
            reason_detail=args.reason_detail,
        )

    if tool_name == BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
        args = _require_args(arguments, BulkWishlistByPopularIngredientArgs)
        return prepare_bulk_wishlist_by_popular_ingredient(
            session,
            user,
            conversation_id=conversation_id,
            ingredient_name=args.ingredient_name,
            ingredient_names=args.ingredient_names,
            ingredient_match_mode=args.ingredient_match_mode,
            category=args.category,
            price_min=args.price_min,
            price_max=args.price_max,
            skin_type=args.skin_type,
            sensitivity=args.sensitivity,
            rank_limit=args.rank_limit,
            window_days=args.window_days,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    raise ApiError(400, "UNKNOWN_AGENT_TOOL", "지원하지 않는 에이전트 기능이에요.")


def _require_args(arguments: ToolArgs, model: type[BaseModel]) -> Any:
    if not isinstance(arguments, model):
        raise ApiError(400, "AGENT_TOOL_ARGUMENT_INVALID", "요청 내용을 실행 가능한 형식으로 해석하지 못했어요.")
    return arguments


def _record_executed_tool_call(
    session: Session,
    *,
    response: AgentChatResponse,
    arguments: ToolArgs,
    user: User | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    latency_ms: int,
) -> None:
    now = datetime.now(UTC)
    tool_call = AgentToolCall(
        tool_call_id=_generate_tool_call_id(),
        conversation_id=response.conversation_id,
        user_id=user.id if user is not None else None,
        anonymous_user_id=anonymous_user_id,
        session_id=session_id,
        request_id=request_id,
        tool_name=response.tool_name or "",
        status="EXECUTED",
        confirmation_required=False,
        executed_at=now,
        input_json=_safe_tool_input(response.tool_name or "", arguments),
        output_json=dump_model(response),
        latency_ms=latency_ms,
        created_at=now,
        updated_at=now,
    )
    session.add(tool_call)
    session.flush()


def _record_failed_tool_call(
    session: Session,
    *,
    tool_name: str,
    arguments: ToolArgs,
    user: User | None,
    conversation_id: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    error: ApiError,
    latency_ms: int,
) -> None:
    now = datetime.now(UTC)
    tool_call = AgentToolCall(
        tool_call_id=_generate_tool_call_id(),
        conversation_id=conversation_id,
        user_id=user.id if user is not None else None,
        anonymous_user_id=anonymous_user_id,
        session_id=session_id,
        request_id=request_id,
        tool_name=tool_name,
        status="FAILED",
        confirmation_required=False,
        input_json=_safe_tool_input(tool_name, arguments),
        output_json={},
        error_code=error.code,
        error_message=error.message,
        latency_ms=latency_ms,
        created_at=now,
        updated_at=now,
    )
    session.add(tool_call)
    session.flush()


def _record_pre_execution_tool_call(
    session: Session,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    user: User | None,
    conversation_id: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    error: ApiError,
    status: Literal["REJECTED", "FAILED"],
    confirmation_required: bool,
    latency_ms: int,
) -> None:
    now = datetime.now(UTC)
    session.add(
        AgentToolCall(
            tool_call_id=_generate_tool_call_id(),
            conversation_id=conversation_id,
            user_id=user.id if user is not None else None,
            anonymous_user_id=anonymous_user_id,
            session_id=session_id,
            request_id=request_id,
            tool_name=tool_name,
            status=status,
            confirmation_required=confirmation_required,
            input_json=_safe_unparsed_tool_input(tool_name, arguments),
            output_json={},
            error_code=error.code,
            error_message=error.message,
            latency_ms=latency_ms,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()


def _log_pre_execution_failure(
    *,
    tool_name: str,
    status: Literal["REJECTED", "FAILED"],
    error: ApiError,
    policy: AgentToolPolicy,
    request_id: str | None,
    user: User | None,
    latency_ms: int,
) -> None:
    log_performance_event(
        "agent_tool_failed",
        request_id=request_id,
        duration_ms=latency_ms,
        metadata={
            "tool_name": tool_name,
            "status": status,
            "confirmation_required": policy.requires_confirmation,
            "error_code": error.code,
            "user_authenticated": user is not None,
            "failure_stage": "access" if status == "REJECTED" else "arguments",
        },
    )


def _generate_tool_call_id() -> str:
    return f"tool_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def _safe_tool_input(tool_name: str, arguments: ToolArgs) -> dict[str, Any]:
    if tool_name != REGISTER_SHIPPING_ADDRESS_TOOL:
        return dump_model(arguments)

    args = _require_args(arguments, RegisterShippingAddressArgs)
    return {
        "recipient_name_provided": bool(args.recipient_name),
        "phone_provided": bool(args.phone),
        "postal_code_provided": bool(args.postal_code),
        "address1_provided": bool(args.address1),
        "address2_provided": bool(args.address2),
        "delivery_memo_provided": bool(args.delivery_memo),
        "is_default": args.is_default,
        "continue_checkout": args.continue_checkout,
        "cart_item_ids": args.cart_item_ids,
        "pii_redacted": True,
    }


def _safe_unparsed_tool_input(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name != REGISTER_SHIPPING_ADDRESS_TOOL:
        return dict(arguments)

    return {
        "recipient_name_provided": bool(arguments.get("recipient_name")),
        "phone_provided": bool(arguments.get("phone")),
        "postal_code_provided": bool(arguments.get("postal_code")),
        "address1_provided": bool(arguments.get("address1")),
        "address2_provided": bool(arguments.get("address2")),
        "delivery_memo_provided": bool(arguments.get("delivery_memo")),
        "is_default": arguments.get("is_default"),
        "continue_checkout": arguments.get("continue_checkout"),
        "cart_item_ids": arguments.get("cart_item_ids"),
        "pii_redacted": True,
    }


def _elapsed_ms(started_at: float) -> int:
    return max(int((time.perf_counter() - started_at) * 1000), 0)
