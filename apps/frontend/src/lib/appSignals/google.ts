import type { EventMetadata, OfficialEventName } from "./contracts";

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

export const trackGa4Event = (eventName: OfficialEventName, params: EventMetadata = {}) => {
  if (typeof window === "undefined" || typeof window.gtag !== "function") {
    return;
  }

  window.gtag("event", eventName, params);
};
