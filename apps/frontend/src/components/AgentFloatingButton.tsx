import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { navigateWithinApp } from "../lib/navigation";
import {
  useProductComparison,
  type ProductComparisonCandidatePreview,
  type ProductComparisonDifference,
  type ProductComparisonIntent,
} from "../contexts/ProductComparisonContext";
import type {
  AgentChatResponse,
  AgentContext,
  AgentResponseItem,
  AgentToolConfirmResponse,
  AgentToolName,
  AgentUiAction,
} from "../types/agent";
import type { ApiError } from "../types/recommendation";

type AgentFloatingButtonProps = {
  isAgentResponding?: boolean;
  skinProfileStatus?: "empty" | "saved" | "temporary";
  surface?: "home" | "productDetail" | "context" | "minimal";
};

type AgentChatBaseMessage = {
  createdAt?: number;
  id: string;
};

type AgentChatTextMessage = AgentChatBaseMessage & {
  kind: "chat";
  role: "assistant" | "user";
  content: string;
  evidenceExpanded?: boolean;
  showActions?: boolean;
};

type AgentStatusStep = {
  label: string;
  status: "active" | "done" | "todo";
};

type AgentChatStatusMessage = AgentChatBaseMessage & {
  kind: "status";
  steps: AgentStatusStep[];
  title: string;
};

type AgentChatApprovalMessage = AgentChatBaseMessage & {
  approveLabel: string;
  kind: "approval";
  description: string;
  rejectLabel: string;
  resolved?: "approved" | "cancelled";
  title: string;
  toolCallId: string | null;
  toolName?: AgentToolName | null;
};

type AgentChatErrorMessage = AgentChatBaseMessage & {
  action: "login" | "profile" | "retry";
  actionLabel: string;
  kind: "error";
  message: string;
  retryMessage?: string;
  title: string;
  tone: "amber" | "info";
};

type AgentChatResultItem = {
  id: string;
  itemType: "order" | "product";
  price?: number | null;
  subtitle?: string | null;
  title: string;
};

type AgentChatResultMessage = AgentChatBaseMessage & {
  actionTarget?: string | null;
  actionType: AgentUiAction["type"];
  actionUrl?: string | null;
  description: string;
  items: AgentChatResultItem[];
  kind: "result";
  title: string;
};

type AgentChatMessage =
  | AgentChatApprovalMessage
  | AgentChatErrorMessage
  | AgentChatResultMessage
  | AgentChatStatusMessage
  | AgentChatTextMessage;

type AgentChatView = "home" | "thread";

type AgentChatThreadSummary = {
  conversationId: string | null;
  id: string;
  messages: AgentChatMessage[];
  title: string;
  updatedAt: number;
};

const AGENT_CHAT_HISTORY_KEY = "mwobareullae-agent-chat-history-v2";
const AGENT_CONVERSATION_ID_KEY = "mwobareullae-agent-conversation-id";
const AGENT_CHAT_THREADS_KEY = "mwobareullae-agent-chat-threads-v1";
const MAX_AGENT_CHAT_THREADS = 5;
const MAX_AGENT_PRODUCT_PREVIEW_ITEMS = 3;
const MAX_STORED_AGENT_MESSAGES = 24;
const MAX_AGENT_CHAT_THREAD_TITLE_LENGTH = 36;

const homeQuickQuestions = [
  "이 성분, 내 피부에 맞을까?",
  "이번 주 예산 3만원 루틴 짜줘",
  "지금 쓰는 제품과 같이 써도 될까?",
];

const productQuickQuestions = [
  "이거랑 비슷한 상품 보여줘",
  "이 성분, 내 피부에 맞을까?",
  "비슷한 상품끼리 비교해줘",
];

const completedStatusSteps: AgentStatusStep[] = [
  { label: "피부 타입 확인", status: "done" },
  { label: "성분 근거 찾기", status: "done" },
  { label: "추천 기준 정리", status: "done" },
];

const activeStatusSteps: AgentStatusStep[] = [
  { label: "피부 타입 확인", status: "done" },
  { label: "상품 성분 확인 중", status: "active" },
  { label: "추천 결과 정리", status: "todo" },
];

function createStatusMessage(id: string, isActive = false): AgentChatStatusMessage {
  return {
    id,
    kind: "status",
    steps: isActive ? activeStatusSteps : completedStatusSteps,
    title: isActive ? "상품 정보를 확인하고 있어요" : "추천 근거를 확인했어요",
  };
}

function createAssistantMessage(id: string, content: string): AgentChatTextMessage {
  return {
    id,
    content,
    evidenceExpanded: false,
    kind: "chat",
    role: "assistant",
    showActions: true,
  };
}

function normalizeStoredMessage(message: unknown): AgentChatMessage | null {
  if (!message || typeof message !== "object") {
    return null;
  }

  const candidate = message as Record<string, unknown>;

  if (typeof candidate.id !== "string") {
    return null;
  }

  const createdAt = typeof candidate.createdAt === "number" ? candidate.createdAt : undefined;

  if (!("kind" in candidate) && (candidate.role === "assistant" || candidate.role === "user")) {
    return typeof candidate.content === "string"
      ? {
          id: candidate.id,
          content: candidate.content,
          createdAt,
          kind: "chat",
          role: candidate.role,
        }
      : null;
  }

  if (candidate.kind === "chat") {
    return (candidate.role === "assistant" || candidate.role === "user") && typeof candidate.content === "string"
      ? {
          id: candidate.id,
          content: candidate.content,
          createdAt,
          evidenceExpanded: Boolean(candidate.evidenceExpanded),
          kind: "chat",
          role: candidate.role,
          showActions: Boolean(candidate.showActions),
        }
      : null;
  }

  if (candidate.kind === "status") {
    return Array.isArray(candidate.steps) && typeof candidate.title === "string"
      ? {
          id: candidate.id,
          createdAt,
          kind: "status",
          steps: candidate.steps.filter(
            (step): step is AgentStatusStep =>
              Boolean(step) &&
              typeof step === "object" &&
              typeof (step as Record<string, unknown>).label === "string" &&
              ["active", "done", "todo"].includes(String((step as Record<string, unknown>).status)),
          ),
          title: candidate.title,
        }
      : null;
  }

  if (candidate.kind === "approval") {
    return typeof candidate.title === "string" && typeof candidate.description === "string"
      ? {
          id: candidate.id,
          approveLabel: typeof candidate.approveLabel === "string" ? candidate.approveLabel : "승인",
          createdAt,
          description: candidate.description,
          kind: "approval",
          rejectLabel: typeof candidate.rejectLabel === "string" ? candidate.rejectLabel : "취소",
          resolved:
            candidate.resolved === "approved" || candidate.resolved === "cancelled" ? candidate.resolved : undefined,
          title: candidate.title,
          toolCallId: typeof candidate.toolCallId === "string" ? candidate.toolCallId : null,
          toolName: typeof candidate.toolName === "string" ? (candidate.toolName as AgentToolName) : null,
        }
      : null;
  }

  if (candidate.kind === "error") {
    return typeof candidate.title === "string" &&
      typeof candidate.message === "string" &&
      typeof candidate.actionLabel === "string" &&
      (candidate.tone === "amber" || candidate.tone === "info")
      ? {
          id: candidate.id,
          action:
            candidate.action === "login" || candidate.action === "profile" || candidate.action === "retry"
              ? candidate.action
              : "retry",
          actionLabel: candidate.actionLabel,
          createdAt,
          kind: "error",
          message: candidate.message,
          retryMessage: typeof candidate.retryMessage === "string" ? candidate.retryMessage : undefined,
          title: candidate.title,
          tone: candidate.tone,
        }
      : null;
  }

  if (candidate.kind === "result") {
    return typeof candidate.title === "string" &&
      typeof candidate.description === "string" &&
      typeof candidate.actionType === "string" &&
      Array.isArray(candidate.items)
      ? {
          id: candidate.id,
          actionTarget: typeof candidate.actionTarget === "string" ? candidate.actionTarget : null,
          actionType: candidate.actionType as AgentUiAction["type"],
          actionUrl: typeof candidate.actionUrl === "string" ? candidate.actionUrl : null,
          createdAt,
          description: candidate.description,
          items: candidate.items.filter((item): item is AgentChatResultItem => {
            if (!item || typeof item !== "object") {
              return false;
            }
            const nextItem = item as Record<string, unknown>;
            return (
              typeof nextItem.id === "string" &&
              (nextItem.itemType === "order" || nextItem.itemType === "product") &&
              typeof nextItem.title === "string"
            );
          }),
          kind: "result",
          title: candidate.title,
        }
      : null;
  }

  return null;
}

