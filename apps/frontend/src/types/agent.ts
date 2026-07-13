export type AgentToolName =
  | "order_status_lookup"
  | "cancel_recent_order"
  | "find_similar_products"
  | "compare_products"
  | "refine_product_results"
  | "get_cart"
  | "add_to_cart"
  | "prepare_checkout"
  | "prepare_order";

export type AgentToolCallStatus =
  | "PROPOSED"
  | "AWAITING_CONFIRMATION"
  | "CONFIRMED"
  | "EXECUTED"
  | "REJECTED"
  | "EXPIRED"
  | "FAILED";

export type AgentUiActionType =
  | "noop"
  | "navigate"
  | "open_modal"
  | "show_products"
  | "show_product_comparison"
  | "show_order_status"
  | "show_cart"
  | "show_checkout_preview"
  | "open_payment";

export type AgentUiTarget =
  | "home"
  | "login"
  | "product_detail"
  | "order_detail"
  | "checkout"
  | "agent_confirmation"
  | "order_cancel_confirm"
  | "product_results"
  | "similar_products"
  | "refined_products"
  | "product_comparison"
  | "order_status"
  | "cart"
  | "checkout_preview"
  | "order_create_confirm"
  | "toss_payment";

export type AgentContext = {
  page?: string | null;
  route?: string | null;
  current_product_id?: string | null;
  visible_product_ids?: string[];
  selected_product_ids?: string[];
  recommendation_id?: string | null;
  search_query?: string | null;
  filters?: Record<string, unknown>;
  order_code?: string | null;
  cart_item_ids?: number[];
  address_id?: number | null;
};

export type AgentChatRequest = {
  message: string;
  conversation_id?: string | null;
  context?: AgentContext;
  recent_messages?: Array<{
    role: "user" | "assistant";
    content: string;
  }>;
  last_tool_result?: {
    action_type: AgentUiActionType;
    target?: string | null;
    items: Array<{
      item_type: "product" | "order";
      id: string;
      title: string;
    }>;
  } | null;
};

export type AgentUiAction = {
  type: AgentUiActionType;
  target?: AgentUiTarget | string | null;
  payload: Record<string, unknown>;
};

export type AgentResponseItem = {
  item_type: "product" | "order";
  id: string;
  title: string;
  subtitle?: string | null;
  image_storage_key?: string | null;
  price?: number | null;
  currency?: string | null;
  metadata: Record<string, unknown>;
};

export type AgentError = {
  code: string;
  message: string;
  retryable: boolean;
};

export type AgentChatResponse = {
  conversation_id: string;
  message: string;
  requires_confirmation: boolean;
  tool_call_id?: string | null;
  tool_name?: AgentToolName | null;
  ui_action: AgentUiAction;
  items: AgentResponseItem[];
  error?: AgentError | null;
};

export type AgentToolConfirmRequest = {
  action: "confirm" | "reject";
};

export type AgentToolConfirmResponse = {
  tool_call_id: string;
  status: AgentToolCallStatus;
  message: string;
  ui_action: AgentUiAction;
  error?: AgentError | null;
};
