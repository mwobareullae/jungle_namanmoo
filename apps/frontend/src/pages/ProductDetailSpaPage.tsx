import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductComparisonPanel, { type ProductComparisonDifference } from "../components/ProductComparisonPanel";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import { addMyRecentProduct, addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { addCartItem } from "../lib/cartApi";
import { avoidIngredientCategories } from "../constants/avoidIngredientCategories";
import { getFallbackProductDetail } from "../lib/fallbackProducts";
import { installHomeRuntime } from "../lib/homeRuntime";
import { navigateWithinApp } from "../lib/navigation";
import { getSavedSkinProfile } from "../lib/profileApi";
import { useProductReviews } from "../hooks/useProductReviews";
import type {
  IngredientEvidence,
  ProductDetail,
  RecommendationNarrativeOverview,
  RecommendationNarrativeProduct,
} from "../types/recommendation";

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const evidenceLevelLabel: Record<IngredientEvidence["evidence_level"], string> = {
  high: "근거 높음",
  medium: "근거 보통",
  low: "근거 낮음",
};

const evidenceLevelBadgeClass: Record<IngredientEvidence["evidence_level"], string> = {
  high: "evidence-badge-high",
  medium: "evidence-badge-medium",
  low: "evidence-badge-low",
};

type ReviewTypeFilter = "all" | "photo" | "month" | "repurchase";
type ReviewSortOption = "recommended" | "latest" | "ratingHigh" | "ratingLow";

const reviewPageSize = 10;
const reviewTypeOptions: { value: ReviewTypeFilter; label: string }[] = [
  { value: "all", label: "전체 리뷰" },
  { value: "photo", label: "포토 리뷰" },
  { value: "month", label: "한달 사용 리뷰" },
  { value: "repurchase", label: "재구매" },
];
const reviewSortOptions: { value: ReviewSortOption; label: string }[] = [
  { value: "recommended", label: "추천순" },
  { value: "latest", label: "최신순" },
  { value: "ratingHigh", label: "평점 높은순" },
  { value: "ratingLow", label: "평점 낮은순" },
];
const reviewSkinTypeOptions = ["건성", "지성", "복합성", "수부지", "중성", "민감성"];

const formatReviewDate = (date: string) => date.replace(/-/g, ".");
const AVATAR_COLOR_CLASSES = ["c1", "c2", "c3"];
const getAvatarColorClass = (seed: string) => {
  const code = seed.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return AVATAR_COLOR_CLASSES[code % AVATAR_COLOR_CLASSES.length];
};
const REVIEW_STAR_PATH =
  "M10.868 2.884c-.321-.772-1.415-.772-1.736 0l-1.83 4.401-4.753.381c-.833.067-1.171 1.107-.536 1.651l3.62 3.102-1.106 4.637c-.194.813.691 1.45 1.405 1.02L10 15.591l4.069 2.446c.713.428 1.598-.208 1.404-1.02l-1.106-4.637 3.62-3.102c.635-.544.297-1.584-.536-1.65l-4.752-.382-1.831-4.401Z";
const ReviewStarIcon = ({ filled, size = 15 }: { filled: boolean; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
    <path fill={filled ? "var(--color-danger)" : "#E2E5E9"} d={REVIEW_STAR_PATH} />
  </svg>
);
const ReviewStarRow = ({ rating, size = 15 }: { rating: number; size?: number }) => (
  <>
    {Array.from({ length: 5 }, (_, index) => (
      <ReviewStarIcon key={index} filled={index < rating} size={size} />
    ))}
  </>
);

// 백엔드 성분 데이터에 PMID·tier·canonical 같은 내부 리서치 원본 텍스트가 섞여 들어오는 경우가 있어,
// 소비자 화면에 노출되지 않도록 방어적으로 걸러낸다.
const INTERNAL_NOTE_PATTERN = /pmid|canonical|\b(role|tier|status)\s*=|\bcfr\b/i;
const INTERNAL_EVIDENCE_COPY_PATTERN =
  /marker_upper_bound|upper-bound|heuristic|coverage|confidence|regulatory_anchor|legal_upper_bound|prior_estimate|range_confidence|concentration_confidence|exact\s*아님|internal/i;
const isInternalNoteText = (value: string | null | undefined) => {
  if (!value) return false;
  const normalized = value.trim();
  if (!normalized) return false;
  if (/^(high|medium|low)$/i.test(normalized)) return true;
  return INTERNAL_NOTE_PATTERN.test(normalized);
};

const evidenceLevelDisplayText: Record<IngredientEvidence["evidence_level"], string> = {
  high: "관련 효능 근거가 비교적 명확하게 확인된 성분입니다.",
  medium: "관련 효능 근거가 확인되며, 제품 내 함량과 사용 조건에 따라 체감은 달라질 수 있습니다.",
  low: "관련 효능과 연결된 참고 근거가 있어 보조 정보로 확인할 수 있습니다.",
};

const isConsumerFacingEvidenceText = (value: string | null | undefined) => {
  if (!value) return false;
  const normalized = value.trim();
  if (!normalized) return false;
  if (isInternalNoteText(normalized)) return false;
  return !INTERNAL_EVIDENCE_COPY_PATTERN.test(normalized);
};

const getIngredientEvidenceDisplayText = (
  evidence: IngredientEvidence,
  effectLabel: string,
) => {
  if (isConsumerFacingEvidenceText(evidence.evidence_text)) {
    return evidence.evidence_text.trim();
  }

  const ingredientName = evidence.ingredient_name?.trim() || "이 성분";
  const normalizedEffectLabel = effectLabel.trim() || "해당 효능";
  return `${ingredientName}은 ${normalizedEffectLabel}과 관련된 성분 근거가 확인되었습니다. ${evidenceLevelDisplayText[evidence.evidence_level]}`;
};

const getAvoidIngredientMatchSet = (avoidValues: string[]) => {
  const matchSet = new Set<string>();
  avoidValues.forEach((value) => {
    const category = avoidIngredientCategories.find(
      (item) =>
        item.id === value ||
        item.label === value ||
        (item.mappedIngredients as readonly string[]).includes(value),
    );

    if (category) {
      category.mappedIngredients.forEach((name) => matchSet.add(name));
      return;
    }

    matchSet.add(value);
  });
  return matchSet;
};
const EMPTY_AVOID_INGREDIENT_MATCH_SET = new Set<string>();

const getDetailParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    productId: params.get("id") ?? "",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
  };
};

type EffectIconKey = "brighten" | "wrinkle" | "acne" | "moisture" | "soothe";

const getEffectIcon = (effect: string): EffectIconKey => {
  if (effect.includes("미백") || effect.includes("톤")) return "brighten";
  if (effect.includes("주름") || effect.includes("탄력")) return "wrinkle";
  if (effect.includes("여드름") || effect.includes("피지") || effect.includes("모공")) return "acne";
  if (effect.includes("보습") || effect.includes("장벽")) return "moisture";
  return "soothe";
};

const EFFECT_ICON_SVG: Record<EffectIconKey, JSX.Element> = {
  moisture: (
    <path d="M12 2.5c4 5 7 8.5 7 12a7 7 0 1 1-14 0c0-3.5 3-7 7-12z" />
  ),
  soothe: (
    <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" />
  ),
  brighten: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
    </>
  ),
  wrinkle: (
    <>
      <path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3" />
      <path d="M18 3v4h-4M6 21v-4h4" />
    </>
  ),
  acne: <path d="M12 3l7 3.5v5c0 5-3 8.5-7 9.5-4-1-7-4.5-7-9.5v-5L12 3z" />,
};

const EffectIcon = ({ iconKey }: { iconKey: EffectIconKey }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {EFFECT_ICON_SVG[iconKey]}
  </svg>
);

const getEffectLabel = (effect: string) => {
  if (effect.includes("미백") || effect.includes("톤")) return "피부 미백에 도움되는 기능성 성분";
  if (effect.includes("주름") || effect.includes("탄력")) return "주름 개선에 도움되는 기능성 성분";
  if (effect.includes("여드름") || effect.includes("피지")) return "여드름·피지 케어에 연결된 성분";
  if (effect.includes("모공")) return "모공 케어에 연결된 성분";
  if (effect.includes("보습")) return "보습에 도움되는 성분";
  return `${effect} 효능과 연결된 성분`;
};

const getEffectTagLabel = (effect: string) => effect.trim() || "효능";

