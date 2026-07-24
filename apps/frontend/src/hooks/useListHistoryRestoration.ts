import { useCallback, useMemo } from "react";
import { useLocation } from "react-router-dom";

const LIST_RESTORATION_STATE_KEY = "mwobareullae.listRestoration";

type ListRestorationSnapshot = {
  locationKey: string;
  loadedPageCount: number;
  productId: string;
  scrollY: number;
};

type HistoryStateWithRestoration = Record<string, unknown> & {
  [LIST_RESTORATION_STATE_KEY]?: ListRestorationSnapshot;
};

const getLocationKey = () => `${window.location.pathname}${window.location.search}`;

const isListRestorationSnapshot = (value: unknown): value is ListRestorationSnapshot => {
  if (!value || typeof value !== "object") return false;

  const snapshot = value as Partial<ListRestorationSnapshot>;
  return (
    typeof snapshot.locationKey === "string"
    && typeof snapshot.loadedPageCount === "number"
    && typeof snapshot.productId === "string"
    && typeof snapshot.scrollY === "number"
  );
};

const getCurrentHistoryState = (): HistoryStateWithRestoration => {
  const state = window.history.state;
  return state && typeof state === "object" ? state as HistoryStateWithRestoration : {};
};

export const getListHistoryRestoration = (locationKey = getLocationKey()) => {
  const snapshot = getCurrentHistoryState()[LIST_RESTORATION_STATE_KEY];
  if (!isListRestorationSnapshot(snapshot) || snapshot.locationKey !== locationKey) return null;
  return snapshot;
};

export function useListHistoryRestoration() {
  const location = useLocation();
  const restoration = useMemo(
    () => getListHistoryRestoration(`${location.pathname}${location.search}`),
    [location.pathname, location.search]
  );

  const saveListRestoration = useCallback((productId: string, loadedPageCount: number) => {
    const locationKey = getLocationKey();
    const nextState: HistoryStateWithRestoration = {
      ...getCurrentHistoryState(),
      [LIST_RESTORATION_STATE_KEY]: {
        locationKey,
        loadedPageCount: Math.max(1, loadedPageCount),
        productId,
        scrollY: window.scrollY,
      },
    };

    window.history.replaceState(nextState, "", `${locationKey}${window.location.hash}`);
  }, []);

  const restoreListPosition = useCallback((target: HTMLElement | null) => {
    if (!restoration) return Promise.resolve();

    return new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (target?.isConnected) {
            target.scrollIntoView({ block: "center", behavior: "auto" });
          } else {
            window.scrollTo({ top: restoration.scrollY, left: 0, behavior: "auto" });
          }
          resolve();
        });
      });
    });
  }, [restoration]);

  return {
    restoration,
    restoreListPosition,
    saveListRestoration,
  };
}
