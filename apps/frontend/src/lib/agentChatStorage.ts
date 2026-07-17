import { getAnonymousUserId } from "./appSignals/ids";

const AGENT_CHAT_HISTORY_KEY = "mwobareullae-agent-chat-history-v2";
const AGENT_CONVERSATION_ID_KEY = "mwobareullae-agent-conversation-id";
const AGENT_CHAT_THREADS_KEY = "mwobareullae-agent-chat-threads-v1";

export type AgentChatStorageScope = `user:${number}` | `guest:${string}`;

export const getUserAgentChatStorageScope = (userId: number): AgentChatStorageScope =>
  `user:${userId}`;

export const getGuestAgentChatStorageScope = (): AgentChatStorageScope =>
  `guest:${getAnonymousUserId()}`;

export const getAgentChatStorageKeys = (scope: AgentChatStorageScope) => ({
  conversationId: `${AGENT_CONVERSATION_ID_KEY}:${scope}`,
  history: `${AGENT_CHAT_HISTORY_KEY}:${scope}`,
  threads: `${AGENT_CHAT_THREADS_KEY}:${scope}`,
});

export const clearAgentChatStorageScope = (scope: AgentChatStorageScope) => {
  if (typeof window === "undefined") return;
  const keys = getAgentChatStorageKeys(scope);
  window.localStorage.removeItem(keys.history);
  window.localStorage.removeItem(keys.conversationId);
  window.localStorage.removeItem(keys.threads);
};

export const clearLegacyAgentChatStorage = () => {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AGENT_CHAT_HISTORY_KEY);
  window.localStorage.removeItem(AGENT_CONVERSATION_ID_KEY);
  window.localStorage.removeItem(AGENT_CHAT_THREADS_KEY);
};