const normalizeNarrativeTitle = (title: string) => {
  if (/내 피부 고민 기준 추천 근거|추천\s*근거|왜\s*추천/.test(title)) return "왜 추천했나요";
  if (/핵심\s*성분/.test(title)) return "핵심 성분";
  if (/피부\s*타입/.test(title)) return "피부 타입";
  return title;
};

const getSourceUrlForEvidence = (product: ProductDetail, sourceTitle: string | null) => {
  if (!sourceTitle) return "";
  return product.sources.find((source) => source.title === sourceTitle)?.url ?? "";
};

const parseRiskFlag = (riskFlag: string) => {
  const [name, ...noteParts] = riskFlag.split(":");
  return {
    name: name.trim() || "주의 성분",
    note: noteParts.join(":").trim(),
  };
};

const DETAIL_TAB_HASHES = ["#description", "#ingredients", "#reviews", "#qna"] as const;
type DetailTabHash = typeof DETAIL_TAB_HASHES[number];
const DETAIL_TAB_SCROLL_OFFSET_PX = 66;
const REVIEW_PAGE_SCROLL_OFFSET_PX = 168;
const CORE_INGREDIENT_COUNT = 4;
const INITIAL_VISIBLE_INGREDIENT_COUNT = 12;
const normalizeDetailHash = (hash: string) =>
  DETAIL_TAB_HASHES.includes(hash as typeof DETAIL_TAB_HASHES[number])
    ? hash
    : "#description";
const scrollToDetailTabs = (behavior: ScrollBehavior = "smooth") => {
  window.requestAnimationFrame(() => {
    const tabs = document.querySelector<HTMLElement>(".detail-tabs");
    if (!tabs) return;

    window.scrollTo({
      top: Math.max(0, tabs.getBoundingClientRect().top + window.scrollY - DETAIL_TAB_SCROLL_OFFSET_PX),
      behavior,
    });
  });
};
const AGENT_PRODUCT_COMPARISON_EVENT = "mwobareullae:show-product-comparison";

type ProductComparisonRequest = {
  compareProductIds: string[];
  differences: ProductComparisonDifference[];
  recommendationReason: string;
  source: "comparison" | "similar";
  summary: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const toDisplayString = (value: unknown) => {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number") return String(value);
  return null;
};

const readString = (record: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = toDisplayString(record[key]);
    if (value) return value;
  }
  return null;
};

const readRecord = (record: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = record[key];
    if (isRecord(value)) return value;
  }
  return null;
};

const getComparisonPayload = (detail: unknown) => {
  if (!isRecord(detail)) return {};
  if (isRecord(detail.payload)) return detail.payload;

  const action = isRecord(detail.action) ? detail.action : null;
  return action && isRecord(action.payload) ? action.payload : {};
};

const getComparisonAction = (detail: unknown) =>
  isRecord(detail) && isRecord(detail.action) ? detail.action : {};

const getComparisonItems = (detail: unknown) =>
  isRecord(detail) && Array.isArray(detail.items) ? detail.items : [];

const getAgentMessage = (detail: unknown) =>
  isRecord(detail) ? readString(detail, ["agentMessage", "message", "summary"]) : null;

const readProductId = (value: unknown) => {
  const rawValue = toDisplayString(value);
  if (rawValue) return rawValue;
  if (!isRecord(value)) return null;

  return readString(value, [
    "compare_product_id",
    "compared_product_id",
    "comparison_product_id",
    "target_product_id",
    "recommended_product_id",
    "product_id",
    "id",
  ]);
};

const collectProductIds = (value: unknown) => {
  if (!Array.isArray(value)) return [];
  return value.map(readProductId).filter((id): id is string => Boolean(id));
};

const uniqueProductIds = (values: Array<string | null | undefined>) => {
  const result: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    const normalized = value?.trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    result.push(normalized);
  });
  return result;
};

const normalizeComparisonDifference = (
  value: unknown,
  index: number,
): ProductComparisonDifference | null => {
  const description = toDisplayString(value);
  if (description) {
    return {
      description,
      label: `비교 포인트 ${index + 1}`,
    };
  }

  if (!isRecord(value)) return null;

  return {
    base: readString(value, ["base", "base_value", "current", "current_value", "left", "source"]),
    compare: readString(value, ["compare", "compare_value", "compared", "compared_value", "right", "target"]),
    description: readString(value, ["description", "summary", "reason", "detail"]),
    label: readString(value, ["label", "title", "category", "name", "criterion"]) ?? `비교 포인트 ${index + 1}`,
  };
};

const readComparisonDifferences = (
  payload: Record<string, unknown>,
  comparison: Record<string, unknown>,
) => {
  const rawDifferences =
    payload.differences ??
    payload.comparison_points ??
    payload.diff ??
    comparison.differences ??
    comparison.comparison_points;

  if (!Array.isArray(rawDifferences)) return [];

  return rawDifferences
    .map(normalizeComparisonDifference)
    .filter((difference): difference is ProductComparisonDifference => difference !== null);
};

const createComparisonRequest = (
  detail: unknown,
  currentProductId: string,
): ProductComparisonRequest | null => {
  const action = getComparisonAction(detail);
  const actionType = readString(action, ["type"]);
  const actionTarget = readString(action, ["target"]);
  const source = actionType === "show_products" && actionTarget === "similar_products" ? "similar" : "comparison";
  const payload = getComparisonPayload(detail);
  const comparison =
    readRecord(payload, ["comparison", "comparison_result", "result", "analysis"]) ?? {};
  const baseProductId =
    readString(payload, ["base_product_id", "source_product_id", "current_product_id"]) ?? currentProductId;
  const directCompareProductId =
    readString(payload, [
      "compare_product_id",
      "compared_product_id",
      "comparison_product_id",
      "target_product_id",
      "recommended_product_id",
    ]) ??
    readProductId(payload.compare_product) ??
    readProductId(payload.compared_product) ??
    readProductId(payload.target_product);
  const candidateProductIds = uniqueProductIds([
    directCompareProductId,
    ...collectProductIds(payload.products),
    ...collectProductIds(payload.product_ids),
    ...collectProductIds(payload.compare_product_ids),
    ...collectProductIds(getComparisonItems(detail)),
  ]);
  const compareProductIds = candidateProductIds
    .filter((id) => id !== currentProductId && id !== baseProductId)
    .slice(0, 2);

  if (compareProductIds.length === 0) {
    return null;
  }

  const structuredSummary =
    readString(payload, ["summary", "comparison_summary", "description", "reason"]) ??
    readString(comparison, ["summary", "comparison_summary", "description", "reason"]);

  return {
    compareProductIds,
    differences: readComparisonDifferences(payload, comparison),
    recommendationReason:
      readString(payload, ["recommendation_reason", "recommendation", "conclusion", "final_recommendation"]) ??
      readString(comparison, ["recommendation_reason", "recommendation", "conclusion", "final_recommendation"]) ??
      "",
    source,
    summary: structuredSummary ?? (source === "comparison" ? getAgentMessage(detail) : null) ?? "",
  };
};

