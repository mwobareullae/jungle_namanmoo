import type { ProductDetail, RecommendationNarrativeDetailSection } from "../../types/recommendation";

export type ProductDetailStatusProps = {
  errorMessage: string;
  isLoading: boolean;
};

export type ProductDetailToastProps = {
  message: string;
};

export type ProductDetailActionButtonsProps = {
  displayedIsWished: boolean;
  isWishlistPending: boolean;
  onToggleWishlist: () => void;
};

export type ProductPurchasePanelProps = {
  cartErrorMessage: string;
  cartMessage: string;
  isAddingToCart: boolean;
  onAddToCart: () => void;
  onBuyNow: () => void;
};

export type ProductDetailHeroProps = {
  brandPagePath: string;
  cartErrorMessage: string;
  cartMessage: string;
  displayedIsWished: boolean;
  isAddingToCart: boolean;
  isNarrativeLoading: boolean;
  isWishlistPending: boolean;
  mainImageUrl: string;
  narrativeCaution?: string | null;
  narrativeChips: string[];
  narrativeDetailSections: RecommendationNarrativeDetailSection[];
  narrativeHeadline: string;
  narrativeKeyPoints: string[];
  narrativeReason: string;
  narrativeRole?: string;
  narrativeSelectionGuide?: string | null;
  narrativeSummaryText?: string | null;
  onAddToCart: () => void;
  onBuyNow: () => void;
  onToggleWishlist: () => void;
  priceLabel: string;
  product: ProductDetail;
  sensitivity: string;
  skinType: string;
};
