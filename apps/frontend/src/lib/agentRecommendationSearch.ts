import { AGENT_ENTRY_MESSAGE_EVENT, type AgentEntryMessageDetail } from "./agentUiEvents";
import { callOriginal } from "./originalRuntime";
import type { AgentChatResponse } from "../types/agent";
import type { RecommendationProfile } from "../types/recommendation";

export const buildRecommendationSearchUrl = (
  message: string,
  profile: RecommendationProfile,
) => {
  const params = new URLSearchParams({
    keyword: message.trim(),
    page_size: "10",
    search_mode: "ai",
    sensitivity: profile.sensitivity,
    skin_type: profile.skin,
  });
  return `/search?${params.toString()}`;
};

export const buildAgentPendingSearchUrl = (
  message: string,
  profile: RecommendationProfile,
) => {
  const url = new URL(buildRecommendationSearchUrl(message, profile), window.location.origin);
  url.searchParams.set("agent_pending", "1");
  return `${url.pathname}${url.search}`;
};

export const buildAgentPendingEntryUrl = (
  message: string,
  profile: RecommendationProfile,
) => {
  const normalized = message.trim();
  if (/주문\s*(내역|목록)|(내역|목록)\s*.*주문/.test(normalized)) {
    const periodMonths = /1\s*개월/.test(normalized)
      ? 1
      : /3\s*개월/.test(normalized)
        ? 3
        : /6\s*개월/.test(normalized)
          ? 6
          : 12;
    return `/mypage/orders?period_months=${periodMonths}`;
  }
  return buildAgentPendingSearchUrl(normalized, profile);
};

export const runAgentEntryMessage = (
  message: string,
  profile: RecommendationProfile,
) => new Promise<AgentChatResponse | null>((resolve, reject) => {
  callOriginal("saveRecentConcern", message);
  const detail: AgentEntryMessageDetail = {
    message,
    startNewThread: true,
    profile: {
      avoidIngredients: profile.avoidIngredients,
      sensitivity: profile.sensitivity,
      skin: profile.skin,
    },
    reject,
    resolve,
  };

  window.dispatchEvent(new CustomEvent<AgentEntryMessageDetail>(AGENT_ENTRY_MESSAGE_EVENT, { detail }));
});