function readStoredMessages() {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const storedMessages = window.localStorage.getItem(AGENT_CHAT_HISTORY_KEY);

    if (!storedMessages) {
      return [];
    }

    const parsedMessages: unknown = JSON.parse(storedMessages);

    if (!Array.isArray(parsedMessages)) {
      return [];
    }

    return parsedMessages
      .map((message) => normalizeStoredMessage(message))
      .filter((message): message is AgentChatMessage => message !== null)
      .slice(-MAX_STORED_AGENT_MESSAGES);
  } catch {
    return [];
  }
}

function readStoredConversationId() {
  if (typeof window === "undefined") {
    return null;
  }

  return readString(window.localStorage.getItem(AGENT_CONVERSATION_ID_KEY));
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const readString = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : null);

const readNumber = (value: unknown) => {
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
};

const createThreadTitle = (content: string) => {
  const normalizedContent = content.replace(/\s+/g, " ").trim();
  if (!normalizedContent) return "새 대화";
  return normalizedContent.length > MAX_AGENT_CHAT_THREAD_TITLE_LENGTH
    ? `${normalizedContent.slice(0, MAX_AGENT_CHAT_THREAD_TITLE_LENGTH)}...`
    : normalizedContent;
};

const createThreadTitleFromMessages = (messages: AgentChatMessage[]) => {
  const firstUserMessage = messages.find(
    (message): message is AgentChatTextMessage => message.kind === "chat" && message.role === "user",
  );
  return firstUserMessage ? createThreadTitle(firstUserMessage.content) : "새 대화";
};

const normalizeStoredThread = (thread: unknown): AgentChatThreadSummary | null => {
  if (!isRecord(thread)) {
    return null;
  }

  const id = readString(thread.id);
  const messages = Array.isArray(thread.messages)
    ? thread.messages
        .map((message) => normalizeStoredMessage(message))
        .filter((message): message is AgentChatMessage => message !== null)
        .slice(-MAX_STORED_AGENT_MESSAGES)
    : [];

  if (!id || messages.length === 0) {
    return null;
  }

  return {
    id,
    conversationId: readString(thread.conversationId),
    messages,
    title: readString(thread.title) ?? createThreadTitleFromMessages(messages),
    updatedAt: readNumber(thread.updatedAt) ?? Date.now(),
  };
};

function readStoredThreads() {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const storedThreads = window.localStorage.getItem(AGENT_CHAT_THREADS_KEY);
    const parsedThreads: unknown = storedThreads ? JSON.parse(storedThreads) : null;

    if (Array.isArray(parsedThreads)) {
      return parsedThreads
        .map((thread) => normalizeStoredThread(thread))
        .filter((thread): thread is AgentChatThreadSummary => thread !== null)
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_AGENT_CHAT_THREADS);
    }
  } catch {
    // Legacy history is still useful if the new thread list cannot be parsed.
  }

  const legacyMessages = readStoredMessages();
  const legacyConversationId = readStoredConversationId();
  if (legacyMessages.length === 0) {
    return [];
  }

  return [
    {
      id: legacyConversationId ?? "legacy-agent-thread",
      conversationId: legacyConversationId,
      messages: legacyMessages,
      title: createThreadTitleFromMessages(legacyMessages),
      updatedAt: Date.now(),
    },
  ];
}

const upsertAgentChatThread = (
  currentThreads: AgentChatThreadSummary[],
  nextThread: AgentChatThreadSummary,
) =>
  [
    nextThread,
    ...currentThreads.filter((thread) => thread.id !== nextThread.id),
  ]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_AGENT_CHAT_THREADS);

const uniqueNonEmpty = (values: (string | null | undefined)[]) =>
  Array.from(new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value))));

const readPayloadString = (payload: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = readString(payload[key]);
    if (value) return value;
  }

  return null;
};

const collectVisibleProductIds = (currentProductId: string | null) => {
  if (typeof document === "undefined") {
    return currentProductId ? [currentProductId] : [];
  }

  const cardProductIds = Array.from(document.querySelectorAll<HTMLElement>("[data-agent-product-id]"))
    .map((element) => element.dataset.agentProductId);
  return uniqueNonEmpty([currentProductId, ...cardProductIds]).slice(0, 20);
};

const resolveAgentPage = (pathname: string) => {
  if (pathname.startsWith("/product-detail")) return "product_detail";
  if (pathname.startsWith("/search")) return "search_results";
  if (pathname.startsWith("/checkout")) return "checkout";
  if (pathname.startsWith("/payment-complete")) return "payment_complete";
  if (pathname.startsWith("/skin-test")) return "skin_test";
  if (pathname.startsWith("/login")) return "login";
  return "home";
};

function buildAgentContext(): AgentContext {
  if (typeof window === "undefined") {
    return {};
  }

  const { hash, pathname, search } = window.location;
  const params = new URLSearchParams(search);
  const currentProductId = pathname.startsWith("/product-detail") || pathname.startsWith("/checkout")
    ? readString(params.get("id"))
    : null;
  const filters: Record<string, unknown> = {};
  const skinType = readString(params.get("skin_type"));
  const sensitivity = readString(params.get("sensitivity"));
  const pageSize = readNumber(params.get("page_size"));
  const page = readNumber(params.get("page"));

  if (skinType) filters.skin_type = skinType;
  if (sensitivity) filters.sensitivity = sensitivity;
  if (pageSize) filters.page_size = pageSize;
  if (page) filters.page = page;

  return {
    current_product_id: currentProductId,
    filters,
    order_code: readString(params.get("order_code")),
    page: resolveAgentPage(pathname),
    recommendation_id: readString(params.get("recommendation_id")),
    route: `${pathname}${search}${hash}`,
    search_query: readString(params.get("keyword")),
    selected_product_ids: [],
    visible_product_ids: collectVisibleProductIds(currentProductId),
  };
}

