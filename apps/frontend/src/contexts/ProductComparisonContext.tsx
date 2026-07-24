import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type ProductComparisonDifference = {
  base?: string | null;
  compare?: string | null;
  description?: string | null;
  label: string;
};

export type ProductComparisonCandidatePreview = {
  brand: string;
  evidenceTags: string[];
  keyIngredients: string[];
  lowestPrice: number | null;
  matchReasons: string[];
  name: string;
  productId: string;
  riskFlags: string[];
  thumbnailStorageKey: string | null;
};

export type ProductComparisonIntent = {
  candidatePreviews: ProductComparisonCandidatePreview[];
  compareProductIds: string[];
  createdAt: number;
  differences: ProductComparisonDifference[];
  recommendationReason: string;
  source: "comparison" | "similar";
  sourceProductId: string;
  summary: string;
};

type ProductComparisonContextValue = {
  clearComparison: () => void;
  comparisonIntent: ProductComparisonIntent | null;
  openComparison: (intent: ProductComparisonIntent) => void;
};

const ProductComparisonContext = createContext<ProductComparisonContextValue | null>(null);

export function ProductComparisonProvider({ children }: { children: ReactNode }) {
  const [comparisonIntent, setComparisonIntent] = useState<ProductComparisonIntent | null>(null);

  const openComparison = useCallback((intent: ProductComparisonIntent) => {
    setComparisonIntent(intent);
  }, []);

  const clearComparison = useCallback(() => {
    setComparisonIntent(null);
  }, []);

  const value = useMemo(
    () => ({ clearComparison, comparisonIntent, openComparison }),
    [clearComparison, comparisonIntent, openComparison],
  );

  return <ProductComparisonContext.Provider value={value}>{children}</ProductComparisonContext.Provider>;
}

// This module intentionally exports the provider hook with its provider.
// eslint-disable-next-line react-refresh/only-export-components
export function useProductComparison() {
  const context = useContext(ProductComparisonContext);

  if (!context) {
    throw new Error("useProductComparison must be used within ProductComparisonProvider");
  }

  return context;
}
