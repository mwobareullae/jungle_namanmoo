from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentToolName = Literal[
    "order_status_lookup",
    "cancel_recent_order",
    "find_similar_products",
    "compare_products",
    "refine_product_results",
    "get_cart",
    "add_to_cart",
    "prepare_checkout",
    "prepare_order",
    "compose_cart",
]

AgentToolCallStatus = Literal[
    "PROPOSED",
    "AWAITING_CONFIRMATION",
    "CONFIRMED",
    "EXECUTED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
]

AgentUiActionType = Literal[
    "noop",
    "navigate",
    "open_modal",
    "show_products",
    "show_product_comparison",
    "show_order_status",
    "show_cart",
    "show_checkout_preview",
    "open_payment",
]


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str | None = Field(default=None, max_length=80)
    route: str | None = Field(default=None, max_length=255)
    current_product_id: str | None = Field(default=None, max_length=128)
    visible_product_ids: list[str] = Field(default_factory=list, max_length=100)
    selected_product_ids: list[str] = Field(default_factory=list, max_length=20)
    recommendation_id: str | None = Field(default=None, max_length=128)
    search_query: str | None = Field(default=None, max_length=255)
    filters: dict[str, Any] = Field(default_factory=dict)
    order_code: str | None = Field(default=None, max_length=40)
    cart_item_ids: list[int] = Field(default_factory=list, max_length=100)
    address_id: int | None = Field(default=None, ge=1)


class AgentConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)


class AgentContextResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["product", "order"]
    id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)


class AgentLastToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: AgentUiActionType
    target: str | None = Field(default=None, max_length=80)
    items: list[AgentContextResultItem] = Field(default_factory=list, max_length=10)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=128)
    context: AgentContext = Field(default_factory=AgentContext)
    recent_messages: list[AgentConversationMessage] = Field(default_factory=list, max_length=8)
    last_tool_result: AgentLastToolResult | None = None


class AgentUiAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AgentUiActionType = "noop"
    target: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_:-]{0,79}$")
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["product", "order"]
    id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    image_storage_key: str | None = Field(default=None, max_length=500)
    price: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=80)
    message: str = Field(..., min_length=1, max_length=255)
    retryable: bool = False


class AgentChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=2000)
    requires_confirmation: bool = False
    tool_call_id: str | None = Field(default=None, max_length=128)
    tool_name: AgentToolName | None = None
    ui_action: AgentUiAction = Field(default_factory=AgentUiAction)
    items: list[AgentResponseItem] = Field(default_factory=list, max_length=20)
    error: AgentError | None = None


class AgentToolConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "reject"] = "confirm"


class AgentToolConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(..., min_length=1, max_length=128)
    status: AgentToolCallStatus
    message: str = Field(..., min_length=1, max_length=2000)
    ui_action: AgentUiAction = Field(default_factory=AgentUiAction)
    error: AgentError | None = None