const getApprovalCopy = (toolName?: AgentToolName | null) => {
  if (toolName === "cancel_recent_order") {
    return {
      approveLabel: "취소 진행",
      description: "주문 상태를 바꾸는 작업이라 한 번 더 확인이 필요해요.",
      rejectLabel: "취소 안 함",
      title: "주문 취소를 진행할까요?",
    };
  }

  return {
    approveLabel: "승인",
    description: "이 작업은 진행 전에 확인이 필요해요.",
    rejectLabel: "취소",
    title: "이 작업을 진행할까요?",
  };
};

function createApprovalMessage(response: AgentChatResponse, timestamp: number): AgentChatApprovalMessage {
  const copy = getApprovalCopy(response.tool_name);
  const orderCode = readString(response.ui_action.payload.order_code);

  return {
    id: `approval-${timestamp}`,
    approveLabel: copy.approveLabel,
    description: orderCode ? `${copy.description} 대상 주문: ${orderCode}` : copy.description,
    kind: "approval",
    rejectLabel: copy.rejectLabel,
    title: copy.title,
    toolCallId: response.tool_call_id ?? null,
    toolName: response.tool_name,
  };
}

function createAgentErrorMessage(
  id: string,
  title: string,
  message: string,
  options: Partial<Pick<AgentChatErrorMessage, "action" | "actionLabel" | "retryMessage" | "tone">> = {},
): AgentChatErrorMessage {
  return {
    id,
    action: options.action ?? "retry",
    actionLabel: options.actionLabel ?? "다시 시도",
    kind: "error",
    message,
    retryMessage: options.retryMessage,
    title,
    tone: options.tone ?? "amber",
  };
}

function createAgentErrorFromUnknown(error: unknown, id: string, retryMessage?: string): AgentChatErrorMessage {
  const apiError = error as Partial<ApiError>;
  const status = typeof apiError.status === "number" ? apiError.status : 0;
  const code = typeof apiError.code === "string" ? apiError.code : "";
  const message = typeof apiError.message === "string" ? apiError.message : "요청을 처리하지 못했어요.";

  if (status === 401 || code === "AGENT_AUTH_REQUIRED") {
    return createAgentErrorMessage(id, "로그인이 필요해요", message, {
      action: "login",
      actionLabel: "로그인하기",
      tone: "info",
    });
  }

  if (status === 408) {
    return createAgentErrorMessage(id, "응답이 지연되고 있어요", message, {
      retryMessage,
    });
  }

  if (status === 503 || code.startsWith("AGENT_OPENAI_") || code === "AGENT_SDK_NOT_INSTALLED") {
    return createAgentErrorMessage(id, "AI 연결을 확인해야 해요", message, {
      retryMessage,
    });
  }

  return createAgentErrorMessage(id, "답변을 만들지 못했어요", message, {
    retryMessage,
  });
}

function createAgentErrorFromResponse(response: AgentChatResponse, id: string, retryMessage?: string) {
  if (!response.error) {
    return null;
  }

  return createAgentErrorMessage(id, "요청을 처리하지 못했어요", response.error.message, {
    retryMessage,
    tone: response.error.retryable ? "amber" : "info",
  });
}

const formatAgentPrice = (price?: number | null) =>
  typeof price === "number" ? `${price.toLocaleString("ko-KR")}원` : null;

const mapAgentItem = (item: AgentResponseItem): AgentChatResultItem => ({
  id: item.id,
  itemType: item.item_type,
  price: item.price ?? null,
  subtitle: item.subtitle ?? null,
  title: item.title,
});

const mapPayloadProduct = (item: unknown): AgentChatResultItem | null => {
  if (!isRecord(item)) {
    return null;
  }

  const id = readString(item.product_id) ?? readString(item.id);
  const name = readString(item.name) ?? readString(item.title) ?? readString(item.product_name);
  if (!id || !name) {
    return null;
  }

  const brand = readString(item.brand);
  const stockStatus = readString(item.stock_status);

  return {
    id,
    itemType: "product",
    price: readNumber(item.price) ?? readNumber(item.lowest_price),
    subtitle: uniqueNonEmpty([brand, stockStatus]).join(" · ") || null,
    title: name,
  };
};

const mapOrderPayload = (action: AgentUiAction): AgentChatResultItem | null => {
  const orderCode = readString(action.payload.order_code);
  if (!orderCode) {
    return null;
  }

  const orderStatus = readString(action.payload.order_status) ?? readString(action.payload.status);
  const paymentStatus = readString(action.payload.payment_status);

  return {
    id: orderCode,
    itemType: "order",
    subtitle: uniqueNonEmpty([orderStatus, paymentStatus]).join(" · ") || null,
    title: `주문 ${orderCode}`,
  };
};

const getResultTitle = (action: AgentUiAction) => {
  if (action.type === "show_product_comparison") return "상품 비교 결과";
  if (action.type === "show_order_status") return "주문 상태";
  if (action.target === "similar_products") return "비슷한 상품";
  if (action.target === "refined_products") return "조건에 맞는 상품";
  if (action.type === "show_products") return "상품 결과";
  return "처리 결과";
};

const normalizeInternalResultUrl = (value: unknown) => {
  const rawUrl = readString(value);
  if (!rawUrl) return null;

  try {
    const baseOrigin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(rawUrl, baseOrigin);
    if (url.origin !== baseOrigin) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return rawUrl.startsWith("/") ? rawUrl : null;
  }
};

const buildProductsResultUrl = (action: AgentUiAction) => {
  if (action.type !== "show_products") {
    return null;
  }

  const directUrl =
    normalizeInternalResultUrl(action.payload.result_url) ??
    normalizeInternalResultUrl(action.payload.results_url) ??
    normalizeInternalResultUrl(action.payload.url) ??
    normalizeInternalResultUrl(action.payload.href);
  if (directUrl) {
    return directUrl;
  }

  const filters = isRecord(action.payload.filters) ? action.payload.filters : {};
  const params = new URLSearchParams();
  const keyword =
    readPayloadString(action.payload, ["keyword", "query", "search_query", "concern_text"]) ??
    readPayloadString(filters, ["keyword", "query", "search_query", "concern_text"]);
  const skinType =
    readPayloadString(action.payload, ["skin_type", "skinType"]) ??
    readPayloadString(filters, ["skin_type", "skinType"]);
  const sensitivity =
    readPayloadString(action.payload, ["sensitivity"]) ??
    readPayloadString(filters, ["sensitivity"]);
  const recommendationId =
    readPayloadString(action.payload, ["recommendation_id", "recommendationId"]) ??
    readPayloadString(filters, ["recommendation_id", "recommendationId"]);
  const pageSize =
    readNumber(action.payload.page_size) ??
    readNumber(action.payload.pageSize) ??
    readNumber(filters.page_size) ??
    readNumber(filters.pageSize) ??
    10;

  if (keyword) params.set("keyword", keyword);
  if (skinType) params.set("skin_type", skinType);
  if (sensitivity) params.set("sensitivity", sensitivity);
  if (recommendationId) params.set("recommendation_id", recommendationId);
  params.set("page_size", String(pageSize));

  return params.size > 1 || recommendationId || keyword ? `/search?${params.toString()}` : null;
};

