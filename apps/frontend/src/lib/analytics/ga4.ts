import type { EventMetadata, OfficialEventName } from "./types";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

const gaMeasurementId = import.meta.env.VITE_GA_MEASUREMENT_ID?.trim() ?? "";

const allowedGaKeys = new Set([
  "recommendation_id",
  "product_id",
  "rank",
  "source",
  "page",
  "section",
  "section_id",
  "is_logged_in",
  "has_profile",
  "skin_type",
  "sensitivity",
  "has_concern_text",
  "concern_length",
  "result_count",
  "total_items",
  "score_bucket"
]);

const toGaValue = (value: unknown): string | number | boolean | undefined => {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return undefined;
};

export const trackGa4Event = (eventName: OfficialEventName, params: EventMetadata) => {
  if (!gaMeasurementId || typeof window === "undefined") {
    return;
  }

  const gaParams = Object.fromEntries(
    Object.entries(params)
      .filter(([key]) => allowedGaKeys.has(key))
      .map(([key, value]) => [key, toGaValue(value)])
      .filter((entry): entry is [string, string | number | boolean] => entry[1] !== undefined)
  );

  if (window.gtag) {
    window.gtag("event", eventName, gaParams);
    return;
  }

  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({
    event: eventName,
    ...gaParams
  });
};
