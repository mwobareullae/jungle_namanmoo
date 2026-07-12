import { trackEventBatch } from "./client";
import type { OfficialEventName } from "./contracts";

const sentImpressions = new Set<string>();

const isImpressionEvent = (value: string | undefined): value is OfficialEventName =>
  value === "home_product_impression" || value === "search_result_impression";

export const observeProductImpressions = (root: ParentNode = document) => {
  if (typeof IntersectionObserver === "undefined") return () => undefined;

  const timers = new Map<Element, number>();
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const element = entry.target as HTMLElement;
        const clearTimer = () => {
          const timer = timers.get(element);
          if (timer !== undefined) window.clearTimeout(timer);
          timers.delete(element);
        };

        if (!entry.isIntersecting || entry.intersectionRatio < 0.5) {
          clearTimer();
          return;
        }
        if (timers.has(element)) return;

        const eventName = element.dataset.impressionEvent;
        const productId = element.dataset.productId;
        const sectionId = element.dataset.sectionId;
        const rank = Number(element.dataset.rank);
        const page = element.dataset.eventPage;
        const source = element.dataset.eventSource;
        if (!isImpressionEvent(eventName) || !productId || !sectionId || !rank || !page || !source) return;

        const dedupeKey = [eventName, page, sectionId, productId, rank].join(":");
        if (sentImpressions.has(dedupeKey)) return;

        timers.set(
          element,
          window.setTimeout(() => {
            timers.delete(element);
            sentImpressions.add(dedupeKey);
            trackEventBatch([
              {
                eventName,
                payload: {
                  productId,
                  rank,
                  page,
                  source,
                  recommendationId: element.dataset.recommendationId || undefined,
                  metadata: { section_id: sectionId }
                }
              }
            ]);
          }, 500)
        );
      });
    },
    { threshold: [0.5] }
  );

  root.querySelectorAll<HTMLElement>("[data-impression-event]").forEach((element) => observer.observe(element));

  return () => {
    observer.disconnect();
    timers.forEach((timer) => window.clearTimeout(timer));
    timers.clear();
  };
};