const isSimilarProductsAction = (action: AgentUiAction) =>
  action.type === "show_products" && action.target === "similar_products";

const readProductId = (value: unknown) => {
  const directValue = readString(value);
  if (directValue) return directValue;
  if (!isRecord(value)) return null;

  for (const key of ["product_id", "id", "compare_product_id", "compared_product_id", "target_product_id"]) {
    const productId = readString(value[key]);
    if (productId) return productId;
  }

  return null;
};

const collectProductIds = (value: unknown) =>
  Array.isArray(value)
    ? value.map(readProductId).filter((productId): productId is string => Boolean(productId))
    : [];

const uniqueProductIds = (productIds: Array<string | null | undefined>) =>
  Array.from(new Set(productIds.map((productId) => productId?.trim()).filter((productId): productId is string => Boolean(productId))));

const createComparisonDifferences = (payload: Record<string, unknown>): ProductComparisonDifference[] => {
  const highlights = isRecord(payload.highlights) ? payload.highlights : {};
  const values = payload.differences ?? payload.comparison_points ?? highlights.different_points;

  if (!Array.isArray(values)) return [];

  return values.flatMap((value, index) => {
    if (typeof value === "string" && value.trim()) {
      return [{ description: value.trim(), label: `비교 포인트 ${index + 1}` }];
    }
    if (!isRecord(value)) return [];

    const label = readString(value.label) ?? readString(value.title) ?? `비교 포인트 ${index + 1}`;
    const description = readString(value.description) ?? readString(value.summary);
    const base = readString(value.base) ?? readString(value.current);
    const compare = readString(value.compare) ?? readString(value.target);

    return [{ label, description, base, compare }];
  });
};

const readStringValues = (value: unknown) =>
  Array.isArray(value)
    ? value.flatMap((item) => typeof item === "string" && item.trim() ? [item.trim()] : [])
    : [];

const createCandidatePreview = (
  productId: string,
  itemByProductId: Map<string, AgentResponseItem>,
  payloadByProductId: Map<string, Record<string, unknown>>,
): ProductComparisonCandidatePreview => {
  const item = itemByProductId.get(productId);
  const payload = payloadByProductId.get(productId) ?? {};
  const metadata = item?.metadata ?? {};

  return {
    brand: readString(payload.brand) ?? readString(metadata.brand) ?? item?.subtitle ?? "브랜드 정보 없음",
    evidenceTags: readStringValues(payload.effects).length > 0
      ? readStringValues(payload.effects)
      : readStringValues(metadata.effects),
    keyIngredients: readStringValues(payload.key_ingredients).length > 0
      ? readStringValues(payload.key_ingredients)
      : readStringValues(metadata.ingredients),
    lowestPrice: readNumber(payload.price) ?? item?.price ?? null,
    name: readString(payload.name) ?? item?.title ?? "상품 정보 확인 중",
    productId,
    riskFlags: readStringValues(payload.caution_flags).length > 0
      ? readStringValues(payload.caution_flags)
      : readStringValues(metadata.caution_flags),
    thumbnailStorageKey: readString(payload.thumbnail_storage_key) ?? item?.image_storage_key ?? null,
  };
};

const createComparisonIntent = (
  action: AgentUiAction,
  items: AgentResponseItem[],
  message: string,
  currentProductId: string | null,
): ProductComparisonIntent | null => {
  if (action.type !== "show_product_comparison" && !isSimilarProductsAction(action)) {
    return null;
  }

  const payload = action.payload;
  const sourceProductId =
    readString(payload.source_product_id) ??
    readString(payload.base_product_id) ??
    readString(payload.current_product_id) ??
    currentProductId;

  if (!sourceProductId) return null;

  const candidateProductIds = uniqueProductIds([
    ...collectProductIds(payload.products),
    ...collectProductIds(payload.product_ids),
    ...collectProductIds(payload.compare_product_ids),
    ...items.map((item) => item.item_type === "product" ? item.id : null),
  ]).filter((productId) => productId !== sourceProductId).slice(0, 2);

  if (candidateProductIds.length === 0) return null;

  const itemByProductId = new Map(
    items
      .filter((item) => item.item_type === "product")
      .map((item) => [item.id, item]),
  );
  const payloadByProductId = new Map(
    (Array.isArray(payload.products) ? payload.products : [])
      .flatMap((item) => isRecord(item) && readProductId(item) ? [[readProductId(item) as string, item] as const] : []),
  );

  return {
    candidatePreviews: candidateProductIds.map((productId) => (
      createCandidatePreview(productId, itemByProductId, payloadByProductId)
    )),
    compareProductIds: candidateProductIds,
    createdAt: Date.now(),
    differences: createComparisonDifferences(payload),
    recommendationReason: readString(payload.recommendation_reason) ?? "",
    source: isSimilarProductsAction(action) ? "similar" : "comparison",
    sourceProductId,
    summary: readString(payload.summary) ?? message,
  };
};

function createResultMessage(
  id: string,
  action: AgentUiAction,
  items: AgentResponseItem[] = [],
): AgentChatResultMessage | null {
  if (isSimilarProductsAction(action)) {
    return null;
  }

  const productPayload = Array.isArray(action.payload.products)
    ? action.payload.products.map(mapPayloadProduct).filter((item): item is AgentChatResultItem => item !== null)
    : [];
  const orderPayload = action.type === "show_order_status" ? mapOrderPayload(action) : null;
  const resultItems = items.length > 0
    ? items.map(mapAgentItem)
    : orderPayload
      ? [orderPayload]
      : productPayload;

  if (action.type === "noop" && resultItems.length === 0) {
    return null;
  }

  const title = getResultTitle(action);
  const emptyProducts = action.type === "show_products" && resultItems.length === 0;

  return {
    id,
    actionTarget: action.target ?? null,
    actionType: action.type,
    actionUrl: buildProductsResultUrl(action),
    description: emptyProducts
      ? "조건에 맞는 상품을 찾지 못했어요."
      : resultItems.length > 0
        ? `${resultItems.length}개 항목을 확인했어요.`
        : "요청 결과를 확인했어요.",
    items: resultItems,
    kind: "result",
    title,
  };
}

function createMessagesFromAgentResponse(response: AgentChatResponse, timestamp: number, retryMessage: string) {
  const nextMessages: AgentChatMessage[] = [];
  const resultMessage = createResultMessage(`result-${timestamp}`, response.ui_action, response.items);

  if (resultMessage) {
    nextMessages.push(resultMessage);
  }

  const errorMessage = createAgentErrorFromResponse(response, `error-${timestamp}`, retryMessage);
  if (errorMessage) {
    nextMessages.push(errorMessage);
  }

  if (response.message.trim()) {
    nextMessages.push(createAssistantMessage(`assistant-${timestamp}`, response.message));
  }

  if (response.requires_confirmation) {
    nextMessages.push(createApprovalMessage(response, timestamp));
  }

  if (nextMessages.length === 0) {
    nextMessages.push(createAssistantMessage(`assistant-${timestamp}`, "요청을 확인했어요."));
  }

  return nextMessages;
}

