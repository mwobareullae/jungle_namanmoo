export type AgentToolName =
  | "order_status_lookup"
  | "cancel_recent_order"
  | "find_similar_products"
  | "compare_products"
  | "refine_product_results";

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
  | "show_order_status";

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
  | "order_status";

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
};

export type AgentChatRequest = {
  message: string;
  conversation_id?: string | null;
  context?: AgentContext;
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
