import type { AgentChatResponse } from "../types/agent";

export const AGENT_SHOW_CART_EVENT = "mwobareullae:agent-show-cart";
export const AGENT_ENTRY_MESSAGE_EVENT = "mwobareullae:agent-entry-message";

export type AgentEntryMessageDetail = {
  message: string;
  profile?: {
    avoidIngredients?: string[];
    sensitivity: string;
    skin: string;
  };
  reject: (reason?: unknown) => void;
  resolve: (response: AgentChatResponse | null) => void;
};