function createMessagesFromConfirmResponse(response: AgentToolConfirmResponse, timestamp: number) {
  const nextMessages: AgentChatMessage[] = [];

  if (response.message.trim()) {
    nextMessages.push(createAssistantMessage(`assistant-confirm-${timestamp}`, response.message));
  }

  if (response.error) {
    nextMessages.push(createAgentErrorMessage(`error-confirm-${timestamp}`, "작업을 완료하지 못했어요", response.error.message, {
      tone: response.error.retryable ? "amber" : "info",
    }));
  }

  const resultMessage = createResultMessage(`result-confirm-${timestamp}`, response.ui_action);
  if (resultMessage) {
    nextMessages.push(resultMessage);
  }

  return nextMessages.length > 0
    ? nextMessages
    : [createAssistantMessage(`assistant-confirm-${timestamp}`, "요청을 처리했어요.")];
}

const resolveNavigateUrl = (action: AgentUiAction) => {
  if (action.type !== "navigate") {
    return null;
  }

  if (action.target === "home") return "/";
  if (action.target === "login") return "/login";
  if (action.target === "checkout") return "/checkout";
  if (action.target === "product_detail") {
    const productId = readString(action.payload.product_id) ?? readString(action.payload.id);
    return productId ? `/product-detail?id=${encodeURIComponent(productId)}` : null;
  }
  if (action.target === "order_detail") {
    const orderCode = readString(action.payload.order_code);
    return orderCode ? `/payment-complete?order_code=${encodeURIComponent(orderCode)}` : null;
  }

  return null;
};

const applyAgentUiAction = (
  action: AgentUiAction,
  items: AgentResponseItem[] = [],
  message = "",
  currentProductId: string | null,
  openComparison: (intent: ProductComparisonIntent) => void,
) => {
  const comparisonIntent = createComparisonIntent(action, items, message, currentProductId);
  if (comparisonIntent) {
    openComparison(comparisonIntent);
    return;
  }

  const url = resolveNavigateUrl(action);
  if (!url) {
    return;
  }

  navigateWithinApp(url).catch(() => {
    window.location.href = url;
  });
};