function ProductDetailSpaPage() {
  const [{ productId, recommendationId, skinType, sensitivity }] = useState(getDetailParams);
  const navigate = useNavigate();
  const { user } = useAuth();
  const [avoidIngredientMatchState, setAvoidIngredientMatchState] = useState<{
    matchSet: Set<string>;
    userId: number | null;
  }>({ matchSet: EMPTY_AVOID_INGREDIENT_MATCH_SET, userId: null });
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [narrativeProduct, setNarrativeProduct] = useState<RecommendationNarrativeProduct | null>(null);
  const [narrativeOverview, setNarrativeOverview] = useState<RecommendationNarrativeOverview | null>(null);
  const [narrativeSelectionGuide, setNarrativeSelectionGuide] = useState<string | null>(null);
  const [isNarrativeLoading, setIsNarrativeLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(Boolean(productId));
  const [errorMessage, setErrorMessage] = useState(() => productId ? "" : "상품 정보를 찾을 수 없습니다.");
  const [isAddingToCart, setIsAddingToCart] = useState(false);
  const [isWished, setIsWished] = useState(false);
  const [isWishlistPending, setIsWishlistPending] = useState(false);
  const [cartMessage, setCartMessage] = useState("");
  const [cartErrorMessage, setCartErrorMessage] = useState("");
  const [toastMessage, setToastMessage] = useState("");
  const toastTimerRef = useRef<number | null>(null);
  const [activeTab, setActiveTab] = useState(() => normalizeDetailHash(window.location.hash));
  const [isIngredientExpanded, setIsIngredientExpanded] = useState(false);
  const [activeEvidenceEffectName, setActiveEvidenceEffectName] = useState<string | null>(null);
  const [comparisonRequest, setComparisonRequest] = useState<ProductComparisonRequest | null>(null);
  const [comparisonProducts, setComparisonProducts] = useState<ProductDetail[]>([]);
  const [isComparisonLoading, setIsComparisonLoading] = useState(false);
  const [comparisonErrorMessage, setComparisonErrorMessage] = useState("");
  const [reviewTypeFilter, setReviewTypeFilter] = useState<ReviewTypeFilter>("all");
  const [reviewSort, setReviewSort] = useState<ReviewSortOption>("recommended");
  const [reviewPage, setReviewPage] = useState(1);
  const [isReviewTypePopoverOpen, setIsReviewTypePopoverOpen] = useState(false);
  const [isReviewSkinPopoverOpen, setIsReviewSkinPopoverOpen] = useState(false);
  const [isSkinFitOnly, setIsSkinFitOnly] = useState(false);
  const [reviewProfileSkinType, setReviewProfileSkinType] = useState<string | null>(null);
  const [likedReviewIds, setLikedReviewIds] = useState<Set<string>>(() => new Set());
  const [reviewSkinTypeFilter, setReviewSkinTypeFilter] = useState("");
  const restoredHashProductRef = useRef<string | null>(null);
  const reviewTypeFilterRef = useRef<HTMLDivElement | null>(null);
  const reviewSkinFilterRef = useRef<HTMLDivElement | null>(null);
  const { reviews: productReviews, summary: reviewSummary } = useProductReviews(product?.product_id ?? productId);

  useEffect(() => installHomeRuntime(), []);

  useEffect(() => () => {
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!isReviewTypePopoverOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!reviewTypeFilterRef.current?.contains(event.target as Node)) {
        setIsReviewTypePopoverOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isReviewTypePopoverOpen]);

  useEffect(() => {
    if (!isReviewSkinPopoverOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!reviewSkinFilterRef.current?.contains(event.target as Node)) {
        setIsReviewSkinPopoverOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isReviewSkinPopoverOpen]);

  useEffect(() => {
    const handleHashChange = () => {
      const hasHash = Boolean(window.location.hash);
      const normalizedHash = normalizeDetailHash(window.location.hash);
      setActiveTab(normalizedHash);
      if (normalizedHash !== window.location.hash) {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${normalizedHash}`);
      }
      if (hasHash) {
        scrollToDetailTabs("auto");
      }
    };
    handleHashChange();
    window.addEventListener("hashchange", handleHashChange);
    window.addEventListener("popstate", handleHashChange);
    return () => {
      window.removeEventListener("hashchange", handleHashChange);
      window.removeEventListener("popstate", handleHashChange);
    };
  }, []);

  useEffect(() => {
    const resetTimer = window.setTimeout(() => {
      setIsIngredientExpanded(false);
      setActiveEvidenceEffectName(null);
    }, 0);
    return () => window.clearTimeout(resetTimer);
  }, [product?.product_id]);

  const productImageUrls = useMemo(() => {
    const urls: string[] = [];
    if (product?.thumbnail_url) urls.push(product.thumbnail_url);
    product?.image_urls.forEach((imageUrl) => {
      if (imageUrl && !urls.includes(imageUrl)) urls.push(imageUrl);
    });
    return urls;
  }, [product]);

  const mainImageUrl = productImageUrls[0] ?? "";
  const descriptionImageUrls = productImageUrls.slice(1);

  useEffect(() => {
    const handleComparisonEvent = (event: Event) => {
      const request = createComparisonRequest((event as CustomEvent).detail, productId);
      if (!request) {
        return;
      }

      setComparisonRequest(request);
      setComparisonProducts([]);
      setComparisonErrorMessage("");

      window.requestAnimationFrame(() => {
        document.getElementById("productComparisonPanel")?.scrollIntoView({
          block: "start",
          behavior: "smooth",
        });
      });
    };

    window.addEventListener(AGENT_PRODUCT_COMPARISON_EVENT, handleComparisonEvent);
    return () => window.removeEventListener(AGENT_PRODUCT_COMPARISON_EVENT, handleComparisonEvent);
  }, [productId]);

  useEffect(() => {
    if (!productId) {
      return;
    }

    let isMounted = true;

    const loadProduct = async () => {
      setIsLoading(true);

      try {
        const response = await api.getProduct(productId, recommendationId);
        if (isMounted) setProduct(response);
      } catch {
        if (!isMounted) return;
        const fallbackProduct = getFallbackProductDetail(productId);
        if (fallbackProduct) {
          setProduct(fallbackProduct);
          setErrorMessage("");
          return;
        }
        setErrorMessage("상품 상세 정보를 불러오지 못했습니다.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    loadProduct();

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  useEffect(() => {
    if (!user || !productId || !product) {
      return;
    }

    addMyRecentProduct(productId).catch(() => {
      // Recent-view logging should never block the product detail page.
    });
  }, [product, productId, user]);

  useEffect(() => {
    if (!user || !productId) {
      return;
    }

    let isMounted = true;

    getMyWishlist()
      .then((items) => {
        if (!isMounted) return;
        setIsWished(items.some((item) => item.productId === productId));
      })
      .catch(() => {
        if (isMounted) setIsWished(false);
      });

    return () => {
      isMounted = false;
    };
  }, [productId, user]);

  const displayedIsWished = Boolean(user && isWished);
  const brandPagePath = product?.brand ? `/brand/${encodeURIComponent(product.brand)}` : "";

  useEffect(() => {
    if (!user) {
      return;
    }

    let isMounted = true;
    const currentUserId = user.id;

    getSavedSkinProfile()
      .then((profile) => {
        if (!isMounted) return;
        setReviewProfileSkinType(profile?.skin ?? (skinType || null));
        setAvoidIngredientMatchState({
          matchSet: getAvoidIngredientMatchSet(profile?.avoidIngredients ?? []),
          userId: currentUserId,
        });
      })
      .catch(() => {
        if (isMounted) {
          setReviewProfileSkinType(skinType || null);
          setAvoidIngredientMatchState({
            matchSet: EMPTY_AVOID_INGREDIENT_MATCH_SET,
            userId: currentUserId,
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [skinType, user]);

  useEffect(() => {
    if (!comparisonRequest) {
      return;
    }

    let isMounted = true;

    const loadComparisonProducts = async () => {
      setIsComparisonLoading(true);
      setComparisonErrorMessage("");

      const loadedProducts = await Promise.all(
        comparisonRequest.compareProductIds.map(async (compareProductId) => {
          try {
            return await api.getProduct(compareProductId, recommendationId);
          } catch {
            return getFallbackProductDetail(compareProductId);
          }
        }),
      );

      if (!isMounted) {
        return;
      }

      const nextProducts = loadedProducts.filter((item): item is ProductDetail => item !== null);
      setComparisonProducts(nextProducts);

      if (nextProducts.length === 0) {
        setComparisonErrorMessage("비교 상품 정보를 불러오지 못했습니다.");
      } else if (nextProducts.length < comparisonRequest.compareProductIds.length) {
        setComparisonErrorMessage("일부 비교 상품 정보를 불러오지 못했습니다.");
      }

      setIsComparisonLoading(false);
    };

    loadComparisonProducts().catch(() => {
      if (!isMounted) {
        return;
      }
      setComparisonProducts([]);
      setComparisonErrorMessage("비교 상품 정보를 불러오지 못했습니다.");
      setIsComparisonLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, [comparisonRequest, recommendationId]);

  useEffect(() => {
    if (!productId || !recommendationId) {
      return;
    }

    let isMounted = true;

    const loadNarrative = async () => {
      setNarrativeProduct(null);
      setNarrativeOverview(null);
      setNarrativeSelectionGuide(null);
      setIsNarrativeLoading(true);

      try {
        const response = await api.createRecommendationNarrative(recommendationId, {
          mode: "community_beta",
          view: "detail",
          product_id: productId,
          product_limit: 5,
          use_llm: true,
        });
        if (!isMounted) return;
        const productNarrative =
          response.narrative.product_explanations.find((item) => item.product_id === productId) ?? null;
        setNarrativeProduct(productNarrative);
        setNarrativeOverview(response.narrative.overview);
        setNarrativeSelectionGuide(response.narrative.selection_guide);
      } catch {
        if (!isMounted) return;
        setNarrativeProduct(null);
        setNarrativeOverview(null);
        setNarrativeSelectionGuide(null);
      } finally {
        if (isMounted) setIsNarrativeLoading(false);
      }
    };

    loadNarrative();

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  const detailData = useMemo(() => {
    if (!product) return null;

    const relatedIngredients =
      product.related_ingredients.length > 0 ? product.related_ingredients : product.key_ingredients;
    const coreIngredients = product.ingredients
      .filter((ingredient) => ingredient.name)
      .slice(0, CORE_INGREDIENT_COUNT)
      .map((ingredient) => ({
        ...ingredient,
        purpose: isInternalNoteText(ingredient.purpose) ? "" : ingredient.purpose,
      }));
    const allIngredients =
      product.ingredients.length > 0
        ? product.ingredients.map((ingredient) => ingredient.name).filter(Boolean)
        : relatedIngredients;
    const visibleIngredients = isIngredientExpanded
      ? allIngredients
      : allIngredients.slice(0, INITIAL_VISIBLE_INGREDIENT_COUNT);
    const hasMoreIngredients = allIngredients.length > INITIAL_VISIBLE_INGREDIENT_COUNT;
    const sanitizedEvidence = product.evidence.map((item) => ({
      ...item,
      evidence_text: isInternalNoteText(item.evidence_text) ? "" : item.evidence_text,
      source_title: isInternalNoteText(item.source_title) ? null : item.source_title,
    }));
    const effectGroups = Array.from(new Set(sanitizedEvidence.map((item) => item.effect_name).filter(Boolean)))
      .map((effect) => ({
        effect,
        icon: getEffectIcon(effect),
        label: getEffectLabel(effect),
        items: sanitizedEvidence.filter((item) => item.effect_name === effect),
      }))
      .filter((group) => group.items.length > 0);
    const groupedEvidence: { effectName: string; icon: EffectIconKey; items: typeof sanitizedEvidence }[] = [];
    sanitizedEvidence.forEach((item) => {
      const effectName = item.effect_name || "기타";
      const existingGroup = groupedEvidence.find((group) => group.effectName === effectName);
      if (existingGroup) {
        existingGroup.items.push(item);
      } else {
        groupedEvidence.push({
          effectName,
          icon: getEffectIcon(effectName),
          items: [item],
        });
      }
    });

    return {
      relatedIngredients,
      coreIngredients,
      allIngredients,
      visibleIngredients,
      hasMoreIngredients,
      sanitizedEvidence,
      effectGroups,
      groupedEvidence,
    };
  }, [isIngredientExpanded, product]);

  const avoidIngredientMatchSet =
    user && avoidIngredientMatchState.userId === user.id
      ? avoidIngredientMatchState.matchSet
      : EMPTY_AVOID_INGREDIENT_MATCH_SET;
  const avoidIngredientMatchCount = detailData
    ? detailData.allIngredients.filter((name) => avoidIngredientMatchSet.has(name)).length
    : 0;

  useEffect(() => {
    if (!product?.product_id || !detailData) {
      return;
    }

    const normalizedHash = normalizeDetailHash(window.location.hash);
    const restoreKey = `${product.product_id}:${normalizedHash}`;
    if (restoredHashProductRef.current === restoreKey) {
      return;
    }

    restoredHashProductRef.current = restoreKey;
    setActiveTab(normalizedHash);
    if (window.location.hash) {
      scrollToDetailTabs("auto");
    }
  }, [detailData, product?.product_id]);

  const tabClassName = (hash: string) => `detail-tab${activeTab === hash ? " active" : ""}`;
  const panelClassName = (hash: DetailTabHash) =>
    `detail-section detail-tab-panel${activeTab === hash ? " active" : ""}`;
  const openEvidenceModal = (effectName: string) => setActiveEvidenceEffectName(effectName);
  const closeEvidenceModal = () => setActiveEvidenceEffectName(null);

  const handleTabClick = (hash: DetailTabHash) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    const normalizedHash = normalizeDetailHash(hash);

    setActiveTab(normalizedHash);
    if (window.location.hash !== normalizedHash) {
      window.history.pushState(
        null,
        "",
        `${window.location.pathname}${window.location.search}${normalizedHash}`,
      );
    }

    scrollToDetailTabs("smooth");
  };

  const activeEvidenceGroup = activeEvidenceEffectName
    ? detailData?.groupedEvidence.find((group) => group.effectName === activeEvidenceEffectName) ?? null
    : null;
  const userReviewSkinType = user ? reviewProfileSkinType ?? (skinType || "복합성") : null;
  const hasActiveReviewTypeFilter = reviewTypeFilter !== "all";
  const hasActiveSkinTypeFilter = Boolean(reviewSkinTypeFilter);
  const activeReviewTypeLabel =
    reviewTypeOptions.find((option) => option.value === reviewTypeFilter)?.label ?? "전체 리뷰";
  const activeSkinTypeLabel = reviewSkinTypeFilter || "전체";
  const filteredReviews = useMemo(() => {
    const nextReviews = productReviews.filter((review) => {
      const matchesType =
        reviewTypeFilter === "all" ||
        (reviewTypeFilter === "photo" && review.photos.length > 0) ||
        (reviewTypeFilter === "month" && review.usedOverMonth) ||
        (reviewTypeFilter === "repurchase" && review.isRepurchase);
      const matchesSkinFit = !isSkinFitOnly || !userReviewSkinType || review.skinType === userReviewSkinType;
      const matchesSkinType = !reviewSkinTypeFilter || review.skinType === reviewSkinTypeFilter;

      return matchesType && matchesSkinFit && matchesSkinType;
    });

    return [...nextReviews].sort((a, b) => {
      if (reviewSort === "latest") {
        return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
      }
      if (reviewSort === "ratingHigh") {
        return b.rating - a.rating;
      }
      if (reviewSort === "ratingLow") {
        return a.rating - b.rating;
      }
      return b.likeCount - a.likeCount;
    });
  }, [isSkinFitOnly, productReviews, reviewSkinTypeFilter, reviewSort, reviewTypeFilter, userReviewSkinType]);
  const totalReviewPages = Math.max(1, Math.ceil(filteredReviews.length / reviewPageSize));
  const currentReviewPage = Math.min(reviewPage, totalReviewPages);
  const visibleReviews = filteredReviews.slice(
    (currentReviewPage - 1) * reviewPageSize,
    currentReviewPage * reviewPageSize,
  );

  const handleGoBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigateWithinApp("/");
  };

  const addCurrentProductToCart = async () => {
    if (!productId) {
      throw new Error("상품 정보를 찾을 수 없습니다.");
    }

    const updatedCart = await addCartItem({
      product_id: productId,
      quantity: 1,
      source: "product_detail",
      recommendation_id: recommendationId ?? null,
    });
    window.dispatchEvent(new Event("cart:updated"));
    return updatedCart;
  };

  const showToast = (message: string) => {
    setToastMessage(message);
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToastMessage("");
      toastTimerRef.current = null;
    }, 2500);
  };

  const handleSkinFitToggle = () => {
    if (!user) {
      showToast("로그인 후 내 피부 맞춤 리뷰를 볼 수 있어요.");
      setIsSkinFitOnly(false);
      setReviewPage(1);
      return;
    }

    setIsSkinFitOnly((current) => !current);
    setReviewPage(1);
  };

  const toggleReviewLike = (reviewId: string) => {
    setLikedReviewIds((current) => {
      const next = new Set(current);
      if (next.has(reviewId)) {
        next.delete(reviewId);
      } else {
        next.add(reviewId);
      }
      return next;
    });
  };

  const scrollToReviewPageStart = () => {
    window.requestAnimationFrame(() => {
      const reviewControls = document.querySelector<HTMLElement>("#reviews .product-review-controls");
      if (!reviewControls) return;

      window.scrollTo({
        top: Math.max(0, reviewControls.getBoundingClientRect().top + window.scrollY - REVIEW_PAGE_SCROLL_OFFSET_PX),
        behavior: "smooth",
      });
    });
  };

  const handleReviewPageChange = (nextPage: number) => {
    const normalizedPage = Math.min(Math.max(1, nextPage), totalReviewPages);
    if (normalizedPage === currentReviewPage) return;

    setReviewPage(normalizedPage);
    scrollToReviewPageStart();
  };

  const handleAddToCart = async () => {
    setIsAddingToCart(true);
    setCartMessage("");
    setCartErrorMessage("");

    try {
      await addCurrentProductToCart();
      navigateWithinApp("/cart");
    } catch (error) {
      setCartErrorMessage(error instanceof Error ? error.message : "장바구니 담기에 실패했습니다.");
    } finally {
      setIsAddingToCart(false);
    }
  };

  const handleBuyNow = async () => {
    if (!user) {
      navigate("/login", { state: { from: window.location.pathname + window.location.search } });
      return;
    }

    setIsAddingToCart(true);
    setCartMessage("");
    setCartErrorMessage("");

    try {
      const updatedCart = await addCurrentProductToCart();
      const checkoutItem = updatedCart.items.find((item) => item.product_id === productId);

      if (!checkoutItem) {
        throw new Error("주문서로 이동할 장바구니 상품을 찾지 못했습니다.");
      }

      navigateWithinApp(`/checkout?cart_item_ids=${checkoutItem.id}`);
    } catch (error) {
      setCartErrorMessage(error instanceof Error ? error.message : "구매하기 처리에 실패했습니다.");
    } finally {
      setIsAddingToCart(false);
    }
  };

  const handleToggleWishlist = async () => {
    if (!productId || isWishlistPending) {
      return;
    }

    if (!user) {
      navigate("/login", { state: { from: window.location.pathname + window.location.search } });
      return;
    }

    const nextIsWished = !displayedIsWished;
    setIsWished(nextIsWished);
    setIsWishlistPending(true);

    try {
      if (nextIsWished) {
        await addMyWishlistItem(productId);
        showToast("찜한 상품에 추가했습니다.");
      } else {
        await deleteMyWishlistItem(productId);
        showToast("찜한 상품에서 해제했습니다.");
      }
    } catch {
      setIsWished(!nextIsWished);
      showToast("찜 처리에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsWishlistPending(false);
    }
  };

  const narrativeCard = narrativeProduct?.card;
  const narrativeHeadline =
    narrativeCard?.headline || narrativeOverview?.headline || "내 피부 고민 기준 추천 근거";
  const narrativeReason = narrativeCard?.reason || product?.reason_summary || "피부 고민 기준 추천 근거를 확인했습니다.";
  const narrativeRole = narrativeProduct?.role;
  const narrativeOverviewSummary = narrativeOverview?.summary;
  const narrativeKeyPoints = narrativeOverview?.key_points ?? [];
  const narrativeCaution = narrativeProduct?.caution;
  const narrativeSummaryText = narrativeOverviewSummary || null;
  const narrativeChips = narrativeCard?.chips?.length
    ? narrativeCard.chips
    : [
      ...new Set([
        ...(product?.evidence_tags ?? []),
        ...(product?.key_ingredients ?? []),
      ]),
    ].slice(0, 5);
  const baseNarrativeDetailSections = narrativeProduct?.detail_sections?.length
    ? narrativeProduct.detail_sections
    : [
      {
        title: "추천 근거",
        body: product?.reason_summary || "피부 고민과 성분 근거를 함께 확인했습니다.",
      },
      {
        title: "핵심 성분",
        body: product?.key_ingredients?.slice(0, 3).join(", ") || "핵심 성분 정보를 확인 중입니다.",
      },
      {
        title: "피부 타입",
        body: skinType || sensitivity ? `${skinType || "피부 타입"} · 민감도 ${sensitivity || "확인 중"}` : "피부 타입 조건을 함께 반영했습니다.",
      },
    ];
  const narrativeDetailSections = baseNarrativeDetailSections
    .map((section) => ({
      ...section,
      title: normalizeNarrativeTitle(section.title),
    }))
    .filter((section, index, sections) => {
      const body = section.body.trim();
      if (!body) return false;
      if (body === narrativeReason.trim()) return false;
      if (section.title === narrativeHeadline.trim()) return false;
      return sections.findIndex((item) => item.title === section.title && item.body.trim() === body) === index;
    })
    .slice(0, 4);

  return (
    <>
      <HomeHeader />
      <main className="detail-page">
        <section className="detail-shell">
          <button className="detail-mobile-back-button" type="button" aria-label="이전 화면으로 이동" onClick={handleGoBack}>
            <span aria-hidden="true">‹</span>
          </button>
          <div className="detail-breadcrumb">
            <a href="/">홈</a>
            <span>&gt;</span>
            <span>스킨케어</span>
            <span>&gt;</span>
            <span id="breadcrumbProduct">{product?.name ?? "상품 상세"}</span>
          </div>

          {isLoading ? (
            <div className="detail-loading">상품 상세 정보를 불러오는 중입니다.</div>
          ) : errorMessage ? (
            <div className="detail-loading">{errorMessage}</div>
          ) : product ? (
            <div className="detail-hero">
              <div className="detail-media">
                <div className="detail-image-box">
                  {mainImageUrl ? (
                    <img id="productImage" src={mainImageUrl} alt={product.name} />
                  ) : null}
                  {!mainImageUrl ? (
                    <div className="detail-image-empty" id="productImageEmpty">이미지 준비중</div>
                  ) : null}
                </div>
              </div>

              <div className="detail-summary">
                <div className="detail-brand-row">
                  {brandPagePath ? (
                    <Link className="detail-brand detail-brand-link" id="productBrand" to={brandPagePath}>
                      {product.brand}
                      <span aria-hidden="true">&gt;</span>
                    </Link>
                  ) : (
                    <div className="detail-brand" id="productBrand">{product.brand}</div>
                  )}
                  <div className="detail-actions">
                    <button className="detail-icon-btn" type="button" aria-label="공유">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="18" cy="5" r="3" />
                        <circle cx="6" cy="12" r="3" />
                        <circle cx="18" cy="19" r="3" />
                        <path d="M8.59 13.51 15.42 17.49M15.41 6.51 8.59 10.49" />
                      </svg>
                    </button>
                    <button
                      aria-label={displayedIsWished ? "찜 해제" : "찜"}
                      aria-pressed={displayedIsWished}
                      className={`detail-icon-btn${displayedIsWished ? " is-wished" : ""}`}
                      data-commerce-only
                      disabled={isWishlistPending}
                      onClick={handleToggleWishlist}
                      type="button"
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill={displayedIsWished ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l7.78-8.84a5.5 5.5 0 0 0 1.06-7.78z" />
                      </svg>
                    </button>
                  </div>
                </div>
                <h1 className="detail-title" id="productName">{product.name}</h1>
                <div className="detail-price-panel">
                  <div className="detail-price-row">
                    <span className="detail-price" id="productPrice">{formatPrice(product.lowest_price)}</span>
                  </div>
                </div>
                <div className="detail-tags" id="productTags">
                  {product.evidence_tags.map((tag) => (
                    <span className="detail-tag" key={tag}>{tag}</span>
                  ))}
                </div>
                <div className={`detail-match ai-narrative-card${isNarrativeLoading ? " loading" : ""}`}>
                  <div className="ai-narrative-head">
                    <strong>AI 추천 요약</strong>
                    <span aria-label="추천 문구는 성분 근거와 매칭 점수를 바탕으로 생성됩니다">i</span>
                  </div>
                  <div className="ai-narrative-body">
                    {narrativeRole ? (
                      <div className="ai-narrative-role">{narrativeRole}</div>
                    ) : null}
                    <strong>{isNarrativeLoading ? "추천 문구를 정리하는 중입니다." : narrativeHeadline}</strong>
                    <p id="matchReason">
                      <span aria-hidden="true">◆</span>
                      {narrativeReason}
                    </p>
                    {narrativeSummaryText ? (
                      <p className="ai-narrative-summary">{narrativeSummaryText}</p>
                    ) : null}
                    <div className="ai-narrative-chip-list">
                      {narrativeChips.map((chip) => (
                        <span key={chip}>{chip}</span>
                      ))}
                      <span className="score-chip" id="matchScore">추천 점수 {product.total_score}</span>
                    </div>
                    {narrativeKeyPoints.length > 0 ? (
                      <div className="ai-narrative-keypoints">
                        {narrativeKeyPoints.slice(0, 3).map((point) => (
                          <span key={point}>{point}</span>
                        ))}
                      </div>
                    ) : null}
                    <div className="ai-narrative-detail-list">
                      {narrativeDetailSections.map((section) => (
                        <div className="ai-narrative-detail-item" key={section.title}>
                          <strong>{section.title}</strong>
                          <p>{section.body}</p>
                        </div>
                      ))}
                    </div>
                    {narrativeCaution ? (
                      <div className="ai-narrative-caution">{narrativeCaution}</div>
                    ) : null}
                    {narrativeSelectionGuide ? (
                      <div className="ai-narrative-guide">{narrativeSelectionGuide}</div>
                    ) : null}
                  </div>
                </div>
                <div
                  className="detail-selectors"
                  id="profileSelectors"
                  style={{ display: skinType || sensitivity ? undefined : "none" }}
                >
                  <div className="detail-select-row" id="skinTypeRow" style={{ display: skinType ? undefined : "none" }}>
                    <span>피부 타입</span>
                    <strong id="skinTypeValue">{skinType}</strong>
                  </div>
                  <div className="detail-select-row" id="sensitivityRow" style={{ display: sensitivity ? undefined : "none" }}>
                    <span>민감성</span>
                    <strong id="sensitivityValue">{sensitivity}</strong>
                  </div>
                </div>
                <div data-commerce-only className="detail-cta-row">
                  <button className="detail-btn" disabled={isAddingToCart} type="button" onClick={handleAddToCart}>
                    {isAddingToCart ? "담는 중..." : "장바구니"}
                  </button>
                  <button className="detail-btn primary" disabled={isAddingToCart} type="button" onClick={handleBuyNow}>
                    구매하기
                  </button>
                </div>
                {cartMessage ? <p className="detail-cart-message">{cartMessage}</p> : null}
                {cartErrorMessage ? <p className="detail-cart-message error">{cartErrorMessage}</p> : null}
              </div>
            </div>
          ) : null}
        </section>

        {product && comparisonRequest ? (
          <ProductComparisonPanel
            differences={comparisonRequest.differences}
            errorMessage={comparisonErrorMessage}
            expectedProductCount={comparisonRequest.compareProductIds.length + 1}
            isLoading={isComparisonLoading}
            onClose={() => {
              setComparisonRequest(null);
              setComparisonProducts([]);
              setComparisonErrorMessage("");
            }}
            products={[product, ...comparisonProducts]}
            recommendationReason={comparisonRequest.recommendationReason}
            sensitivity={sensitivity}
            skinType={skinType}
            source={comparisonRequest.source}
            summary={comparisonRequest.summary}
          />
        ) : null}

        {product && detailData ? (
          <>
            <nav className="detail-tabs" aria-label="상품 상세 탭">
              <a className={tabClassName("#description")} href="#description" onClick={handleTabClick("#description")}>상품 설명</a>
              <a className={tabClassName("#ingredients")} href="#ingredients" onClick={handleTabClick("#ingredients")}>성분</a>
              <a className={tabClassName("#reviews")} href="#reviews" onClick={handleTabClick("#reviews")}>리뷰</a>
              <a className={tabClassName("#qna")} href="#qna" onClick={handleTabClick("#qna")}>QnA</a>
            </nav>

            <section className="detail-sections">
              <section className={panelClassName("#description")} id="description">
                {descriptionImageUrls.length > 0 ? (
                  <div className="product-description-images">
                    {descriptionImageUrls.map((imageUrl, index) => (
                      <img
                        src={imageUrl}
                        alt={`${product.name} 상세 이미지 ${index + 2}`}
                        loading="lazy"
                        key={imageUrl}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="detail-empty-state">
                    <strong>상세 이미지가 준비 중입니다.</strong>
                    <p>대표 이미지를 제외한 상품 설명 이미지를 확인하면 이 영역에 표시합니다.</p>
                  </div>
                )}
                <details className="detail-subsection detail-accordion">
                  <summary className="detail-subsection-head">
                    <h3>주의사항</h3>
                    <p>민감도와 피부 타입에 따라 사용 전 한 번 더 확인하면 좋은 정보입니다.</p>
                    <span className="detail-accordion-icon" aria-hidden="true">⌄</span>
                  </summary>
                  <div className="review-list" id="riskList">
                    {product.risk_flags.length > 0 ? (
                      product.risk_flags.map((riskFlag) => {
                        const risk = parseRiskFlag(riskFlag);
                        return (
                          <article className="review-item" key={riskFlag}>
                            <div className="review-item-head">
                              <strong>{risk.name}</strong>
                              <span>주의 정보</span>
                            </div>
                            <p>{risk.note || "민감도와 피부 타입에 따라 사용 전 성분 확인이 필요합니다."}</p>
                          </article>
                        );
                      })
                    ) : (
                      <div className="detail-empty-state">
                        <strong>표시할 주의 성분 정보가 없습니다.</strong>
                        <p>민감 피부라면 구매 전 전성분과 사용 방법을 한 번 더 확인하는 것을 권장합니다.</p>
                      </div>
                    )}
                  </div>
                </details>
                <details className="detail-subsection detail-accordion">
                  <summary className="detail-subsection-head">
                    <h3>배송 안내</h3>
                    <p>배송비와 배송 기간은 주문 조건과 배송지에 따라 달라질 수 있습니다.</p>
                    <span className="detail-accordion-icon" aria-hidden="true">⌄</span>
                  </summary>
                  <div className="detail-info-table" aria-label="배송 안내">
                    <div className="detail-info-row">
                      <strong>일반배송</strong>
                      <p>
                        배송 지역은 전국 기준이며, 기본 배송비는 2,500원 예시입니다. 결제 금액이 20,000원 이상인 경우 무료배송으로 안내할 수 있고, 도서 산간 등 일부 지역은 추가 배송비가 발생할 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>배송 가능일</strong>
                      <p>
                        배송 가능일은 주문 상품을 고객님께 배송 가능한 기간을 의미합니다. 연휴 및 공휴일은 기간 계산에서 제외되며, 현금 주문의 경우 입금 확인일을 기준으로 산정될 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>오늘드림 배송</strong>
                      <p>
                        오늘드림 배송은 일부 지역과 일부 상품에 한해 제공되는 예시 정책입니다. 주문 시간, 재고, 배송지에 따라 당일 도착 또는 익일 도착으로 안내될 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>유의사항</strong>
                      <p>
                        기상 상황, 재고 부족, 배송사 사정에 따라 배송이 지연되거나 주문이 취소될 수 있습니다. 정확한 배송 조건은 주문/결제 단계에서 다시 확인해야 합니다.
                      </p>
                    </div>
                  </div>
                </details>
                <details className="detail-subsection detail-accordion">
                  <summary className="detail-subsection-head">
                    <h3>교환·반품 안내</h3>
                    <p>교환, 반품, 환불 조건은 상품 상태와 신청 시점에 따라 달라질 수 있습니다.</p>
                    <span className="detail-accordion-icon" aria-hidden="true">⌄</span>
                  </summary>
                  <div className="detail-info-table" aria-label="교환·반품 안내">
                    <div className="detail-info-row">
                      <strong>신청 방법</strong>
                      <p>
                        마이페이지 내 주문내역에서 신청하는 방식을 기본 예시로 둡니다. 실제 운영 시 택배 회수, 매장 방문 등 가능한 신청 경로를 정책에 맞게 조정할 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>신청 기간</strong>
                      <p>
                        교환/반품 신청은 배송 완료 후 15일 이내 가능하다는 예시 기준입니다. 상품 불량이나 표시 내용과 다른 경우에는 상품 수령 후 3개월 이내 또는 해당 사실을 알 수 있었던 날부터 30일 이내로 안내할 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>회수 비용</strong>
                      <p>
                        고객 변심으로 인한 교환/반품 시 회수 비용이 발생할 수 있습니다. 상품 불량, 오배송 등 판매자 귀책 사유인 경우 비용 부담 기준은 별도 정책에 따라 달라질 수 있습니다.
                      </p>
                    </div>
                    <div className="detail-info-row">
                      <strong>불가 안내</strong>
                      <p>
                        배송 완료 후 일정 기간이 지났거나, 개봉/사용 흔적, 구성품 누락, 고객 부주의로 인한 훼손이 있는 경우 교환/반품/환불이 제한될 수 있습니다.
                      </p>
                    </div>
                  </div>
                </details>
              </section>

              <section className={panelClassName("#ingredients")} id="ingredients">
                <h2>성분 정보</h2>
                <div className="review-ingredient-layout ingredients-only">
                  <div className="ingredient-panel">
                    <div className="ingredient-tags" id="ingredientTags">
                      <div className="ingredient-tag-group">
                        <div className="ingredient-evidence-card-headline">
                          <span className="ingredient-evidence-card-title-wrap">
                            <span className="ingredient-evidence-card-icon" aria-hidden="true">
                              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M9 2h6M10 2v6.5L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 8.5V2" />
                                <path d="M7.5 14h9" />
                              </svg>
                            </span>
                            <strong className="ingredient-evidence-card-title">대표 성분</strong>
                          </span>
                        </div>
                        <div className="core-ingredient-list">
                          {detailData.coreIngredients.length > 0 ? (
                            detailData.coreIngredients.map((ingredient) => (
                              <article
                                className={`core-ingredient-item${avoidIngredientMatchSet.has(ingredient.name) ? " ingredient-avoid-card" : ""}`}
                                key={ingredient.name}
                              >
                                <strong>{ingredient.name}</strong>
                                <p>{ingredient.purpose || "성분 정보 준비 중"}</p>
                              </article>
                            ))
                          ) : (
                            <span className="ingredient-tag empty">대표 성분 정보 없음</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="detail-subsection ingredient-evidence-section" id="ingredientEvidence">
                  <div className="detail-subsection-head">
                    <h3>성분 근거</h3>
                  </div>
                  <div
                    className="ingredient-evidence-list"
                    id="evidenceList"
                  >
                    {detailData.groupedEvidence.length > 0 ? (
                      detailData.groupedEvidence.map((group) => {
                        const effectLabel = getEffectTagLabel(group.effectName);

                        return (
                          <button
                            className="ingredient-evidence-tile"
                            type="button"
                            key={group.effectName}
                            onClick={() => openEvidenceModal(group.effectName)}
                          >
                            <span className="ingredient-evidence-card-title-wrap">
                              <span className="ingredient-evidence-card-icon" aria-hidden="true">
                                <EffectIcon iconKey={group.icon} />
                              </span>
                              <strong className="ingredient-evidence-tile-title">{effectLabel}</strong>
                            </span>
                            <span className="ingredient-evidence-tile-count">관련 성분 {group.items.length}개</span>
                          </button>
                        );
                      })
                    ) : (
                      <div className="ingredient-evidence-tile"><p>표시할 성분 효능 근거가 없습니다.</p></div>
                    )}
                  </div>
                  {activeEvidenceGroup ? (
                    <div
                      className="ingredient-evidence-modal-backdrop"
                      role="presentation"
                      onClick={closeEvidenceModal}
                    >
                      <div
                        className="ingredient-evidence-modal"
                        role="dialog"
                        aria-modal="true"
                        aria-label={`${getEffectTagLabel(activeEvidenceGroup.effectName)} 성분 근거`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <div className="ingredient-evidence-modal-head">
                          <span className="ingredient-evidence-card-title-wrap">
                            <span className="ingredient-evidence-card-icon" aria-hidden="true">
                              <EffectIcon iconKey={activeEvidenceGroup.icon} />
                            </span>
                            <strong className="ingredient-evidence-card-title">
                              {getEffectTagLabel(activeEvidenceGroup.effectName)}
                            </strong>
                          </span>
                          <button
                            className="ingredient-evidence-modal-close"
                            type="button"
                            aria-label="닫기"
                            onClick={closeEvidenceModal}
                          >
                            ×
                          </button>
                        </div>
                        <div className="ingredient-evidence-modal-body">
                          {activeEvidenceGroup.items.map((evidence, index) => {
                            const sourceUrl = getSourceUrlForEvidence(product, evidence.source_title);
                            const effectLabel = getEffectTagLabel(activeEvidenceGroup.effectName);
                            return (
                              <div
                                className="ingredient-evidence-effect-row"
                                key={`${evidence.ingredient_name}-${evidence.source_title}-${index}`}
                              >
                                <div className="ingredient-evidence-effect-head">
                                  <strong className="ingredient-evidence-effect-label">
                                    {evidence.ingredient_name || "성분"}
                                  </strong>
                                  <span className={evidenceLevelBadgeClass[evidence.evidence_level]}>
                                    {evidenceLevelLabel[evidence.evidence_level]}
                                  </span>
                                </div>
                                <p className="ingredient-evidence-effect-text">
                                  {getIngredientEvidenceDisplayText(evidence, effectLabel)}
                                </p>
                                {sourceUrl ? (
                                  <a
                                    className="ingredient-evidence-source-link"
                                    href={sourceUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title={evidence.source_title ?? undefined}
                                  >
                                    출처 보기 <span aria-hidden="true">↗</span>
                                  </a>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="detail-subsection">
                <div className="ingredient-copy" id="ingredientCopy">
                  <div className="ingredient-copy-label-row ingredient-evidence-card-headline">
                    <div className="ingredient-copy-label-group">
                      <span className="ingredient-evidence-card-title-wrap">
                        <span className="ingredient-evidence-card-icon" aria-hidden="true">
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M8 6h13M8 12h13M8 18h13" />
                            <path d="M3 6h.01M3 12h.01M3 18h.01" strokeWidth="2.5" />
                          </svg>
                        </span>
                        <strong className="ingredient-evidence-card-title">전성분</strong>
                      </span>
                      {avoidIngredientMatchCount > 0 ? (
                        <span className="ingredient-avoid-badge">
                          회피 성분 {avoidIngredientMatchCount}개 포함
                        </span>
                      ) : null}
                    </div>
                    {detailData.hasMoreIngredients ? (
                      <button
                        className="ingredient-copy-toggle"
                        type="button"
                        aria-expanded={isIngredientExpanded}
                        aria-controls="ingredientCopyText"
                        onClick={() => setIsIngredientExpanded((current) => !current)}
                      >
                        {isIngredientExpanded ? "접기" : `전체 ${detailData.allIngredients.length}개 보기`}
                        <span aria-hidden="true">{isIngredientExpanded ? "⌃" : "⌄"}</span>
                      </button>
                    ) : null}
                  </div>
                  <p className="ingredient-copy-text" id="ingredientCopyText">
                    {detailData.visibleIngredients.length > 0
                      ? detailData.visibleIngredients.map((ingredientName, index) => (
                          <span key={`${ingredientName}-${index}`}>
                            {avoidIngredientMatchSet.has(ingredientName) ? (
                              <span className="ingredient-avoid-match">{ingredientName}</span>
                            ) : (
                              ingredientName
                            )}
                            {index < detailData.visibleIngredients.length - 1 ? ", " : ""}
                          </span>
                        ))
                      : "성분 정보가 준비 중입니다."}
                    {!isIngredientExpanded && detailData.hasMoreIngredients ? (
                      <span className="ingredient-copy-ellipsis" aria-hidden="true"> ...</span>
                    ) : null}
                  </p>
                </div>
                <p className="ingredient-name-basis-note">
                  해당 성분명은 식품의약품안전처 기준 및 성분 근거 데이터에 따른 표시입니다.
                </p>
                </div>
              </section>
              <section className={panelClassName("#reviews")} id="reviews">
                <div className="product-review-head">
                  <div>
                    <h2>리뷰</h2>
                  </div>
                </div>

                <div className="product-review-summary">
                  <div className="product-review-score">
                    <span aria-hidden="true"><ReviewStarIcon filled size={30} /></span>
                    <strong>{reviewSummary.averageRating.toFixed(1)}</strong>
                    <p>{reviewSummary.totalCount}개 평가</p>
                  </div>
                  <div className="product-review-rating-bars" aria-label="별점 분포">
                    {[5, 4, 3, 2, 1].map((score) => {
                      const count = reviewSummary.ratingDistribution[score as 1 | 2 | 3 | 4 | 5];
                      const percent = Math.round((count / reviewSummary.totalCount) * 100);
                      return (
                        <div className="product-review-rating-row" key={score}>
                          <span>{score}</span>
                          <div className="product-review-rating-track">
                            <span style={{ width: `${percent}%` }} />
                          </div>
                          <strong>{percent}%</strong>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="product-review-stats" aria-label="리뷰 통계">
                  {reviewSummary.stats.map((item) => (
                    <div className="product-review-stat-row" key={item.label}>
                      <span className="product-review-stat-pill">{item.label}</span>
                      <strong>{item.text}</strong>
                      <i aria-hidden="true" />
                      <b>{item.percent}%</b>
                    </div>
                  ))}
                </div>

                <div className="product-review-controls">
                  <div className="product-review-filter-group">
                    <div className="product-review-filter-popover-wrap" ref={reviewTypeFilterRef}>
                      <button
                        className={hasActiveReviewTypeFilter ? "product-review-filter-button active" : "product-review-filter-button"}
                        type="button"
                        aria-expanded={isReviewTypePopoverOpen}
                        onClick={() => setIsReviewTypePopoverOpen((current) => !current)}
                      >
                        {hasActiveReviewTypeFilter ? <strong>{activeReviewTypeLabel}</strong> : "리뷰 유형"}
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M6 9l6 6 6-6" />
                        </svg>
                      </button>
                      {isReviewTypePopoverOpen ? (
                        <div className="product-review-type-popover">
                          {reviewTypeOptions.map((option) => (
                            <button
                              className={option.value === reviewTypeFilter ? "active" : ""}
                              type="button"
                              key={option.value}
                              onClick={() => {
                                setReviewTypeFilter(option.value);
                                setReviewPage(1);
                                setIsReviewTypePopoverOpen(false);
                              }}
                            >
                              {option.label}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="product-review-filter-popover-wrap" ref={reviewSkinFilterRef}>
                      <button
                        className={hasActiveSkinTypeFilter ? "product-review-filter-button active" : "product-review-filter-button"}
                        type="button"
                        aria-expanded={isReviewSkinPopoverOpen}
                        onClick={() => setIsReviewSkinPopoverOpen((current) => !current)}
                      >
                        {hasActiveSkinTypeFilter ? <strong>{activeSkinTypeLabel}</strong> : "피부 필터"}
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M6 9l6 6 6-6" />
                        </svg>
                      </button>
                      {isReviewSkinPopoverOpen ? (
                        <div className="product-review-type-popover">
                          <button
                            className={reviewSkinTypeFilter === "" ? "active" : ""}
                            type="button"
                            onClick={() => {
                              setReviewSkinTypeFilter("");
                              setReviewPage(1);
                              setIsReviewSkinPopoverOpen(false);
                            }}
                          >
                            전체
                          </button>
                          {reviewSkinTypeOptions.map((option) => (
                            <button
                              className={option === reviewSkinTypeFilter ? "active" : ""}
                              type="button"
                              key={option}
                              onClick={() => {
                                setReviewSkinTypeFilter(option);
                                setReviewPage(1);
                                setIsReviewSkinPopoverOpen(false);
                              }}
                            >
                              {option}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="product-review-controls-row2">
                    <button
                      className={isSkinFitOnly ? "product-review-skin-toggle active" : "product-review-skin-toggle"}
                      type="button"
                      aria-pressed={isSkinFitOnly}
                      onClick={handleSkinFitToggle}
                    >
                      <span className="product-review-skin-toggle-track" aria-hidden="true">
                        <span className="product-review-skin-toggle-knob" />
                      </span>
                      내 피부 맞춤
                    </button>

                    <div className="product-review-sort-list" aria-label="리뷰 정렬">
                      {reviewSortOptions.map((option) => (
                        <button
                          className={option.value === reviewSort ? "active" : ""}
                          type="button"
                          key={option.value}
                          onClick={() => {
                            setReviewSort(option.value);
                            setReviewPage(1);
                          }}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="product-review-list" aria-live="polite">
                  {visibleReviews.length > 0 ? (
                    visibleReviews.map((review) => {
                      const isLiked = likedReviewIds.has(review.id);
                      return (
                        <article className="product-review-card" key={review.id}>
                          <div className="product-review-card-head">
                            <div className={`product-review-avatar ${getAvatarColorClass(review.id)}`} aria-hidden="true">{review.initial}</div>
                            <div className="product-review-profile">
                              <div className="product-review-name-line">
                                <strong>{review.nickname}</strong>
                                {review.isRepurchase ? (
                                  <span className="product-review-badge repurchase">
                                    <span aria-hidden="true">↻</span>
                                    재구매
                                  </span>
                                ) : null}
                                {review.usedOverMonth ? (
                                  <span className="product-review-badge month">
                                    <span aria-hidden="true">◷</span>
                                    한달이상사용
                                  </span>
                                ) : null}
                              </div>
                              <p>{[review.skinType, review.skinTone, ...review.concerns].join(" · ")}</p>
                            </div>
                          </div>

                          <div className="product-review-meta">
                            <span className="product-review-stars" aria-label={`별점 ${review.rating}점`}>
                              <ReviewStarRow rating={review.rating} />
                            </span>
                            <time dateTime={review.createdAt}>{formatReviewDate(review.createdAt)}</time>
                          </div>
                          <p className="product-review-option">옵션 · {review.optionName}</p>
                          <p className="product-review-body">{review.body}</p>

                          {review.photos.length > 0 ? (
                            <div className="product-review-photos" aria-label={`리뷰 사진 ${review.photos.length}장`}>
                              {review.photos.slice(0, 3).map((photo, index) => {
                                const remainingCount = review.photos.length - 3;
                                const showMore = index === 2 && remainingCount > 0;
                                return (
                                  <div className="product-review-photo" key={photo}>
                                    {showMore ? (
                                      <span className="product-review-photo-more">+{remainingCount}</span>
                                    ) : (
                                      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                        <rect x="3" y="6" width="18" height="14" rx="3" />
                                        <path d="M8 6l1.3-2.2A2 2 0 0 1 11 2.8h2a2 2 0 0 1 1.7 1L16 6" />
                                        <circle cx="12" cy="13" r="3.4" />
                                      </svg>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          ) : null}

                          <div className="product-review-actions">
                            <button type="button">
                              <span aria-hidden="true">□</span>
                              신고하기
                            </button>
                            <button
                              className={isLiked ? "liked" : ""}
                              type="button"
                              aria-pressed={isLiked}
                              onClick={() => toggleReviewLike(review.id)}
                            >
                              <svg width="15" height="15" viewBox="0 0 24 24" fill={isLiked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <path d="M12 21s-6.716-4.35-9.428-8.06C.94 10.42 1.3 6.9 4.02 5.06c2.28-1.54 5.02-.9 6.62 1.02L12 7.5l1.36-1.42c1.6-1.92 4.34-2.56 6.62-1.02 2.72 1.84 3.08 5.36 1.45 7.88C18.716 16.65 12 21 12 21z" />
                              </svg>
                              좋아요 {review.likeCount + (isLiked ? 1 : 0)}
                            </button>
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <div className="product-review-empty">
                      <strong>조건에 맞는 리뷰가 없습니다.</strong>
                      <p>필터를 조금 넓혀서 다시 확인해보세요.</p>
                    </div>
                  )}
                </div>

                {totalReviewPages > 1 ? (
                  <div className="product-review-pagination" aria-label="리뷰 페이지">
                    <button
                      type="button"
                      disabled={currentReviewPage === 1}
                      onClick={() => handleReviewPageChange(currentReviewPage - 1)}
                    >
                      ‹
                    </button>
                    {Array.from({ length: totalReviewPages }, (_, index) => index + 1).map((page) => (
                      <button
                        className={page === currentReviewPage ? "active" : ""}
                        type="button"
                        key={page}
                        aria-current={page === currentReviewPage ? "page" : undefined}
                        onClick={() => handleReviewPageChange(page)}
                      >
                        {page}
                      </button>
                    ))}
                    <button
                      type="button"
                      disabled={currentReviewPage === totalReviewPages}
                      onClick={() => handleReviewPageChange(currentReviewPage + 1)}
                    >
                      ›
                    </button>
                  </div>
                ) : null}

              </section>

              <section className={panelClassName("#qna")} id="qna">
                <h2>QnA</h2>
                <div className="detail-empty-state">
                  <strong>상품 문의 기능을 준비 중입니다.</strong>
                  <p>QnA API 계약이 확정되면 문의 목록과 답변 상태를 이 영역에 연결합니다.</p>
                </div>
              </section>
            </section>
          </>
        ) : null}
      </main>

      {toastMessage ? (
        <div className="activity-toast" role="status" aria-live="polite">
          <span className="activity-toast__dot" />
          {toastMessage}
        </div>
      ) : null}

    </>
  );
}

export default ProductDetailSpaPage;
