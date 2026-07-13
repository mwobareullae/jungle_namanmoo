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
  isProductSoldOut: boolean;
  onAddToCart: () => void;
  onBuyNow: () => void;
  onRestockNotify: () => void;
};

export type ProductDetailHeroProps = {
  aiNarrativeCautionText: string;
  aiNarrativeDetailItems: RecommendationNarrativeDetailSection[];
  aiNarrativeProfileChips: string[];
  aiNarrativeReason: string;
  aiNarrativeTitle: string;
  brandPagePath: string;
  cartErrorMessage: string;
  cartMessage: string;
  displayedIsWished: boolean;
  isAddingToCart: boolean;
  isNarrativeDetailOpen: boolean;
  isNarrativeLoading: boolean;
  showAiNarrative: boolean;
  showRecommendationCriteria: boolean;
  isProductSoldOut: boolean;
  isWishlistPending: boolean;
  mainImageUrl: string;
  onAddToCart: () => void;
  onBuyNow: () => void;
  onRestockNotify: () => void;
  onToggleNarrativeDetail: () => void;
  onToggleWishlist: () => void;
  priceLabel: string;
  product: ProductDetail;
};