function AgentFloatingButton({
  isAgentResponding = false,
  skinProfileStatus = "empty",
  surface = "home",
}: AgentFloatingButtonProps) {
  const { openComparison } = useProductComparison();
  const [activeView, setActiveView] = useState<AgentChatView>("home");
  const [conversationId, setConversationId] = useState<string | null>(readStoredConversationId);
  const [isOpen, setIsOpen] = useState(false);
  const [isChatMounted, setIsChatMounted] = useState(false);
  const [isTeaserVisible, setIsTeaserVisible] = useState(surface !== "home" && surface !== "minimal");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [draft, setDraft] = useState("");
  const [lastSentMessage, setLastSentMessage] = useState("");
  const [messages, setMessages] = useState<AgentChatMessage[]>(readStoredMessages);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [chatThreads, setChatThreads] = useState<AgentChatThreadSummary[]>(readStoredThreads);
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const chatPopupRef = useRef<HTMLElement | null>(null);
  const triggerButtonRef = useRef<HTMLButtonElement | null>(null);
  const teaserRef = useRef<HTMLDivElement | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const teaserTimerRef = useRef<number | null>(null);
  const teaserVisibilityFrameRef = useRef<number | null>(null);
  const hasDismissedTeaserRef = useRef(false);
  const previousSurfaceRef = useRef(surface);
  const quickQuestions = useMemo(
    () => (surface === "productDetail" ? productQuickQuestions : homeQuickQuestions),
    [surface],
  );
  const isThreadView = activeView === "thread" && messages.length > 0;
  const isAgentBusy = isSubmitting || isAgentResponding;
  const hasSkinProfile = skinProfileStatus !== "empty";
  const skinProfileChipLabel = skinProfileStatus === "saved"
    ? "내 피부 타입 적용 중"
    : skinProfileStatus === "temporary"
      ? "현재 선택한 피부 타입 적용 중"
      : "피부 정보를 추가하면 더 정확히 답변해드려요";

  const openChat = () => {
    setIsTeaserVisible(false);
    if (closeTimerRef.current !== null && typeof window !== "undefined") {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsChatMounted(true);
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => setIsOpen(true));
    } else {
      setIsOpen(true);
    }
  };

  const closeChat = () => {
    setIsOpen(false);
    hasDismissedTeaserRef.current = true;
    setIsTeaserVisible(false);
    triggerButtonRef.current?.focus();
    if (typeof window !== "undefined") {
      closeTimerRef.current = window.setTimeout(() => {
        setIsChatMounted(false);
        closeTimerRef.current = null;
      }, 400);
    } else {
      setIsChatMounted(false);
    }
  };

  const handleTeaserClick = (question: string) => {
    openChat();
    void sendMessage(question);
  };

  const hasContentBehindTeaser = () => {
    const teaser = teaserRef.current;
    if (!teaser || typeof window === "undefined") {
      return false;
    }

    const rect = teaser.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      return false;
    }

    const points = [
      [rect.left + rect.width * 0.5, rect.top + rect.height * 0.2],
      [rect.left + rect.width * 0.5, rect.top + rect.height * 0.5],
      [rect.left + rect.width * 0.5, rect.top + rect.height * 0.8],
    ];
    const previousVisibility = teaser.style.visibility;
    teaser.style.visibility = "hidden";

    try {
      return points.some(([x, y]) => {
        const elements = document.elementsFromPoint(x, y);
        return elements.some((element) => {
          if (element === document.body || element === document.documentElement) {
            return false;
          }

          const agentElement = element.closest(".agent-floating-entry");
          if (agentElement || element.closest("[aria-hidden=\"true\"]")) {
            return false;
          }

          const tagName = element.tagName.toLowerCase();
          if (["img", "picture", "video", "canvas", "svg"].includes(tagName)) {
            return true;
          }

          if (element.children.length === 0 && element.textContent?.trim()) {
            const style = window.getComputedStyle(element);
            return style.display !== "none" && style.visibility !== "hidden";
          }

          return false;
        });
      });
    } finally {
      teaser.style.visibility = previousVisibility;
    }
  };

  const updateTeaserVisibility = () => {
    if (isOpen || surface === "minimal" || hasDismissedTeaserRef.current) {
      setIsTeaserVisible(false);
      return;
    }

    setIsTeaserVisible(!hasContentBehindTeaser());
  };

  const scheduleTeaserVisibilityCheck = () => {
    if (typeof window === "undefined" || teaserVisibilityFrameRef.current !== null) {
      return;
    }

    teaserVisibilityFrameRef.current = window.requestAnimationFrame(() => {
      teaserVisibilityFrameRef.current = null;
      updateTeaserVisibility();
    });
  };

  useEffect(() => {
    if (previousSurfaceRef.current !== surface) {
      previousSurfaceRef.current = surface;
      hasDismissedTeaserRef.current = false;
      setIsTeaserVisible(surface !== "home" && surface !== "minimal");
    }

    if (surface === "minimal" || hasDismissedTeaserRef.current) {
      setIsTeaserVisible(false);
      return undefined;
    }

    const scheduleIdle = () => {
      if (teaserTimerRef.current !== null) {
        window.clearTimeout(teaserTimerRef.current);
      }
      teaserTimerRef.current = window.setTimeout(scheduleTeaserVisibilityCheck, 2500);
    };

    const handleScroll = () => {
      scheduleTeaserVisibilityCheck();
    };

    const handleResize = () => {
      scheduleTeaserVisibilityCheck();
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", handleResize);
    if (surface === "home") {
      scheduleIdle();
    } else {
      scheduleTeaserVisibilityCheck();
    }

    return () => {
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleResize);
      if (teaserTimerRef.current !== null) {
        window.clearTimeout(teaserTimerRef.current);
      }
      if (teaserVisibilityFrameRef.current !== null) {
        window.cancelAnimationFrame(teaserVisibilityFrameRef.current);
        teaserVisibilityFrameRef.current = null;
      }
    };
  }, [isOpen, surface]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeChat();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (chatPopupRef.current?.contains(target) || triggerButtonRef.current?.contains(target)) {
        return;
      }
      closeChat();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || typeof window === "undefined") {
      return undefined;
    }

    const animationFrame = window.requestAnimationFrame(() => chatInputRef.current?.focus());
    return () => window.cancelAnimationFrame(animationFrame);
  }, [isOpen]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(AGENT_CHAT_HISTORY_KEY, JSON.stringify(messages.slice(-MAX_STORED_AGENT_MESSAGES)));
  }, [messages]);

  useEffect(() => {
    if (!currentThreadId || messages.length === 0) {
      return;
    }

    setChatThreads((currentThreads) =>
      upsertAgentChatThread(currentThreads, {
        id: currentThreadId,
        conversationId,
        messages: messages.slice(-MAX_STORED_AGENT_MESSAGES),
        title: createThreadTitleFromMessages(messages),
        updatedAt: Date.now(),
      }),
    );
  }, [conversationId, currentThreadId, messages]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(AGENT_CHAT_THREADS_KEY, JSON.stringify(chatThreads.slice(0, MAX_AGENT_CHAT_THREADS)));
  }, [chatThreads]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    if (conversationId) {
      window.localStorage.setItem(AGENT_CONVERSATION_ID_KEY, conversationId);
    } else {
      window.localStorage.removeItem(AGENT_CONVERSATION_ID_KEY);
    }
  }, [conversationId]);

  useEffect(() => {
    if (!isOpen || !isThreadView || typeof window === "undefined") {
      return undefined;
    }

    const animationFrame = window.requestAnimationFrame(() => {
      threadEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [isOpen, isThreadView, messages]);

  const appendMessages = (nextMessages: AgentChatMessage[]) => {
    setMessages((currentMessages) => [...currentMessages, ...nextMessages].slice(-MAX_STORED_AGENT_MESSAGES));
    setActiveView("thread");
  };

  const openChatThread = (thread: AgentChatThreadSummary) => {
    setCurrentThreadId(thread.id);
    setConversationId(thread.conversationId);
    setMessages(thread.messages);
    setActiveView("thread");
  };

  const sendMessage = async (message: string) => {
    const nextMessage = message.trim();

    if (!nextMessage || isSubmitting) {
      return;
    }

    const timestamp = Date.now();
    const statusId = `status-${timestamp}`;
    const shouldStartNewThread = activeView === "home";
    const requestConversationId = shouldStartNewThread ? null : conversationId;
    const nextThreadId = shouldStartNewThread || !currentThreadId ? `thread-${timestamp}` : currentThreadId;
    const userMessage: AgentChatTextMessage = {
      id: `user-${timestamp}`,
      content: nextMessage,
      kind: "chat",
      role: "user",
    };

    setLastSentMessage(nextMessage);
    if (shouldStartNewThread) {
      setCurrentThreadId(nextThreadId);
      setConversationId(null);
      setMessages([userMessage, createStatusMessage(statusId, true)]);
      setActiveView("thread");
    } else {
      if (!currentThreadId) {
        setCurrentThreadId(nextThreadId);
      }
      appendMessages([userMessage, createStatusMessage(statusId, true)]);
    }
    setDraft("");
    setIsSubmitting(true);

    try {
      const response = await api.sendAgentMessage({
        context: buildAgentContext(),
        conversation_id: requestConversationId,
        message: nextMessage,
      });
      const responseTimestamp = Date.now();
      setConversationId(response.conversation_id);
      const isRecommendationResponse = response.ui_action.type === "show_products"
        || response.ui_action.type === "show_product_comparison"
        || response.items.some((item) => item.item_type === "product");
      setMessages((currentMessages) =>
        [
          ...currentMessages.flatMap((currentMessage) =>
            currentMessage.id === statusId
              ? (isRecommendationResponse ? [createStatusMessage(statusId)] : [])
              : [currentMessage],
          ),
          ...createMessagesFromAgentResponse(response, responseTimestamp, nextMessage),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
      applyAgentUiAction(
        response.ui_action,
        response.items,
        response.message,
        buildAgentContext().current_product_id ?? null,
        openComparison,
      );
    } catch (error) {
      setMessages((currentMessages) =>
        [
          ...currentMessages.filter((currentMessage) => currentMessage.id !== statusId),
          createAgentErrorFromUnknown(error, `error-${Date.now()}`, nextMessage),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void sendMessage(draft);
  };

  const confirmApproval = async (messageId: string, action: "confirm" | "reject") => {
    const approvalMessage = messages.find(
      (message): message is AgentChatApprovalMessage => message.id === messageId && message.kind === "approval",
    );

    if (!approvalMessage?.toolCallId || isSubmitting) {
      return;
    }

    const statusId = `status-confirm-${Date.now()}`;
    setIsSubmitting(true);
    appendMessages([createStatusMessage(statusId, true)]);

    try {
      const response = await api.confirmAgentToolCall(approvalMessage.toolCallId, { action });
      const timestamp = Date.now();
      const isRecommendationResponse = response.ui_action.type === "show_products"
        || response.ui_action.type === "show_product_comparison";
      setMessages((currentMessages) =>
        [
          ...currentMessages
            .filter((message) => message.id !== statusId)
            .map((message) =>
              message.id === messageId && message.kind === "approval"
                ? { ...message, resolved: action === "confirm" ? "approved" as const : "cancelled" as const }
                : message,
            ),
          ...(isRecommendationResponse ? [createStatusMessage(`status-confirmed-${timestamp}`)] : []),
          ...createMessagesFromConfirmResponse(response, timestamp),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
      applyAgentUiAction(response.ui_action, [], "", buildAgentContext().current_product_id ?? null, openComparison);
    } catch (error) {
      setMessages((currentMessages) =>
        [
          ...currentMessages.filter((message) => message.id !== statusId),
          createAgentErrorFromUnknown(error, `error-confirm-${Date.now()}`),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetry = (retryMessage?: string) => {
    const nextRetryMessage = retryMessage || lastSentMessage;
    if (nextRetryMessage) {
      void sendMessage(nextRetryMessage);
    }
  };

  const handleRegenerate = () => {
    handleRetry(lastSentMessage);
  };

  const handleCopyAnswer = (content: string) => {
    if (typeof window !== "undefined" && window.navigator.clipboard) {
      window.navigator.clipboard.writeText(content).catch(() => undefined);
    }
  };

  const renderStatusMessage = (message: AgentChatStatusMessage) => (
    message.steps.some((step) => step.status === "active") ? (
      <div className="agent-chat-typing" key={message.id} aria-label="답변을 준비하고 있어요">
        <img alt="" src="/mwobareullae-rabbit-chat.png" />
        <span className="agent-chat-typing-dots" aria-hidden="true"><i /><i /><i /></span>
      </div>
    ) : (
      <div className="agent-chat-status-card" key={message.id}>
        <div className="agent-chat-status-head">
          <span className="agent-chat-status-badge" aria-hidden="true">✓</span>
          <strong>{message.title}</strong>
        </div>
        <div className="agent-chat-status-steps">
          {message.steps.map((step) => (
            <div className={`agent-chat-status-step ${step.status}`} key={step.label}>
              <span aria-hidden="true" />
              <span>{step.label}</span>
            </div>
          ))}
        </div>
      </div>
    )
  );

  const renderApprovalMessage = (message: AgentChatApprovalMessage) => {
    const isResolved = Boolean(message.resolved);

    return (
      <div className={`agent-chat-approval-card${isResolved ? " resolved" : ""}`} key={message.id}>
        <span className="agent-chat-approval-icon" aria-hidden="true">?</span>
        <strong>{message.title}</strong>
        <p>{message.description}</p>
        <div className="agent-chat-approval-actions">
          <button
            disabled={isResolved || isSubmitting || !message.toolCallId}
            onClick={() => void confirmApproval(message.id, "confirm")}
            type="button"
          >
            {message.approveLabel}
          </button>
          <button
            disabled={isResolved || isSubmitting || !message.toolCallId}
            onClick={() => void confirmApproval(message.id, "reject")}
            type="button"
          >
            {message.rejectLabel}
          </button>
        </div>
        {message.resolved ? <span className="agent-chat-approval-state">{message.resolved === "approved" ? "승인됨" : "취소됨"}</span> : null}
      </div>
    );
  };

  const handleErrorAction = (message: AgentChatErrorMessage) => {
    if (message.action === "login") {
      const redirect = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.href = `/login?redirect=${encodeURIComponent(redirect)}`;
      return;
    }

    if (message.action === "profile") {
      void navigateWithinApp("/signup/skin-profile");
      return;
    }

    handleRetry(message.retryMessage);
  };

  const renderErrorMessage = (message: AgentChatErrorMessage) => (
    <div className={`agent-chat-error-card ${message.tone}`} key={message.id}>
      <span className="agent-chat-error-icon" aria-hidden="true">{message.tone === "amber" ? "!" : "i"}</span>
      <strong>{message.title}</strong>
      <p>{message.message}</p>
      <button disabled={isSubmitting} onClick={() => handleErrorAction(message)} type="button">
        {message.actionLabel}
      </button>
    </div>
  );

  const openResultItem = (item: AgentChatResultItem) => {
    if (item.itemType === "product") {
      void navigateWithinApp(`/product-detail?id=${encodeURIComponent(item.id)}`);
    }
  };

  const openResultAction = (actionUrl?: string | null) => {
    if (!actionUrl) {
      return;
    }

    navigateWithinApp(actionUrl).catch(() => {
      window.location.href = actionUrl;
    });
  };

  const renderResultMessage = (message: AgentChatResultMessage) => {
    const previewItems = message.actionType === "show_products"
      ? message.items.slice(0, MAX_AGENT_PRODUCT_PREVIEW_ITEMS)
      : message.items;

    return (
      <div className="agent-chat-result-card" key={message.id}>
        <strong>{message.title}</strong>
        <p>{message.description}</p>
        {previewItems.length > 0 ? (
          <div className="agent-chat-result-list">
            {previewItems.map((item) => {
              const priceText = formatAgentPrice(item.price);
              return (
                <button
                  className="agent-chat-result-item"
                  disabled={item.itemType !== "product"}
                  key={`${item.itemType}-${item.id}`}
                  onClick={() => openResultItem(item)}
                  type="button"
                >
                  <span>
                    <strong>{item.title}</strong>
                    {item.subtitle ? <small>{item.subtitle}</small> : null}
                  </span>
                  {priceText ? <em>{priceText}</em> : null}
                </button>
              );
            })}
          </div>
        ) : null}
        {message.actionType === "show_products" && message.actionUrl ? (
          <button
            className="agent-chat-result-more"
            onClick={() => openResultAction(message.actionUrl)}
            type="button"
          >
            전체 보기
          </button>
        ) : null}
      </div>
    );
  };

  const renderTextMessage = (message: AgentChatTextMessage) => (
    <div className={`agent-chat-message-group ${message.role}`} key={message.id}>
      <div className={`agent-chat-message-line ${message.role}`}>
        {message.role === "assistant" ? <img alt="" src="/mwobareullae-rabbit-chat.png" /> : null}
        <div className={`agent-chat-message ${message.role}`}>{message.content}</div>
      </div>
      {message.role === "assistant" && message.showActions ? (
        <>
          <div className="agent-chat-actions" aria-label="답변 액션">
            <button aria-label="좋아요" type="button">
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M10 14v13H6V14h4Zm0 13h11.1a3 3 0 0 0 2.92-2.3l1.35-5.76A3 3 0 0 0 22.45 15H18l.66-4.62A3 3 0 0 0 15.7 7L10 14v13Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button aria-label="별로예요" type="button">
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M10 18V5H6v13h4Zm0-13h11.1a3 3 0 0 1 2.92 2.3l1.35 5.76A3 3 0 0 1 22.45 14H18l.66 4.62A3 3 0 0 1 15.7 22L10 15v-10Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button aria-label="다시 생성" onClick={handleRegenerate} type="button">
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M25 12a10 10 0 1 0 1 8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" /><path d="M25 6v6h-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button aria-label="복사" onClick={() => handleCopyAnswer(message.content)} type="button">
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><rect height="15" rx="2" stroke="currentColor" strokeWidth="1.8" width="15" x="11" y="11" /><path d="M21 11V8a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h3" stroke="currentColor" strokeWidth="1.8" /></svg>
            </button>
          </div>
        </>
      ) : null}
    </div>
  );

  const renderMessage = (message: AgentChatMessage) => {
    if (message.kind === "status") {
      return renderStatusMessage(message);
    }

    if (message.kind === "approval") {
      return renderApprovalMessage(message);
    }

    if (message.kind === "error") {
      return renderErrorMessage(message);
    }

    if (message.kind === "result") {
      return renderResultMessage(message);
    }

    return renderTextMessage(message);
  };

  return (
    <>
      <div className={`agent-floating-entry${isOpen ? " is-open" : ""}`} aria-label="AI 에이전트 진입점">
        <div
          ref={teaserRef}
          className={`agent-floating-entry__teasers${!isTeaserVisible || (isChatMounted && isOpen) ? " is-hidden" : ""}`}
        >
          {surface === "productDetail" ? (
            <button onClick={() => handleTeaserClick("비슷한 상품 비교해줘")} type="button">
              비슷한 상품 비교해줘
            </button>
          ) : (
            <>
              <button onClick={() => handleTeaserClick("피부 고민을 같이 찾아볼까요?")} type="button">
                피부 고민을 같이 찾아볼까요?
              </button>
              <button onClick={() => handleTeaserClick("궁금한 성분을 물어보세요")} type="button">
                궁금한 성분을 물어보세요
              </button>
            </>
          )}
        </div>
        {isChatMounted ? (
          <section
            aria-modal={isOpen ? "true" : undefined}
            aria-labelledby="agent-chat-title"
            className={`agent-chat-popup${isOpen ? " is-visible" : ""}`}
            id="agent-chat-popup"
            ref={chatPopupRef}
            role="dialog"
          >
            <span className="agent-chat-popup__tail" aria-hidden="true" />
            <div className={`agent-chat-popup__head${isThreadView ? " has-back" : ""}`}>
              <span className="agent-chat-popup__avatar" aria-hidden="true">
                <img alt="" src="/mwobareullae-rabbit-chat-sky.png" />
              </span>
              <div className="agent-chat-popup__title">
                <h2 id="agent-chat-title">뭐바를래 AI</h2>
                <p>성분 근거로 답해드려요</p>
              </div>
              {isThreadView ? (
                <button className="agent-chat-back-button" onClick={() => setActiveView("home")} type="button">
                  <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
                    <path
                      d="M15 18 9 12l6-6"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>뒤로</span>
                </button>
              ) : null}
            </div>

            <div className="agent-chat-popup__body">
              {isThreadView ? (
                <div className="agent-chat-thread" aria-live="polite">
                  {messages.map((message) => renderMessage(message))}
                  <div ref={threadEndRef} aria-hidden="true" />
                </div>
              ) : (
                <>
                  <div className={`agent-chat-profile-chip${hasSkinProfile ? "" : " empty"}`} role="status">
                    <span aria-hidden="true">{hasSkinProfile ? "✓" : "＋"}</span>
                    <span>{skinProfileChipLabel}</span>
                  </div>

                  <div className="agent-chat-divider" />
                  <div className="agent-chat-section-label">빠른 질문</div>
                    <div className="agent-chat-quick-questions">
                    {quickQuestions.map((question) => (
                      <button
                      className="agent-chat-question-row quick"
                      disabled={isSubmitting}
                      key={question}
                      onClick={() => void sendMessage(question)}
                      type="button"
                    >
                      <span className="agent-chat-row-icon" aria-hidden="true">
                        <svg fill="none" viewBox="0 0 24 24">
                          <path
                            d="M12 3.5 14 8l4.5 2-4.5 2-2 4.5-2-4.5-4.5-2 4.5-2L12 3.5Z"
                            stroke="currentColor"
                            strokeLinejoin="round"
                            strokeWidth="1.8"
                          />
                          <path
                            d="M18.5 15.5v3M20 17h-3M5.5 4.5v2M6.5 5.5h-2"
                            stroke="currentColor"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="1.8"
                          />
                        </svg>
                      </span>
                      <span>{question}</span>
                      <span aria-hidden="true">›</span>
                      </button>
                    ))}
                    </div>

                  {chatThreads.length > 0 ? (
                    <>
                      <div className="agent-chat-divider" />
                      <div className="agent-chat-section-label">최근 대화</div>
                      {chatThreads.map((thread) => (
                        <button
                          aria-label={`${thread.title} 대화 열기`}
                          className="agent-chat-question-row"
                          disabled={isSubmitting}
                          key={thread.id}
                          onClick={() => openChatThread(thread)}
                          type="button"
                        >
                          <span className="agent-chat-row-icon" aria-hidden="true">
                            <svg fill="none" viewBox="0 0 24 24">
                              <path
                                d="M5 6.5a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H9.25L5 17.5v-11Z"
                                stroke="currentColor"
                                strokeLinejoin="round"
                                strokeWidth="1.8"
                              />
                              <path
                                d="M8.5 8.5h7M8.5 11.5h4.5"
                                stroke="currentColor"
                                strokeLinecap="round"
                                strokeWidth="1.8"
                              />
                            </svg>
                          </span>
                          <span>{thread.title}</span>
                          <span aria-hidden="true">›</span>
                        </button>
                      ))}
                    </>
                  ) : null}

                </>
              )}
            </div>

            <form className="agent-chat-input" onSubmit={handleSubmit}>
              <input
                aria-label="AI에게 질문 입력"
                disabled={isSubmitting}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="무엇이든 물어보세요"
                ref={chatInputRef}
                value={draft}
              />
              <button aria-label="질문 전송" disabled={!draft.trim() || isSubmitting} type="submit">
                <svg fill="none" viewBox="0 0 24 24">
                  <path d="M12 19V5" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
                  <path d="m6.5 10.5 5.5-5.5 5.5 5.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </button>
            </form>
          </section>
        ) : null}

        <button
          aria-controls="agent-chat-popup"
          aria-expanded={isOpen}
          className={`agent-floating-entry__button${isOpen ? " is-open" : ""}`}
          onClick={() => (isOpen ? closeChat() : openChat())}
          ref={triggerButtonRef}
          type="button"
          aria-label={isOpen ? "뭐바를래 AI 닫기" : "뭐바를래 AI 열기"}
        >
          {isOpen ? (
            <svg className="agent-floating-entry__close-icon" aria-hidden="true" fill="none" viewBox="0 0 24 24">
              <path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
            </svg>
          ) : (
            <>
              {isAgentBusy ? <span className="agent-floating-entry__badge" aria-hidden="true" /> : null}
              <svg className="agent-floating-entry__chat-icon" aria-hidden="true" fill="none" viewBox="0 0 32 32">
                <path
                  d="M16 4.5c-6.35 0-11.5 4.7-11.5 10.5 0 2.3.85 4.42 2.3 6.13L5.5 26.5l5.57-2.7c1.48.77 3.15 1.2 4.93 1.2 6.35 0 11.5-4.7 11.5-10.5S22.35 4.5 16 4.5Z"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                />
                <circle cx="10.5" cy="15" fill="currentColor" r="1.4" />
                <circle cx="16" cy="15" fill="currentColor" r="1.4" />
                <circle cx="21.5" cy="15" fill="currentColor" r="1.4" />
              </svg>
            </>
          )}
        </button>
      </div>
    </>
  );
}

export default AgentFloatingButton;
