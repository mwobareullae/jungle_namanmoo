import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { navigateWithinApp } from "../lib/navigation";
import { storeAgentClaimDraft, storeAgentReviewDraft } from "../lib/agentDrafts";
import {
  AGENT_ENTRY_MESSAGE_EVENT,
  AGENT_SHOW_CART_EVENT,
  type AgentEntryMessageDetail,
} from "../lib/agentUiEvents";
import { getProductImageUrl } from "../lib/imageUrls";
import { getSensitiveAgentInputMessage } from "../lib/agentInputSafety";
import { getAgentChatStorageKeys, type AgentChatStorageScope } from "../lib/agentChatStorage";
import { getOrderDetail } from "../lib/orderApi";
import { clearAllWishlistCache } from "../lib/activityApi";
import { playAgentClickInteraction, waitForAgentInteraction } from "../lib/agentVisualInteraction";
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
  isAuthenticated?: boolean;
  quickQuestionContext?: QuickQuestionContext;
  skinProfile?: {
    avoidIngredients?: string[];
    sensitivity: string;
    skin: string;
  };
  skinProfileStatus?: "empty" | "saved" | "temporary";
  storageScope: AgentChatStorageScope;
  surface?: "home" | "productDetail" | "context" | "minimal";
};

type QuickQuestionContext =
  | "auth"
  | "cart"
  | "checkout"
  | "home"
  | "mypage"
  | "order"
  | "productDetail"
  | "productList"
  | "recent"
  | "searchResults"
  | "skinProfile"
  | "wishlist";

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
  sensitive?: boolean;
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
  action: "input" | "login" | "profile" | "retry";
  actionLabel: string;
  kind: "error";
  idempotencyKey?: string;
  message: string;
  retryMessage?: string;
  title: string;
  tone: "amber" | "info";
};

type AgentChatResultItem = {
  id: string;
  imageUrl?: string | null;
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
type AgentAnswerReaction = "like" | "dislike";

type AgentChatThreadSummary = {
  conversationId: string | null;
  id: string;
  messages: AgentChatMessage[];
  title: string;
  updatedAt: number;
};

const MAX_AGENT_CHAT_THREADS = 5;
const MAX_AGENT_PRODUCT_PREVIEW_ITEMS = 3;
const MAX_AGENT_CONTEXT_MESSAGES = 8;
const MAX_AGENT_CONTEXT_RESULT_ITEMS = 10;
const MAX_STORED_AGENT_MESSAGES = 24;
const MAX_AGENT_CHAT_THREAD_TITLE_LENGTH = 36;
const REDACTED_ADDRESS_MESSAGE = "배송지 정보를 입력했어요.";
const composeCategoryLabelMap: Record<string, string> = {
  toner: "토너",
  serum: "세럼",
  cream: "크림",
};

const quickQuestionsByContext: Record<QuickQuestionContext, string[]> = {
  auth: [
    "로그인하면 장바구니와 주문을 어떻게 이어서 볼 수 있어?",
    "로그인 후 내 피부 타입으로 맞춤 루틴을 만들고 싶어",
    "비회원으로 이용할 수 있는 기능을 알려줘",
  ],
  cart: [
    "현재 장바구니 상품으로 주문서 열어줘",
    "내 피부에 맞는 토너와 크림을 5만원 안으로 추가해줘",
    "장바구니 상품과 총금액 다시 보여줘",
  ],
  checkout: [
    "이 주문서 내용으로 주문 생성해줘",
    "이 주문서로 결제 진행해줘",
    "결제 예정 금액과 배송지를 다시 확인해줘",
  ],
  home: [
    "내 피부 타입에 맞는 토너, 세럼, 크림을 5만원 이내로 구성해줘",
    "최근 주문 배송 상태 알려줘",
    "장바구니에 담긴 상품과 총금액 보여줘",
  ],
  mypage: [
    "최근 주문 배송 상태 보여줘",
    "내 피부 타입에 맞는 토너와 크림을 5만원 이내로 구성해줘",
    "내 장바구니 상품과 총금액 보여줘",
  ],
  order: [
    "현재 주문 상태와 상품을 보여줘",
    "현재 주문을 취소해줘",
    "최근 주문 배송 상태를 보여줘",
  ],
  productDetail: [
    "이 상품과 비슷한 상품 2개 보여줘",
    "이 상품을 장바구니에 담아줘",
    "이 상품과 비슷한 상품을 비교해줘",
  ],
  productList: [
    "화면에 보이는 첫 두 상품을 비교해줘",
    "화면 상품 중 5만원 이하만 보여줘",
    "화면 상품을 내 피부 타입 기준으로 추려줘",
  ],
  recent: [
    "최근 본 첫 두 상품을 비교해줘",
    "최근 본 상품 중 5만원 이하만 보여줘",
    "최근 본 상품을 내 피부 타입 기준으로 추려줘",
  ],
  searchResults: [
    "2만원대 상품만 보여줘",
    "3만원 이하 세럼만 보여줘",
    "추천 결과 상위 2개 비교해줘",
  ],
  skinProfile: [
    "내 피부 타입에 맞는 토너, 세럼, 크림을 추천해줘",
    "민감도에 맞는 진정 제품 3개 추천해줘",
    "피부 고민에 맞는 성분 근거 제품을 보여줘",
  ],
  wishlist: [
    "찜한 첫 두 상품을 비교해줘",
    "찜한 상품 중 5만원 이하만 보여줘",
    "찜한 상품을 내 피부 타입 기준으로 추려줘",
  ],
};

const miniChatLabelsByContext: Record<QuickQuestionContext, string[]> = {
  auth: ["로그인하면 이어지는 기능은?", "로그인 후 맞춤 루틴 만들기"],
  cart: ["이 장바구니로 주문서 열어줘", "5만원 맞춤 상품 추가해줘"],
  checkout: ["이 주문서로 주문 생성해줘", "결제 진행해줘"],
  home: ["5만원 맞춤 루틴 구성해줘", "최근 주문 배송 보여줘"],
  mypage: ["최근 주문 배송 보여줘", "5만원 맞춤 루틴 구성해줘"],
  order: ["현재 주문 상태 보여줘", "현재 주문 취소해줘"],
  productDetail: ["비슷한 상품 2개 보여줘", "이 상품 장바구니에 담아줘"],
  productList: ["첫 두 상품 비교해줘", "5만원 이하 상품만 보여줘"],
  recent: ["최근 본 두 상품 비교해줘", "5만원 이하만 보여줘"],
  searchResults: ["2만원대 상품만 보여줘", "3만원 이하 세럼만 보여줘"],
  skinProfile: ["내 피부 타입에 맞는 제품 추천해줘", "민감도에 맞는 진정 제품 추천해줘"],
  wishlist: ["찜한 두 상품 비교해줘", "5만원 이하만 보여줘"],
};

const guestQuickQuestionsByContext: Partial<Record<QuickQuestionContext, string[]>> = {
  home: [
    "내 피부 고민에 맞는 제품 추천해줘",
    "5만원 이하 제품 추천해줘",
    "장바구니 상품과 총금액 보여줘",
  ],
  cart: [
    "장바구니 상품과 총금액 보여줘",
    "내 피부 고민에 맞는 제품 추천해줘",
    "5만원 이하 제품 추천해줘",
  ],
  skinProfile: [
    "내 피부 고민에 맞는 제품 추천해줘",
    "민감 피부 진정 제품 추천해줘",
    "피부 프로필 설정 방법 알려줘",
  ],
  searchResults: [
    "2만원대 상품만 보여줘",
    "3만원 이하 세럼만 보여줘",
    "장바구니 상품과 총금액 보여줘",
  ],
};

const guestMiniChatLabelsByContext: Partial<Record<QuickQuestionContext, string[]>> = {
  home: ["피부 고민 제품 추천해줘", "5만원 이하 제품 추천해줘"],
  cart: ["장바구니 상품과 총금액 보여줘", "피부 고민 제품 추천해줘"],
  searchResults: ["2만원대 상품만 보여줘", "3만원 이하 세럼만 보여줘"],
  skinProfile: ["내 피부 고민 제품 추천해줘", "민감 피부 진정 제품 추천해줘"],
};

const emptySearchQuickQuestions = [
  "내 피부 고민에 맞는 제품 추천해줘",
  "5만원 이하 제품 추천해줘",
];

const emptySearchMiniChatLabels = ["피부 고민 제품 추천해줘", "5만원 이하 추천해줘"];

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

function getCommerceStatusSteps(message: string, isActive: boolean): { steps: AgentStatusStep[]; title: string } | null {
  if (/인기|베스트/.test(message) && /찜/.test(message) && /(성분|들어간|포함)/.test(message)) {
    return {
      title: isActive ? "인기 상품의 전성분을 확인하고 있어요" : "찜할 상품을 확인했어요",
      steps: [
        { label: "인기 상품 순위 확인", status: "done" },
        { label: "전성분 확인", status: isActive ? "active" : "done" },
        { label: "현재 찜 상태 구분", status: isActive ? "todo" : "done" },
      ],
    };
  }
  if (/배송지|주소|우편번호|연락처/.test(message)) {
    return {
      title: isActive ? "배송지를 등록하고 있어요" : "배송지를 등록했어요",
      steps: [
        { label: "배송지 정보 확인", status: "done" },
        { label: "배송지 등록", status: isActive ? "active" : "done" },
        { label: "주문서 연결", status: isActive ? "todo" : "done" },
      ],
    };
  }
  if (/장바구니.*(담|추가)|(담|추가).*장바구니/.test(message)) {
    return {
      title: isActive ? "상품을 장바구니에 담고 있어요" : "장바구니에 반영했어요",
      steps: [
        { label: "상품 확인", status: "done" },
        { label: "재고·가격 확인", status: isActive ? "active" : "done" },
        { label: "장바구니 화면 반영", status: isActive ? "todo" : "done" },
      ],
    };
  }
  if (/(상품|번째|첫\s*번째|두\s*번째).*(주문|구매)|(주문|구매).*(상품|번째)/.test(message)) {
    return {
      title: isActive ? "상품을 주문서까지 준비하고 있어요" : "주문서 준비를 마쳤어요",
      steps: [
        { label: "요청한 상품 선택", status: "done" },
        { label: "재고·가격 확인", status: isActive ? "active" : "done" },
        { label: "장바구니 반영·주문서 이동", status: isActive ? "todo" : "done" },
      ],
    };
  }
  if (/주문|결제|체크아웃/.test(message)) {
    return {
      title: isActive ? "주문 내용을 준비하고 있어요" : "주문 준비를 마쳤어요",
      steps: [
        { label: "장바구니 확인", status: "done" },
        { label: "배송지·재고 확인", status: isActive ? "active" : "done" },
        { label: "결제 금액 계산", status: isActive ? "todo" : "done" },
      ],
    };
  }
  return null;
}

function createStatusMessage(id: string, isActive = false, message = ""): AgentChatStatusMessage {
  const commerceStatus = getCommerceStatusSteps(message, isActive);
  return {
    id,
    kind: "status",
    steps: commerceStatus?.steps ?? (isActive ? activeStatusSteps : completedStatusSteps),
    title: commerceStatus?.title ?? (isActive ? "상품 정보를 확인하고 있어요" : "추천 근거를 확인했어요"),
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
              candidate.action === "input" || candidate.action === "login" || candidate.action === "profile" || candidate.action === "retry"
                ? candidate.action
                : "retry",
          actionLabel: candidate.actionLabel,
          createdAt,
          kind: "error",
          idempotencyKey: typeof candidate.idempotencyKey === "string" ? candidate.idempotencyKey : undefined,
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

function readStoredMessages(storageScope: AgentChatStorageScope) {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const storedMessages = window.localStorage.getItem(getAgentChatStorageKeys(storageScope).history);

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

function readStoredConversationId(storageScope: AgentChatStorageScope) {
  if (typeof window === "undefined") {
    return null;
  }

  return readString(window.localStorage.getItem(getAgentChatStorageKeys(storageScope).conversationId));
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
  return firstUserMessage
    ? createThreadTitle(firstUserMessage.sensitive ? REDACTED_ADDRESS_MESSAGE : firstUserMessage.content)
    : "새 대화";
};

const buildRecentMessages = (messages: AgentChatMessage[]) =>
  messages
    .filter((message): message is AgentChatTextMessage => message.kind === "chat")
    .slice(-MAX_AGENT_CONTEXT_MESSAGES)
    .map((message) => ({
      role: message.role,
      content: (message.sensitive ? REDACTED_ADDRESS_MESSAGE : message.content).slice(0, 2000),
    }));

const sanitizeMessagesForStorage = (messages: AgentChatMessage[]) => messages.map((message) => {
  if (message.kind !== "chat" || !message.sensitive) return message;
  return { ...message, content: REDACTED_ADDRESS_MESSAGE, sensitive: false };
});

const buildLastToolResult = (messages: AgentChatMessage[]) => {
  const result = [...messages].reverse().find(
    (message): message is AgentChatResultMessage => message.kind === "result",
  );
  if (!result) return null;

  return {
    action_type: result.actionType,
    target: result.actionTarget ?? null,
    items: result.items.slice(0, MAX_AGENT_CONTEXT_RESULT_ITEMS).map((item) => ({
      item_type: item.itemType,
      id: item.id,
      title: item.title,
    })),
  };
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

function readStoredThreads(storageScope: AgentChatStorageScope) {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const storedThreads = window.localStorage.getItem(getAgentChatStorageKeys(storageScope).threads);
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

  const legacyMessages = readStoredMessages(storageScope);
  const legacyConversationId = readStoredConversationId(storageScope);
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
  if (pathname === "/mypage/orders") return "order_history";
  if (pathname.startsWith("/mypage/orders/")) return "order_detail";
  if (pathname.startsWith("/checkout")) return "checkout";
  if (pathname.startsWith("/payment-complete")) return "payment_complete";
  if (pathname.startsWith("/skin-test")) return "skin_test";
  if (pathname.startsWith("/login")) return "login";
  return "home";
};

function buildAgentContext(
  skinProfile?: AgentFloatingButtonProps["skinProfile"],
  selectedProductIds: string[] = [],
): AgentContext {
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
  const periodMonths = readNumber(params.get("period_months"));
  const orderStatus = readString(params.get("status"));
  const refineMinPrice = readNumber(params.get("refine_min_price"));
  const refineMaxPrice = readNumber(params.get("refine_max_price"));
  const refineCategoryCode = readString(params.get("refine_category_code"));
  const refineSkinType = readString(params.get("refine_skin_type"));
  const refineSensitivity = readString(params.get("refine_sensitivity"));
  const refineEffects = params.getAll("refine_effect").filter(Boolean);
  const refineIngredients = params.getAll("refine_ingredient").filter(Boolean);

  if (skinType || skinProfile?.skin) filters.skin_type = skinType ?? skinProfile?.skin;
  if (sensitivity || skinProfile?.sensitivity) filters.sensitivity = sensitivity ?? skinProfile?.sensitivity;
  if (skinProfile?.avoidIngredients?.length) filters.avoid_ingredients = skinProfile.avoidIngredients;
  if (pageSize) filters.page_size = pageSize;
  if (page) filters.page = page;
  if (periodMonths) filters.period_months = periodMonths;
  if (orderStatus) filters.status = orderStatus;
  if (refineMinPrice !== null) filters.min_price = refineMinPrice;
  if (refineMaxPrice !== null) filters.max_price = refineMaxPrice;
  if (refineCategoryCode) filters.category_code = refineCategoryCode;
  if (refineSkinType) filters.skin_type = refineSkinType;
  if (refineSensitivity) filters.sensitivity = refineSensitivity;
  if (refineEffects.length) filters.effect_keywords = refineEffects;
  if (refineIngredients.length) filters.required_ingredient_names = refineIngredients;

  const context: AgentContext = {
    page: resolveAgentPage(pathname),
    route: `${pathname}${search}${hash}`,
  };
  const visibleProductIds = collectVisibleProductIds(currentProductId);
  const orderPathMatch = pathname.match(/^\/mypage\/orders\/([^/]+)/);
  const orderCodeFromPath = orderPathMatch?.[1]
    ? (() => {
      try {
        return decodeURIComponent(orderPathMatch[1]);
      } catch {
        return orderPathMatch[1];
      }
    })()
    : null;
  const orderCode = readString(params.get("order_code")) ?? readString(orderCodeFromPath);
  const recommendationId = readString(params.get("recommendation_id"));
  const searchQuery = readString(params.get("keyword"));

  if (currentProductId) context.current_product_id = currentProductId;
  if (Object.keys(filters).length > 0) context.filters = filters;
  if (orderCode) context.order_code = orderCode;
  if (recommendationId) context.recommendation_id = recommendationId;
  if (searchQuery) context.search_query = searchQuery;
  if (visibleProductIds.length > 0) context.visible_product_ids = visibleProductIds;
  if (selectedProductIds.length > 0) context.selected_product_ids = uniqueNonEmpty(selectedProductIds).slice(0, 20);

  return context;
}

const getApprovalCopy = (toolName?: AgentToolName | null) => {
  if (toolName === "bulk_wishlist_by_popular_ingredient") {
    return {
      approveLabel: "찜 목록에 반영",
      description: "표시된 인기 상품 여러 개의 찜 상태를 변경하기 전에 확인이 필요해요.",
      rejectLabel: "반영 안 함",
      title: "조건에 맞는 상품을 모두 찜할까요?",
    };
  }
  if (toolName === "cancel_recent_order") {
    return {
      approveLabel: "취소 진행",
      description: "주문 상태를 바꾸는 작업이라 한 번 더 확인이 필요해요.",
      rejectLabel: "취소 안 함",
      title: "주문 취소를 진행할까요?",
    };
  }

  if (toolName === "prepare_order") {
    return {
      approveLabel: "주문 생성",
      description: "최신 가격과 재고를 다시 확인한 뒤 Toss 주문을 만들어요.",
      rejectLabel: "나중에",
      title: "이 내용으로 주문할까요?",
    };
  }

  if (toolName === "compose_cart") {
    return {
      approveLabel: "장바구니 반영",
      description: "선택한 상품들을 실제 장바구니에 추가하기 전에 확인이 필요해요.",
      rejectLabel: "구성만 보기",
      title: "이 구성으로 장바구니에 담을까요?",
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
  const composePayload = response.tool_name === "compose_cart" ? response.ui_action.payload : null;
  const composeCategories = composePayload && Array.isArray(composePayload.categories)
    ? composePayload.categories.filter((value): value is string => typeof value === "string")
    : [];
  const composeCategoryLabels = composeCategories.map((category) => composeCategoryLabelMap[category] ?? category);
  const composeSkinType = composePayload ? readString(composePayload.skin_type) : null;
  const composeSensitivity = composePayload ? readString(composePayload.sensitivity) : null;
  const composeBudget = composePayload ? readNumber(composePayload.max_budget) : null;
  const composeReason = response.tool_name === "compose_cart"
    ? `저장된 피부 프로필${composeSkinType ? `(${composeSkinType}` : ""}${composeSensitivity ? `·민감도 ${composeSensitivity}` : ""}${composeSkinType ? ")" : ""}과 피해야 할 성분을 반영하고, ${composeCategoryLabels.length > 0 ? composeCategoryLabels.join("·") : "토너·세럼·크림"} 카테고리별 1개씩 총 ${composeCategories.length || 3}개 상품을 골라${composeBudget ? ` ${composeBudget.toLocaleString("ko-KR")}원 이내로` : " 예산 안에서"} 구성했어요.`
    : null;

  return {
    id: `approval-${timestamp}`,
    approveLabel: copy.approveLabel,
    description: composeReason ?? (orderCode ? `${copy.description} 대상 주문: ${orderCode}` : copy.description),
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
  options: Partial<Pick<AgentChatErrorMessage, "action" | "actionLabel" | "idempotencyKey" | "retryMessage" | "tone">> = {},
): AgentChatErrorMessage {
  return {
    id,
    action: options.action ?? "retry",
    actionLabel: options.actionLabel ?? "다시 시도",
    kind: "error",
    idempotencyKey: options.idempotencyKey,
    message,
    retryMessage: options.retryMessage,
    title,
    tone: options.tone ?? "amber",
  };
}

const getAgentProviderErrorCopy = (code: string, status = 0) => {
  if (code === "AGENT_OPENAI_BUSY" || code === "AGENT_OPENAI_RATE_LIMITED" || status === 429) {
    return {
      message: "AI가 다른 요청을 처리하고 있어요. 잠시만 기다려주세요.",
      title: "AI 요청이 잠시 많아요",
    };
  }

  if (code === "AGENT_OPENAI_CIRCUIT_OPEN") {
    return {
      message: "AI 연결에 일시적인 문제가 발생했어요. 약 30초 후 다시 시도해주세요.",
      title: "일시적인 문제가 발생했어요",
    };
  }

  if (code === "AGENT_OPENAI_TIMEOUT" || status === 408 || status === 504) {
    return {
      message: "AI 응답이 지연되고 있어요. 잠시 후 다시 시도해주세요.",
      title: "응답이 지연되고 있어요",
    };
  }

  return null;
};

function createAgentErrorFromUnknown(
  error: unknown,
  id: string,
  retryMessage?: string,
  idempotencyKey?: string,
): AgentChatErrorMessage {
  const apiError = error as Partial<ApiError>;
  const status = typeof apiError.status === "number" ? apiError.status : 0;
  const code = typeof apiError.code === "string" ? apiError.code : "";
  const message = typeof apiError.message === "string" ? apiError.message : "요청을 처리하지 못했어요.";
  const isIdempotencyKeyConflict = code === "AGENT_IDEMPOTENCY_KEY_REUSED";

  if (status === 401 || code === "AGENT_AUTH_REQUIRED") {
    return createAgentErrorMessage(id, "로그인이 필요해요", message, {
      action: "login",
      actionLabel: "로그인하기",
      tone: "info",
    });
  }

  if (code === "AGENT_ADDRESS_REQUIRED" || code === "AGENT_ADDRESS_DETAILS_REQUIRED") {
    return createAgentErrorMessage(id, "배송지가 필요해요", message, {
      action: "input",
      actionLabel: "배송지 입력하기",
      tone: "info",
    });
  }

  if (code === "AGENT_SENSITIVE_INPUT") {
    return createAgentErrorMessage(id, "민감정보는 입력할 수 없어요", message, {
      action: "input",
      actionLabel: "내용 수정",
      tone: "info",
    });
  }

  const providerErrorCopy = getAgentProviderErrorCopy(code, status);
  if (providerErrorCopy) {
    return createAgentErrorMessage(id, providerErrorCopy.title, providerErrorCopy.message, {
      retryMessage,
      idempotencyKey,
    });
  }

  if (code === "AGENT_REQUEST_IN_PROGRESS") {
    return createAgentErrorMessage(id, "같은 요청을 처리 중이에요", message, {
      retryMessage,
      idempotencyKey,
    });
  }

  if (status === 503 || code.startsWith("AGENT_OPENAI_") || code === "AGENT_SDK_NOT_INSTALLED") {
    return createAgentErrorMessage(id, "AI 연결을 확인해야 해요", message, {
      retryMessage,
      idempotencyKey,
    });
  }

  return createAgentErrorMessage(id, "답변을 만들지 못했어요", message, {
    retryMessage,
    // 키 충돌 자체를 재시도할 때는 반드시 새 키를 발급한다.
    idempotencyKey: isIdempotencyKeyConflict ? undefined : idempotencyKey,
  });
}

const createAgentIdempotencyKey = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `agent-${crypto.randomUUID()}`;
  }
  return `agent-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
};

function createAgentErrorFromResponse(
  response: AgentChatResponse,
  id: string,
  retryMessage?: string,
  idempotencyKey?: string,
) {
  if (!response.error) {
    return null;
  }

  if (response.error.code === "AGENT_AUTH_REQUIRED") {
    return createAgentErrorMessage(id, "로그인이 필요해요", response.error.message, {
      action: "login",
      actionLabel: "로그인하기",
      tone: "info",
    });
  }

  if (response.error.code === "AGENT_ADDRESS_REQUIRED" || response.error.code === "AGENT_ADDRESS_DETAILS_REQUIRED") {
    return createAgentErrorMessage(id, "배송지가 필요해요", response.error.message, {
      action: "input",
      actionLabel: "배송지 입력하기",
      tone: "info",
    });
  }

  if (response.error.code === "AGENT_SENSITIVE_INPUT") {
    return createAgentErrorMessage(id, "민감정보는 입력할 수 없어요", response.error.message, {
      action: "input",
      actionLabel: "내용 수정",
      tone: "info",
    });
  }

  if (response.error.code === "AGENT_CLARIFICATION_REQUIRED") {
    return createAgentErrorMessage(id, "추가 선택이 필요해요", response.error.message, {
      action: "input",
      actionLabel: "다시 입력하기",
      tone: "info",
    });
  }

  const providerErrorCopy = getAgentProviderErrorCopy(response.error.code);
  if (providerErrorCopy) {
    return createAgentErrorMessage(id, providerErrorCopy.title, providerErrorCopy.message, {
      retryMessage,
      idempotencyKey,
      tone: "amber",
    });
  }

  if (response.error.code === "AGENT_IDEMPOTENCY_KEY_REUSED") {
    return createAgentErrorMessage(id, "답변을 만들지 못했어요", response.error.message, {
      retryMessage,
      // 충돌한 키를 다시 보내지 않고, 재시도 시 새 키를 발급한다.
      idempotencyKey: undefined,
      tone: "info",
    });
  }

  return createAgentErrorMessage(id, "요청을 처리하지 못했어요", response.error.message, {
    retryMessage,
    idempotencyKey,
    tone: response.error.retryable ? "amber" : "info",
  });
}

const formatAgentPrice = (price?: number | null) =>
  typeof price === "number" ? `${price.toLocaleString("ko-KR")}원` : null;

const mapAgentItem = (item: AgentResponseItem): AgentChatResultItem => ({
  id: item.id,
  imageUrl: getProductImageUrl(item.image_storage_key, "w400") || null,
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
    imageUrl: getProductImageUrl(readString(item.thumbnail_url) ?? readString(item.image_storage_key), "w400") || null,
    itemType: "product",
    price: readNumber(item.price) ?? readNumber(item.lowest_price),
    subtitle: uniqueNonEmpty([brand, stockStatus]).join(" · ") || null,
    title: name,
  };
};

const mapCartPayload = (action: AgentUiAction): AgentChatResultItem[] => {
  if (action.type !== "show_cart" || !Array.isArray(action.payload.items)) return [];

  const currentProductId = typeof window === "undefined"
    ? null
    : new URLSearchParams(window.location.search).get("id");
  const cartItems = action.payload.items.flatMap((item) => {
    if (!isRecord(item) || !isRecord(item.product)) return [];
    const productId = readString(item.product_id) ?? readString(item.product.id);
    const title = readString(item.product.name);
    if (!productId || !title) return [];
    const quantity = readNumber(item.quantity);
    const brand = readString(item.product.brand);
    return [{
      id: productId,
      imageUrl: getProductImageUrl(readString(item.product.thumbnail_url), "w400") || null,
      itemType: "product" as const,
      price: readNumber(item.line_subtotal),
      subtitle: uniqueNonEmpty([brand, quantity ? `${quantity}개` : null]).join(" · ") || null,
      title,
    }];
  });

  const currentItem = currentProductId ? cartItems.find((item) => item.id === currentProductId) : null;
  return currentItem ? [currentItem] : cartItems;
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
  if (action.payload.ingredient_name && Array.isArray(action.payload.products)) return "인기 상품 성분 확인 결과";
  if (action.type === "show_product_comparison") return "상품 비교 결과";
  if (action.type === "show_order_status") return "주문 상태";
  if (action.target === "similar_products") return "비슷한 상품";
  if (action.target === "refined_products") return "조건에 맞는 상품";
  if (action.type === "show_products") return "상품 결과";
  if (action.target === "agent_confirmation") return "추천 장바구니 구성";
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

const overrideSearchResultKeyword = (resultUrl: string, queryOverride?: string) => {
  const normalizedQuery = queryOverride?.trim();
  if (!normalizedQuery || typeof window === "undefined") return resultUrl;

  const url = new URL(resultUrl, window.location.origin);
  if (url.pathname !== "/search") return resultUrl;
  url.searchParams.set("keyword", normalizedQuery);
  return `${url.pathname}${url.search}${url.hash}`;
};

const buildProductsResultUrl = (action: AgentUiAction, queryOverride?: string) => {
  if (action.type !== "show_products") {
    return null;
  }

  const directUrl =
    normalizeInternalResultUrl(action.payload.result_url) ??
    normalizeInternalResultUrl(action.payload.results_url) ??
    normalizeInternalResultUrl(action.payload.url) ??
    normalizeInternalResultUrl(action.payload.href);
  if (directUrl) {
    return overrideSearchResultKeyword(directUrl, queryOverride);
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

  const resultUrl = params.size > 1 || recommendationId || keyword ? `/search?${params.toString()}` : null;
  return resultUrl ? overrideSearchResultKeyword(resultUrl, queryOverride) : null;
};

const resolveAgentSearchProfile = (
  profile?: AgentFloatingButtonProps["skinProfile"],
  resultParams?: URLSearchParams | null,
) => {
  const currentParams = typeof window === "undefined"
    ? new URLSearchParams()
    : new URLSearchParams(window.location.search);

  return {
    avoidIngredients: profile?.avoidIngredients ?? [],
    sensitivity:
      resultParams?.get("sensitivity")
      ?? currentParams.get("sensitivity")
      ?? profile?.sensitivity
      ?? "보통",
    skin:
      resultParams?.get("skin_type")
      ?? currentParams.get("skin_type")
      ?? profile?.skin
      ?? "수부지",
  };
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

  return values.flatMap<ProductComparisonDifference>((value, index) => {
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
  queryOverride?: string,
): AgentChatResultMessage | null {
  const productPayload = Array.isArray(action.payload.products)
    ? action.payload.products.map(mapPayloadProduct).filter((item): item is AgentChatResultItem => item !== null)
    : [];
  const orderPayload = action.type === "show_order_status" ? mapOrderPayload(action) : null;
  const cartPayload = mapCartPayload(action);
  const resultItems = items.length > 0
    ? items.map(mapAgentItem)
    : orderPayload
      ? [orderPayload]
      : cartPayload.length > 0
        ? cartPayload
        : productPayload;

  if (action.type === "noop" && resultItems.length === 0) {
    return null;
  }

  const title = getResultTitle(action);
  const emptyProducts = action.type === "show_products" && resultItems.length === 0;
  const actionUrl = action.type === "show_cart" ? "/cart" : buildProductsResultUrl(action, queryOverride);

  return {
    id,
    actionTarget: action.target ?? null,
    actionType: action.type,
    actionUrl,
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

const buildToolResultContext = (action: AgentUiAction, items: AgentResponseItem[]) => {
  if (action.type === "noop") return null;
  const resultMessage = createResultMessage("context-only", action, items);
  const contextItems = resultMessage?.items ?? items.map(mapAgentItem);
  return {
    action_type: action.type,
    target: action.target ?? null,
    items: contextItems.slice(0, MAX_AGENT_CONTEXT_RESULT_ITEMS).map((item) => ({
      item_type: item.itemType,
      id: item.id,
      title: item.title,
    })),
  };
};

function createMessagesFromAgentResponse(
  response: AgentChatResponse,
  timestamp: number,
  retryMessage: string,
  idempotencyKey?: string,
) {
  const nextMessages: AgentChatMessage[] = [];
  const resultMessage = createResultMessage(
    `result-${timestamp}`,
    response.ui_action,
    response.items,
    retryMessage,
  );

  if (resultMessage) {
    nextMessages.push(resultMessage);
  }

  const errorMessage = createAgentErrorFromResponse(response, `error-${timestamp}`, retryMessage, idempotencyKey);
  if (errorMessage) {
    nextMessages.push(errorMessage);
  }

  if (response.message.trim() && response.error?.code !== "AGENT_CLARIFICATION_REQUIRED") {
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
  if (action.type === "open_payment" && action.target === "toss_payment") {
    const orderCode = readString(action.payload.order_code);
    const amount = readNumber(action.payload.amount);
    if (!orderCode || !amount) return null;
    const params = new URLSearchParams({ agent_order_code: orderCode, agent_amount: String(amount) });
    return `/checkout?${params.toString()}`;
  }

  if (action.type !== "navigate") {
    return null;
  }

  if (action.target === "home") return "/";
  if (action.target === "login") return "/login";
  if (action.target === "checkout") return "/checkout";
  if (action.target === "order_history") {
    const currentParams = window.location.pathname === "/mypage/orders"
      ? new URLSearchParams(window.location.search)
      : new URLSearchParams();
    const periodMonths = readNumber(action.payload.period_months)
      ?? readNumber(currentParams.get("period_months"))
      ?? 12;
    const status = readString(action.payload.status);
    currentParams.set("period_months", String(periodMonths));
    if (status === "ALL") currentParams.delete("status");
    else if (status) currentParams.set("status", status);
    return `/mypage/orders?${currentParams.toString()}`;
  }
  if (action.target === "review_write") {
    const orderCode = readString(action.payload.order_code);
    const params = new URLSearchParams({ agent_draft: "1" });
    if (orderCode) params.set("order_code", orderCode);
    return `/mypage/reviews?${params.toString()}`;
  }
  if (action.target === "claim_request") {
    const orderCode = readString(action.payload.order_code);
    return orderCode ? `/mypage/orders/${encodeURIComponent(orderCode)}/return-request?agent_draft=1` : null;
  }
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

const findVisibleAgentTarget = (selector: string) => Array.from(document.querySelectorAll<HTMLElement>(selector))
  .find((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }) ?? null;

const renderInlineMarkdown = (content: string) => content
  .split(/(\*\*[^*]+\*\*)/g)
  .filter(Boolean)
  .map((part, index) => (
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={`${index}-${part}`}>{part.slice(2, -2)}</strong>
      : part
  ));

/**
 * 에이전트 응답에서 화면에 필요한 최소한의 Markdown만 렌더링한다.
 * 백엔드 응답 내용은 변경하지 않고, 줄바꿈과 연속된 `- ` 목록만 보존한다.
 */
const renderAgentMessageContent = (content: string) => {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let lineIndex = 0;

  while (lineIndex < lines.length) {
    const line = lines[lineIndex];
    if (/^\s*-\s+/.test(line)) {
      const items: string[] = [];
      while (lineIndex < lines.length && /^\s*-\s+/.test(lines[lineIndex])) {
        items.push(lines[lineIndex].replace(/^\s*-\s+/, ""));
        lineIndex += 1;
      }
      nodes.push(
        <ul className="agent-chat-list" key={`list-${lineIndex}`}>
          {items.map((item, itemIndex) => (
            <li key={`${lineIndex}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    nodes.push(
      <span key={`line-${lineIndex}`}>
        {renderInlineMarkdown(line)}
        {lineIndex < lines.length - 1 ? <br /> : null}
      </span>,
    );
    lineIndex += 1;
  }

  return nodes;
};

const resolveAgentInteractionTarget = (action: AgentUiAction) => {
  if (typeof document === "undefined") return null;
  if (action.type === "show_cart") return findVisibleAgentTarget("[data-agent-cart-target]");
  if (action.type === "show_checkout_preview") {
    return findVisibleAgentTarget("[data-agent-cart-navigation-target]");
  }
  if (action.type !== "navigate") return null;

  if (action.target === "home") return findVisibleAgentTarget("[data-agent-home-target]");
  if (action.target === "login") return findVisibleAgentTarget("[data-agent-login-target]");
  if (action.target === "checkout") return findVisibleAgentTarget("[data-agent-checkout-target]");
  if (action.target === "product_detail") {
    const productId = readString(action.payload.product_id) ?? readString(action.payload.id);
    return productId
      ? findVisibleAgentTarget(`[data-agent-product-id="${CSS.escape(productId)}"]`)
      : null;
  }
  return null;
};

const applyAgentUiAction = async (
  action: AgentUiAction,
  items: AgentResponseItem[] = [],
  message = "",
  currentProductId: string | null,
  openComparison: (intent: ProductComparisonIntent) => void,
  searchQueryOverride?: string,
) => {
  if (
    action.type === "open_modal"
    && action.target === "agent_confirmation"
    && normalizeInternalResultUrl(action.payload.result_url) === "/products/popular"
    && typeof window !== "undefined"
  ) {
    await waitForAgentInteraction(240);
    if (window.location.pathname === "/products/popular") {
      window.dispatchEvent(new CustomEvent("agent-popular-wishlist-previewed", { detail: action.payload }));
    } else {
      window.sessionStorage.setItem("agent-popular-wishlist-preview", JSON.stringify(action.payload));
      await navigateWithinApp("/products/popular");
    }
    return;
  }

  if (action.type === "show_products" && action.target === "popular_wishlist" && typeof window !== "undefined") {
    const matchedCount = readNumber(action.payload.matched_count) ?? 0;
    const addedCount = readNumber(action.payload.added_count) ?? 0;
    const alreadyWishedCount = readNumber(action.payload.already_wished_count) ?? 0;
    const allMatchedProductsApplied = addedCount > 0
      && matchedCount > 0
      && addedCount + alreadyWishedCount >= matchedCount;
    if (window.location.pathname !== "/products/popular") {
      window.sessionStorage.setItem("agent-popular-wishlist-result", JSON.stringify(action.payload));
      await navigateWithinApp("/products/popular");
    } else {
      window.sessionStorage.removeItem("agent-popular-wishlist-result");
      window.dispatchEvent(new CustomEvent("agent-popular-wishlist-updated", { detail: action.payload }));
    }
    if (allMatchedProductsApplied) {
      await waitForAgentInteraction(Math.max(900, addedCount * 240 + 520));
      await navigateWithinApp("/mypage/wishlist");
    }
    return;
  }
  const isProductCheckoutFlow = action.payload.agent_flow === "product_checkout";
  if (isProductCheckoutFlow && typeof window !== "undefined") {
    const productId = readString(action.payload.highlight_product_id);
    const productTarget = productId
      ? findVisibleAgentTarget(`[data-agent-product-id="${CSS.escape(productId)}"]`)
      : null;
    await playAgentClickInteraction(productTarget);
    window.dispatchEvent(new Event("cart:updated"));
    await waitForAgentInteraction(360);
  }

  const interactionTarget = resolveAgentInteractionTarget(action);
  await playAgentClickInteraction(interactionTarget);

  if (action.type === "show_cart" && typeof window !== "undefined") {
    const currentProductId = new URLSearchParams(window.location.search).get("id");
    window.dispatchEvent(new CustomEvent(AGENT_SHOW_CART_EVENT, {
      detail: { cart: action.payload, highlightProductId: currentProductId },
    }));
    return;
  }

  if (action.type === "show_checkout_preview" && typeof window !== "undefined") {
    const rawItems = Array.isArray(action.payload.items) ? action.payload.items : [];
    const cartItemIds = rawItems.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const id = (item as Record<string, unknown>).id;
      return typeof id === "number" && Number.isInteger(id) ? [id] : [];
    });
    const params = new URLSearchParams({ agent_checkout: "1" });
    cartItemIds.forEach((id) => params.append("cart_item_ids", String(id)));
    await navigateWithinApp(`/cart?${params.toString()}`);
    return;
  }

  if (
    action.type === "show_products"
    && (action.target === "product_results" || action.target === "refined_products")
    && readPayloadString(action.payload, ["recommendation_id", "recommendationId"])
  ) {
    const resultUrl = buildProductsResultUrl(action, searchQueryOverride);
    if (resultUrl) {
      if (window.location.pathname === "/search") {
        window.history.replaceState(null, "", resultUrl);
      } else {
        await navigateWithinApp(resultUrl);
      }
    }
    return;
  }

  const comparisonIntent = createComparisonIntent(action, items, message, currentProductId);
  if (comparisonIntent) {
    openComparison(comparisonIntent);
    return;
  }

  if (action.type === "navigate" && action.target === "review_write") {
    storeAgentReviewDraft(action.payload);
  }
  if (action.type === "navigate" && action.target === "claim_request") {
    storeAgentClaimDraft(action.payload);
  }

  const url = resolveNavigateUrl(action);
  if (!url) {
    return;
  }

  if (action.type === "navigate" && action.target === "order_history" && window.location.pathname === "/mypage/orders") {
    window.history.replaceState(null, "", url);
    window.dispatchEvent(new CustomEvent("agent-order-history-filters"));
    return;
  }

  navigateWithinApp(url).catch(() => {
    window.location.href = url;
  });
};

const setAgentCartTargetBusy = (active: boolean) => {
  if (typeof document === "undefined") return;
  document.querySelectorAll<HTMLElement>("[data-agent-cart-target]").forEach((element) => {
    element.classList.toggle("is-agent-running", active);
  });
};

function AgentFloatingButton({
  isAgentResponding = false,
  isAuthenticated = false,
  quickQuestionContext = "home",
  skinProfile,
  skinProfileStatus = "empty",
  storageScope,
  surface = "home",
}: AgentFloatingButtonProps) {
  const { openComparison, comparisonIntent } = useProductComparison();
  const [activeView, setActiveView] = useState<AgentChatView>("home");
  const storageKeys = useMemo(() => getAgentChatStorageKeys(storageScope), [storageScope]);
  const initialStoredMessages = useMemo(() => readStoredMessages(storageScope), [storageScope]);
  const [conversationId, setConversationId] = useState<string | null>(() => readStoredConversationId(storageScope));
  const [isOpen, setIsOpen] = useState(false);
  const [isChatMounted, setIsChatMounted] = useState(false);
  const [isTeaserVisible, setIsTeaserVisible] = useState(surface !== "home");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [draft, setDraft] = useState("");
  const [lastSentMessage, setLastSentMessage] = useState("");
  const [isAwaitingAddressInput, setIsAwaitingAddressInput] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [answerReactions, setAnswerReactions] = useState<Record<string, AgentAnswerReaction | undefined>>({});
  const [messages, setMessages] = useState<AgentChatMessage[]>(initialStoredMessages);
  const [lastToolResultContext, setLastToolResultContext] = useState(() => buildLastToolResult(initialStoredMessages));
  const [hasSearchProducts, setHasSearchProducts] = useState(quickQuestionContext !== "productList");
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [chatThreads, setChatThreads] = useState<AgentChatThreadSummary[]>(() => readStoredThreads(storageScope));
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const chatPopupRef = useRef<HTMLElement | null>(null);
  const chatBodyRef = useRef<HTMLDivElement | null>(null);
  const triggerButtonRef = useRef<HTMLButtonElement | null>(null);
  const teaserRef = useRef<HTMLDivElement | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const teaserTimerRef = useRef<number | null>(null);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const teaserVisibilityFrameRef = useRef<number | null>(null);
  const openChatRef = useRef<() => void>(() => undefined);
  const sendMessageRef = useRef<(
    message: string,
    contextProfile?: AgentFloatingButtonProps["skinProfile"],
    startNewThread?: boolean,
    retryIdempotencyKey?: string,
    retryRequestMessage?: string,
  ) => Promise<AgentChatResponse | null>>(async () => null);
  const hasDismissedTeaserRef = useRef(false);
  const pendingCheckoutCartItemIdsRef = useRef<number[]>([]);
  const previousSurfaceRef = useRef(surface);
  const quickQuestions = useMemo(
    () => quickQuestionContext === "productList" && !hasSearchProducts
      ? emptySearchQuickQuestions
      : !isAuthenticated && guestQuickQuestionsByContext[quickQuestionContext]
        ? guestQuickQuestionsByContext[quickQuestionContext]!
        : quickQuestionsByContext[quickQuestionContext],
    [hasSearchProducts, isAuthenticated, quickQuestionContext],
  );
  const miniChatQuestions = useMemo(
    () => quickQuestions.slice(0, 2).map((prompt, index) => ({
      label: quickQuestionContext === "productList" && !hasSearchProducts
        ? emptySearchMiniChatLabels[index]
        : !isAuthenticated && guestMiniChatLabelsByContext[quickQuestionContext]
          ? guestMiniChatLabelsByContext[quickQuestionContext]![index]
          : miniChatLabelsByContext[quickQuestionContext][index],
      prompt,
    })),
    [hasSearchProducts, isAuthenticated, quickQuestionContext, quickQuestions],
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

  openChatRef.current = openChat;

  const handleTeaserClick = (question: string) => {
    openChat();
    void sendMessage(question);
  };

  const updateTeaserVisibility = useCallback(() => {
    if (isOpen || hasDismissedTeaserRef.current) {
      setIsTeaserVisible(false);
      return;
    }

    setIsTeaserVisible(true);
  }, [isOpen]);

  const scheduleTeaserVisibilityCheck = useCallback(() => {
    if (typeof window === "undefined" || teaserVisibilityFrameRef.current !== null) {
      return;
    }

    teaserVisibilityFrameRef.current = window.requestAnimationFrame(() => {
      teaserVisibilityFrameRef.current = null;
      updateTeaserVisibility();
    });
  }, [updateTeaserVisibility]);

  useEffect(() => {
    if (previousSurfaceRef.current !== surface) {
      previousSurfaceRef.current = surface;
      hasDismissedTeaserRef.current = false;
      setIsTeaserVisible(surface !== "home");
    }

    if (hasDismissedTeaserRef.current) {
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
  }, [isOpen, scheduleTeaserVisibilityCheck, surface]);

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

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!isOpen || isSubmitting || typeof window === "undefined") {
      return undefined;
    }

    const animationFrame = window.requestAnimationFrame(() => chatInputRef.current?.focus());
    return () => window.cancelAnimationFrame(animationFrame);
  }, [isOpen, isSubmitting]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(
      storageKeys.history,
      JSON.stringify(sanitizeMessagesForStorage(messages).slice(-MAX_STORED_AGENT_MESSAGES)),
    );
  }, [messages, storageKeys.history]);

  useEffect(() => {
    if (!currentThreadId || messages.length === 0) {
      return;
    }

    setChatThreads((currentThreads) =>
      upsertAgentChatThread(currentThreads, {
        id: currentThreadId,
        conversationId,
        messages: sanitizeMessagesForStorage(messages).slice(-MAX_STORED_AGENT_MESSAGES),
        title: createThreadTitleFromMessages(messages),
        updatedAt: Date.now(),
      }),
    );
  }, [conversationId, currentThreadId, messages]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(storageKeys.threads, JSON.stringify(chatThreads.slice(0, MAX_AGENT_CHAT_THREADS)));
  }, [chatThreads, storageKeys.threads]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    if (conversationId) {
      window.localStorage.setItem(storageKeys.conversationId, conversationId);
    } else {
      window.localStorage.removeItem(storageKeys.conversationId);
    }
  }, [conversationId, storageKeys.conversationId]);

  useEffect(() => {
    if (!isOpen || !isThreadView || typeof window === "undefined") {
      return undefined;
    }

    const animationFrame = window.requestAnimationFrame(() => {
      const chatBody = chatBodyRef.current;
      if (chatBody) {
        chatBody.scrollTo({ top: chatBody.scrollHeight, behavior: "auto" });
      } else {
        threadEndRef.current?.scrollIntoView({ block: "end", behavior: "auto" });
      }
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [isOpen, isSubmitting, isThreadView, messages]);

  const appendMessages = (nextMessages: AgentChatMessage[]) => {
    setMessages((currentMessages) => [...currentMessages, ...nextMessages].slice(-MAX_STORED_AGENT_MESSAGES));
    setActiveView("thread");
  };

  const openChatThread = (thread: AgentChatThreadSummary) => {
    setCurrentThreadId(thread.id);
    setConversationId(thread.conversationId);
    setMessages(thread.messages);
    setLastToolResultContext(buildLastToolResult(thread.messages));
    setActiveView("thread");
  };

  const resetDeletedCurrentThread = (threadIds: Set<string>) => {
    if (!currentThreadId || !threadIds.has(currentThreadId)) return;
    setCurrentThreadId(null);
    setConversationId(null);
    setMessages([]);
    setLastToolResultContext(null);
    setIsAwaitingAddressInput(false);
    pendingCheckoutCartItemIdsRef.current = [];
    setActiveView("home");
  };

  const deleteChatThread = (threadId: string) => {
    setChatThreads((currentThreads) => currentThreads.filter((thread) => thread.id !== threadId));
    resetDeletedCurrentThread(new Set([threadId]));
  };

  const deleteAllChatThreads = () => {
    const threadIds = new Set(chatThreads.map((thread) => thread.id));
    setChatThreads([]);
    resetDeletedCurrentThread(threadIds);
  };

  const sendMessage = async (
    message: string,
    contextProfile: AgentFloatingButtonProps["skinProfile"] = skinProfile,
    startNewThread = false,
    retryIdempotencyKey?: string,
    retryRequestMessage?: string,
  ): Promise<AgentChatResponse | null> => {
    const nextMessage = message.trim();

    if (!nextMessage || isSubmitting) {
      return null;
    }

    // Keep async search events tied to the route where the request started.
    // A response that arrives after browser navigation must not wake a new page.
    const requestScope = window.location.pathname === "/search" ? "search" : "home";

    const sensitiveInputMessage = getSensitiveAgentInputMessage(nextMessage);
    if (sensitiveInputMessage) {
      const errorMessage = createAgentErrorMessage(
        `sensitive-${Date.now()}`,
        "민감정보는 입력할 수 없어요",
        sensitiveInputMessage,
        { action: "input", actionLabel: "내용 수정" },
      );
      if (activeView === "home") {
        setCurrentThreadId(`thread-${Date.now()}`);
        setConversationId(null);
        setLastToolResultContext(null);
        setMessages([errorMessage]);
        setActiveView("thread");
      } else {
        appendMessages([errorMessage]);
      }
      return null;
    }

    const timestamp = Date.now();
    const canReuseRetryKey = Boolean(
      retryIdempotencyKey
      && retryRequestMessage
      && retryRequestMessage.trim() === nextMessage,
    );
    const idempotencyKey = canReuseRetryKey && retryIdempotencyKey
      ? retryIdempotencyKey
      : createAgentIdempotencyKey();
    const isSensitiveAddressMessage = isAwaitingAddressInput;
    const statusId = `status-${timestamp}`;
    const shouldStartNewThread = startNewThread || activeView === "home";
    const requestConversationId = shouldStartNewThread ? null : conversationId;
    const recentMessages = shouldStartNewThread ? [] : buildRecentMessages(messages);
    const lastToolResult = shouldStartNewThread ? null : lastToolResultContext ?? buildLastToolResult(messages);
    const nextThreadId = shouldStartNewThread || !currentThreadId ? `thread-${timestamp}` : currentThreadId;
    const userMessage: AgentChatTextMessage = {
      id: `user-${timestamp}`,
      content: nextMessage,
      kind: "chat",
      role: "user",
      sensitive: isSensitiveAddressMessage,
    };

    setLastSentMessage(nextMessage);
    if (shouldStartNewThread) {
      setCurrentThreadId(nextThreadId);
      setConversationId(null);
      setLastToolResultContext(null);
      setMessages([userMessage, createStatusMessage(statusId, true, nextMessage)]);
      setActiveView("thread");
    } else {
      if (!currentThreadId) {
        setCurrentThreadId(nextThreadId);
      }
      appendMessages([userMessage, createStatusMessage(statusId, true, nextMessage)]);
    }
    setDraft("");
    setIsSubmitting(true);
    const isCartAddRequest = Boolean(getCommerceStatusSteps(nextMessage, true))
      && /장바구니.*(담|추가)|(담|추가).*장바구니/.test(nextMessage);
    if (isCartAddRequest) setAgentCartTargetBusy(true);

    try {
      const requestContext = buildAgentContext(contextProfile, comparisonIntent?.compareProductIds);
      if (startNewThread && window.location.pathname === "/search") {
        delete requestContext.recommendation_id;
        delete requestContext.search_query;
        delete requestContext.visible_product_ids;
        requestContext.route = "/search";

        const currentFilters = requestContext.filters ?? {};
        const freshSearchFilters = Object.fromEntries(
          ["avoid_ingredients", "page_size", "sensitivity", "skin_type"]
            .flatMap((key) => currentFilters[key] === undefined ? [] : [[key, currentFilters[key]]]),
        );
        requestContext.filters = Object.keys(freshSearchFilters).length > 0
          ? freshSearchFilters
          : undefined;
      }
      if (isAwaitingAddressInput && pendingCheckoutCartItemIdsRef.current.length > 0) {
        requestContext.cart_item_ids = [...pendingCheckoutCartItemIdsRef.current];
      }
      const response = await api.sendAgentMessage(
        {
          context: requestContext,
          conversation_id: requestConversationId,
          last_tool_result: lastToolResult,
          message: nextMessage,
          recent_messages: recentMessages,
        },
        { idempotencyKey },
      );
      const responseTimestamp = Date.now();
      const addressError = response.error?.code === "AGENT_ADDRESS_REQUIRED"
        || response.error?.code === "AGENT_ADDRESS_DETAILS_REQUIRED";
      if (addressError) {
        setIsAwaitingAddressInput(true);
        const cartItemIds = Array.isArray(response.ui_action.payload.cart_item_ids)
          ? response.ui_action.payload.cart_item_ids.filter(
              (value): value is number => typeof value === "number" && Number.isInteger(value) && value > 0,
            )
          : [];
        if (cartItemIds.length > 0) pendingCheckoutCartItemIdsRef.current = cartItemIds;
      } else if (response.tool_name === "register_shipping_address") {
        setIsAwaitingAddressInput(false);
        pendingCheckoutCartItemIdsRef.current = [];
      }
      setConversationId(response.conversation_id);
      const nextToolResultContext = buildToolResultContext(response.ui_action, response.items);
      if (nextToolResultContext) setLastToolResultContext(nextToolResultContext);
      if (response.ui_action.type === "show_products" && response.ui_action.target === "refined_products") {
        const refinementFilters = isRecord(response.ui_action.payload.filters)
          ? response.ui_action.payload.filters
          : {};
        const refinementRecommendationId = readPayloadString(
          response.ui_action.payload,
          ["recommendation_id", "recommendationId"],
        );
        if (refinementRecommendationId && window.location.pathname === "/search") {
          window.dispatchEvent(new CustomEvent("home-search-request", {
            detail: {
              profile: resolveAgentSearchProfile(contextProfile),
              query: nextMessage,
              recommendationId: refinementRecommendationId,
              refinementFilters,
              scope: requestScope,
            },
          }));
        } else {
          window.dispatchEvent(new CustomEvent("agent-refined-products", {
            detail: {
              filters: refinementFilters,
              products: Array.isArray(response.ui_action.payload.products) ? response.ui_action.payload.products : [],
            },
          }));
        }
      }
      if (
        response.ui_action.type === "show_products"
        && response.ui_action.target === "product_results"
        && window.location.pathname === "/search"
      ) {
        const resultUrl = buildProductsResultUrl(response.ui_action, nextMessage);
        const resultParams = resultUrl
          ? new URL(resultUrl, window.location.origin).searchParams
          : null;
        const recommendationId = resultParams?.get("recommendation_id") ?? undefined;

        window.dispatchEvent(new CustomEvent("home-search-request", {
          detail: {
            profile: resolveAgentSearchProfile(contextProfile, resultParams),
            query: nextMessage,
            recommendationId,
            scope: requestScope,
          },
        }));
      }
      const isRecommendationResponse = response.ui_action.type === "show_products"
        || response.ui_action.type === "show_product_comparison"
        || response.items.some((item) => item.item_type === "product");
      const isCompletedCommerceAction = (
        response.ui_action.type === "show_cart"
        && (response.tool_name === "add_to_cart" || response.tool_name === "compose_cart")
      ) || response.ui_action.type === "show_checkout_preview" || response.ui_action.type === "open_payment";
      const shouldCloseHomeRecommendation = window.location.pathname === "/"
        && response.ui_action.type === "show_products"
        && response.items.some((item) => item.item_type === "product");
      setMessages((currentMessages) =>
        [
          ...currentMessages.flatMap((currentMessage) =>
            currentMessage.id === statusId
              ? (isCompletedCommerceAction
                  ? [createStatusMessage(statusId, false, nextMessage)]
                  : isRecommendationResponse
                    ? [createStatusMessage(statusId, false)]
                  : [])
              : [currentMessage],
          ),
          ...createMessagesFromAgentResponse(response, responseTimestamp, nextMessage, idempotencyKey),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
      if (response.ui_action.type === "show_checkout_preview") {
        setIsOpen(false);
        await waitForAgentInteraction(260);
      }
      if (shouldCloseHomeRecommendation) {
        setIsOpen(false);
        await waitForAgentInteraction(260);
      }
      if (response.tool_name === "get_cart") {
        setIsOpen(false);
        await waitForAgentInteraction(260);
        const cartTarget = findVisibleAgentTarget("[data-agent-cart-navigation-target]");
        await playAgentClickInteraction(cartTarget);
        await navigateWithinApp("/cart");
      } else {
        const currentSearchQuery = window.location.pathname === "/search"
          ? new URLSearchParams(window.location.search).get("keyword")?.trim()
          : undefined;
        const searchQueryOverride = response.ui_action.type === "show_products"
          ? response.ui_action.target === "product_results"
            ? nextMessage
            : response.ui_action.target === "refined_products"
              ? currentSearchQuery
              : undefined
          : undefined;
        await applyAgentUiAction(
          response.ui_action,
          response.items,
          response.message,
          buildAgentContext(contextProfile, comparisonIntent?.compareProductIds).current_product_id ?? null,
          openComparison,
          searchQueryOverride,
        );
      }
      return response;
    } catch (error) {
      setMessages((currentMessages) =>
        [
          ...currentMessages.filter((currentMessage) => currentMessage.id !== statusId),
          createAgentErrorFromUnknown(
            error,
            `error-${Date.now()}`,
            isSensitiveAddressMessage ? undefined : nextMessage,
            idempotencyKey,
          ),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
      return null;
    } finally {
      if (isCartAddRequest) setAgentCartTargetBusy(false);
      setIsSubmitting(false);
    }
  };

  sendMessageRef.current = sendMessage;

  useEffect(() => {
    const handleSearchPending = (event: Event) => {
      const detail = (event as CustomEvent<{ scope?: string }>).detail;
      if (detail?.scope !== "search") return;

      // A new search starts a new agent context. Do not carry the rejected
      // request's messages or tool result into the next request.
      setConversationId(null);
      setCurrentThreadId(null);
      setMessages([]);
      setLastToolResultContext(null);
      setLastSentMessage("");
      setIsAwaitingAddressInput(false);
      pendingCheckoutCartItemIdsRef.current = [];
      setAnswerReactions({});
      setHasSearchProducts(false);
    };

    const handleRecommendationState = (event: Event) => {
      const detail = (event as CustomEvent<{
        scope?: string;
        status?: string;
        recommendation?: { products?: unknown[] } | null;
      }>).detail;
      if (detail?.scope !== "search") return;
      setHasSearchProducts(detail.status === "success" && Boolean(detail.recommendation?.products?.length));
    };

    window.addEventListener("home-search-pending", handleSearchPending);
    window.addEventListener("home-recommendation-state", handleRecommendationState);
    return () => {
      window.removeEventListener("home-search-pending", handleSearchPending);
      window.removeEventListener("home-recommendation-state", handleRecommendationState);
    };
  }, []);

  useEffect(() => {
    const handleEntryMessage = (event: Event) => {
      const detail = (event as CustomEvent<AgentEntryMessageDetail>).detail;
      if (!detail?.message.trim()) {
        detail?.reject(new Error("에이전트 메시지가 비어 있습니다."));
        return;
      }

      openChatRef.current();
      void sendMessageRef.current(detail.message, detail.profile, detail.startNewThread)
        .then((response) => {
          detail.resolve(response);
        })
        .catch((error) => {
          detail.reject(error);
        });
    };

    window.addEventListener(AGENT_ENTRY_MESSAGE_EVENT, handleEntryMessage);
    return () => window.removeEventListener(AGENT_ENTRY_MESSAGE_EVENT, handleEntryMessage);
  }, []);

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
    const confirmationStatusContext = approvalMessage.toolName === "bulk_wishlist_by_popular_ingredient"
      ? "인기 상품 성분 조건 일괄 찜"
      : "";
    setIsSubmitting(true);
    appendMessages([createStatusMessage(statusId, true, confirmationStatusContext)]);

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
          ...(isRecommendationResponse
            ? [createStatusMessage(`status-confirmed-${timestamp}`, false, confirmationStatusContext)]
            : []),
          ...createMessagesFromConfirmResponse(response, timestamp),
        ].slice(-MAX_STORED_AGENT_MESSAGES),
      );
      const shouldCloseAfterBulkWishlist = action === "confirm"
        && approvalMessage.toolName === "bulk_wishlist_by_popular_ingredient";
      if (shouldCloseAfterBulkWishlist) {
        clearAllWishlistCache();
        setIsOpen(false);
        await waitForAgentInteraction(260);
      }
      await applyAgentUiAction(
        response.ui_action,
        [],
        "",
        buildAgentContext(skinProfile, comparisonIntent?.compareProductIds).current_product_id ?? null,
        openComparison,
      );
      const orderCode = readString(response.ui_action.payload.order_code);
      const orderStatus = readString(response.ui_action.payload.status);
      if (action === "confirm" && approvalMessage.toolName === "cancel_recent_order" && orderCode && orderStatus === "CANCEL_REQUESTED") {
        void pollCanceledOrder(orderCode);
      }
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

  const pollCanceledOrder = async (orderCode: string) => {
    for (let attempt = 0; attempt < 15; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      try {
        const order = await getOrderDetail(orderCode);
        if (order.status === "CANCEL_REQUESTED") continue;
        if (order.status !== "CANCELED") return;

        const timestamp = Date.now();
        setMessages((currentMessages) => [
          ...currentMessages.map((message) =>
            message.kind === "result"
              ? {
                  ...message,
                  items: message.items.map((item) =>
                    item.itemType === "order" && item.id === orderCode ? { ...item, subtitle: "취소 완료" } : item,
                  ),
                }
              : message,
          ),
          createAssistantMessage(`assistant-canceled-${timestamp}`, "주문 취소가 완료됐어요."),
        ].slice(-MAX_STORED_AGENT_MESSAGES));
        await waitForAgentInteraction(700);
        setIsOpen(false);
        await waitForAgentInteraction(260);
        const orderDetailUrl = `/mypage/orders/${encodeURIComponent(orderCode)}`;
        const orderDetailTarget = findVisibleAgentTarget(`a[href="${orderDetailUrl}"]`);
        await playAgentClickInteraction(orderDetailTarget);
        await navigateWithinApp(orderDetailUrl);
        return;
      } catch {
        // A transient lookup failure is retried within the bounded polling window.
      }
    }
  };

  const handleRetry = (retryMessage?: string, idempotencyKey?: string) => {
    const nextRetryMessage = retryMessage || lastSentMessage;
    if (nextRetryMessage) {
      const canReuseRetryKey = Boolean(
        idempotencyKey
        && retryMessage
        && retryMessage.trim() === nextRetryMessage.trim(),
      );
      void sendMessage(
        nextRetryMessage,
        skinProfile,
        false,
        canReuseRetryKey ? idempotencyKey : undefined,
        nextRetryMessage,
      );
    }
  };

  const getMessagePrompt = (messageId: string) => {
    const messageIndex = messages.findIndex((message) => message.id === messageId);
    if (messageIndex < 0) return lastSentMessage;

    for (let index = messageIndex - 1; index >= 0; index -= 1) {
      const previousMessage = messages[index];
      if (previousMessage.kind === "chat" && previousMessage.role === "user") {
        return previousMessage.content;
      }
    }

    return lastSentMessage;
  };

  const handleRegenerate = (messageId: string) => {
    handleRetry(getMessagePrompt(messageId));
  };

  const handleCopyAnswer = async (messageId: string, content: string) => {
    let copied = false;

    if (typeof window !== "undefined" && window.navigator.clipboard?.writeText) {
      try {
        await window.navigator.clipboard.writeText(content);
        copied = true;
      } catch {
        // Clipboard permission can be unavailable, so the DOM fallback runs below.
      }
    }

    if (!copied && typeof document !== "undefined" && typeof document.execCommand === "function") {
      const textarea = document.createElement("textarea");
      textarea.value = content;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      copied = document.execCommand("copy");
      textarea.remove();
    }

    if (copied) {
      setCopiedMessageId(messageId);
      if (copyFeedbackTimerRef.current !== null) {
        window.clearTimeout(copyFeedbackTimerRef.current);
      }
      copyFeedbackTimerRef.current = window.setTimeout(() => {
        setCopiedMessageId(null);
        copyFeedbackTimerRef.current = null;
      }, 1600);
    }
  };

  const renderStatusMessage = (message: AgentChatStatusMessage) => (
    message.steps.some((step) => step.status === "active")
    && !/(장바구니|배송지|주문서)/.test(message.title) ? (
      <div className="agent-chat-typing" key={message.id} aria-label="답변을 준비하고 있어요">
        <img alt="" src="/mwobareullae-rabbit-chat-transparent.png" />
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
        {message.resolved ? (
          <span className="agent-chat-approval-state">
            {message.resolved === "approved"
              ? message.toolName === "cancel_recent_order"
                ? "취소 처리 중"
                : message.toolName === "compose_cart" || message.toolName === "bulk_wishlist_by_popular_ingredient" ? "반영됨" : "승인됨"
              : message.toolName === "compose_cart" || message.toolName === "bulk_wishlist_by_popular_ingredient" ? "반영 안 함" : "취소 안 함"}
          </span>
        ) : null}
      </div>
    );
  };

  const handleErrorAction = (message: AgentChatErrorMessage) => {
    if (message.action === "input") {
      chatInputRef.current?.focus();
      return;
    }
    if (message.action === "login") {
      const redirect = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.href = `/login?redirect=${encodeURIComponent(redirect)}`;
      return;
    }

    if (message.action === "profile") {
      void navigateWithinApp("/signup/skin-profile");
      return;
    }

    handleRetry(message.retryMessage, message.idempotencyKey);
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

  const openResultAction = async (actionUrl?: string | null) => {
    if (!actionUrl) {
      return;
    }

    closeChat();
    await waitForAgentInteraction(260);

    try {
      const targetUrl = new URL(actionUrl, window.location.origin);
      if (targetUrl.pathname === "/search" && window.location.pathname === "/search") {
        const query = targetUrl.searchParams.get("keyword")?.trim();
        const recommendationId = targetUrl.searchParams.get("recommendation_id") ?? undefined;
        if (query) {
          window.history.replaceState(null, "", `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`);
          window.dispatchEvent(new CustomEvent("home-search-request", {
            detail: {
              profile: resolveAgentSearchProfile(skinProfile, targetUrl.searchParams),
              query,
              recommendationId,
              scope: window.location.pathname === "/search" ? "search" : "home",
            },
          }));
        }
        document.getElementById("searchResultsSection")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
        return;
      }

      await navigateWithinApp(actionUrl);
    } catch {
      window.location.href = actionUrl;
    }
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
                  {item.imageUrl ? <img alt="" src={item.imageUrl} /> : null}
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
            onClick={() => void openResultAction(
              message.actionTarget === "popular_wishlist" ? "/mypage/wishlist" : message.actionUrl,
            )}
            type="button"
          >
            {message.actionTarget === "popular_wishlist" ? "찜 목록 보기" : "전체 보기"}
          </button>
        ) : null}
        {message.actionType === "show_cart" && message.actionUrl ? (
          <button
            className="agent-chat-result-more"
            onClick={() => void openResultAction(message.actionUrl)}
            type="button"
          >
            장바구니 보기
          </button>
        ) : null}
      </div>
    );
  };

  const renderTextMessage = (message: AgentChatTextMessage) => (
    <div className={`agent-chat-message-group ${message.role}`} key={message.id}>
      <div className={`agent-chat-message-line ${message.role}`}>
        {message.role === "assistant" ? <img alt="" src="/mwobareullae-rabbit-chat-transparent.png" /> : null}
        <div className={`agent-chat-message ${message.role}`}>
          {message.role === "assistant" ? renderAgentMessageContent(message.content) : message.content}
        </div>
      </div>
      {message.role === "assistant" && message.showActions ? (
        <>
          <div className="agent-chat-actions" aria-label="답변 액션">
            <button
              aria-label="좋아요"
              aria-pressed={answerReactions[message.id] === "like"}
              className={`agent-chat-actions__button--like${answerReactions[message.id] === "like" ? " is-liked" : ""}`}
              onClick={() => setAnswerReactions((current) => ({
                ...current,
                [message.id]: current[message.id] === "like" ? undefined : "like",
              }))}
              type="button"
            >
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M10 14v13H6V14h4Zm0 13h11.1a3 3 0 0 0 2.92-2.3l1.35-5.76A3 3 0 0 0 22.45 15H18l.66-4.62A3 3 0 0 0 15.7 7L10 14v13Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button
              aria-label="별로예요"
              aria-pressed={answerReactions[message.id] === "dislike"}
              className={`agent-chat-actions__button--dislike${answerReactions[message.id] === "dislike" ? " is-disliked" : ""}`}
              onClick={() => setAnswerReactions((current) => ({
                ...current,
                [message.id]: current[message.id] === "dislike" ? undefined : "dislike",
              }))}
              type="button"
            >
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M10 18V5H6v13h4Zm0-13h11.1a3 3 0 0 1 2.92 2.3l1.35 5.76A3 3 0 0 1 22.45 14H18l.66 4.62A3 3 0 0 1 15.7 22L10 15v-10Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button aria-label="다시 생성" disabled={isSubmitting} onClick={() => handleRegenerate(message.id)} type="button">
              <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="M25 12a10 10 0 1 0 1 8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" /><path d="M25 6v6h-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" /></svg>
            </button>
            <button
              aria-label={copiedMessageId === message.id ? "복사됨" : "복사"}
              onClick={() => void handleCopyAnswer(message.id, message.content)}
              title={copiedMessageId === message.id ? "복사됨" : "답변 복사"}
              type="button"
            >
              {copiedMessageId === message.id ? (
                <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><path d="m7 16 6 6L25 10" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" /></svg>
              ) : (
                <svg aria-hidden="true" fill="none" viewBox="0 0 32 32"><rect height="15" rx="2" stroke="currentColor" strokeWidth="1.8" width="15" x="11" y="11" /><path d="M21 11V8a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h3" stroke="currentColor" strokeWidth="1.8" /></svg>
              )}
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
          {miniChatQuestions.map((question) => (
            <button key={question.prompt} onClick={() => handleTeaserClick(question.prompt)} type="button">
              {question.label}
            </button>
          ))}
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
                <p>당신만의 쇼핑 에이전트</p>
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

            <div className="agent-chat-popup__body" ref={chatBodyRef}>
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
                      <div className="agent-chat-section-label">
                        <span>최근 대화</span>
                        <button onClick={deleteAllChatThreads} type="button">전체 삭제</button>
                      </div>
                      {chatThreads.map((thread) => (
                        <div className="agent-chat-history-row" key={thread.id}>
                          <button
                            aria-label={`${thread.title} 대화 열기`}
                            className="agent-chat-question-row"
                            disabled={isSubmitting}
                            onClick={() => openChatThread(thread)}
                            type="button"
                          >
                            <span className="agent-chat-row-icon" aria-hidden="true">
                              <svg fill="none" viewBox="0 0 24 24">
                                <path d="M5 6.5a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H9.25L5 17.5v-11Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.8" />
                                <path d="M8.5 8.5h7M8.5 11.5h4.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
                              </svg>
                            </span>
                            <span>{thread.title}</span>
                            <span aria-hidden="true">›</span>
                          </button>
                          <button aria-label={`${thread.title} 대화 삭제`} className="agent-chat-history-delete" onClick={() => deleteChatThread(thread.id)} type="button">
                            <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
                              <path d="M5 7h14M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </>
                  ) : null}

                </>
              )}
            </div>

            <form className="agent-chat-input" onSubmit={handleSubmit}>
              <input
                aria-label="AI에게 질문 입력"
                aria-busy={isSubmitting}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="무엇이든 물어보세요"
                readOnly={isSubmitting}
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
