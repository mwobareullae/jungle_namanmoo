import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductComparisonPanel, { type ProductComparisonDifference } from "../components/ProductComparisonPanel";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import { addMyRecentProduct, addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { addCartItem } from "../lib/cartApi";
import { getFallbackProductDetail } from "../lib/fallbackProducts";
import { installHomeRuntime } from "../lib/homeRuntime";
import { navigateWithinApp } from "../lib/navigation";
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

const getDetailParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    productId: params.get("id") ?? "",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
  };
};

const getEffectIcon = (effect: string) => {
  if (effect.includes("미백") || effect.includes("톤")) return "!";
  if (effect.includes("주름") || effect.includes("탄력")) return "↻";
  if (effect.includes("여드름") || effect.includes("피지") || effect.includes("모공")) return "●";
  if (effect.includes("보습") || effect.includes("장벽")) return "◆";
  return "•";
};

const getEffectLabel = (effect: string) => {
  if (effect.includes("미백") || effect.includes("톤")) return "피부 미백에 도움되는 기능성 성분";
  if (effect.includes("주름") || effect.includes("탄력")) return "주름 개선에 도움되는 기능성 성분";
  if (effect.includes("여드름") || effect.includes("피지")) return "여드름·피지 케어에 연결된 성분";
  if (effect.includes("모공")) return "모공 케어에 연결된 성분";
  if (effect.includes("보습")) return "보습에 도움되는 성분";
  return `${effect} 효능과 연결된 성분`;
};

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
const STICKY_TAB_TOP_PX = 66;
const DETAIL_ACTIVE_OFFSET_PX = STICKY_TAB_TOP_PX + 72;
const CORE_INGREDIENT_COUNT = 4;
const INITIAL_VISIBLE_INGREDIENT_COUNT = 12;
const normalizeDetailHash = (hash: string) =>
  DETAIL_TAB_HASHES.includes(hash as typeof DETAIL_TAB_HASHES[number])
    ? hash
    : "#description";
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
  const [selectedEffect, setSelectedEffect] = useState<{
    icon: string;
    label: string;
    items: IngredientEvidence[];
  } | null>(null);
  const [comparisonRequest, setComparisonRequest] = useState<ProductComparisonRequest | null>(null);
  const [comparisonProducts, setComparisonProducts] = useState<ProductDetail[]>([]);
  const [isComparisonLoading, setIsComparisonLoading] = useState(false);
  const [comparisonErrorMessage, setComparisonErrorMessage] = useState("");

  useEffect(() => installHomeRuntime(), []);

  useEffect(() => () => {
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
  }, []);

  useEffect(() => {
    const handleHashChange = () => {
      const normalizedHash = normalizeDetailHash(window.location.hash);
      setActiveTab(normalizedHash);
      if (normalizedHash !== window.location.hash) {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${normalizedHash}`);
      }
    };
    handleHashChange();
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  useEffect(() => {
    if (!product) return;

    const handleScroll = () => {
      const activeSection = DETAIL_TAB_HASHES
        .map((hash) => document.getElementById(hash.slice(1)))
        .filter((section): section is HTMLElement => Boolean(section))
        .reverse()
        .find((section) => section.getBoundingClientRect().top <= DETAIL_ACTIVE_OFFSET_PX);

      if (activeSection) {
        setActiveTab(`#${activeSection.id}`);
      }
    };

    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", handleScroll);
    return () => {
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleScroll);
    };
  }, [product]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedEffect(null);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    const resetTimer = window.setTimeout(() => {
      setIsIngredientExpanded(false);
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
      setSelectedEffect(null);
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
      .slice(0, CORE_INGREDIENT_COUNT);
    const allIngredients =
      product.ingredients.length > 0
        ? product.ingredients.map((ingredient) => ingredient.name).filter(Boolean)
        : relatedIngredients;
    const visibleIngredients = isIngredientExpanded
      ? allIngredients
      : allIngredients.slice(0, INITIAL_VISIBLE_INGREDIENT_COUNT);
    const hasMoreIngredients = allIngredients.length > INITIAL_VISIBLE_INGREDIENT_COUNT;
    const effectGroups = Array.from(new Set(product.evidence.map((item) => item.effect_name).filter(Boolean)))
      .map((effect) => ({
        effect,
        icon: getEffectIcon(effect),
        label: getEffectLabel(effect),
        items: product.evidence.filter((item) => item.effect_name === effect),
      }))
      .filter((group) => group.items.length > 0);

    return {
      relatedIngredients,
      coreIngredients,
      visibleIngredients,
      hasMoreIngredients,
      effectGroups,
    };
  }, [isIngredientExpanded, product]);

  const tabClassName = (hash: string) => `detail-tab${activeTab === hash ? " active" : ""}`;
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
                  <div className="detail-brand" id="productBrand">{product.brand}</div>
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
              <a className={tabClassName("#description")} href="#description">상품 설명</a>
              <a className={tabClassName("#ingredients")} href="#ingredients">성분</a>
              <a className={tabClassName("#reviews")} href="#reviews">리뷰</a>
              <a className={tabClassName("#qna")} href="#qna">QnA</a>
            </nav>

            <section className="detail-sections">
              <section className="detail-section" id="description">
                <div className="section-kicker">Product Description</div>
                <h2>상품 상세 이미지</h2>
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
                <div className="detail-subsection">
                  <div className="detail-subsection-head">
                    <h3>주의사항</h3>
                    <p>민감도와 피부 타입에 따라 사용 전 한 번 더 확인하면 좋은 정보입니다.</p>
                  </div>
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
                </div>
                <div className="detail-subsection">
                  <div className="detail-subsection-head">
                    <h3>배송·교환 안내</h3>
                    <p>주문과 교환·반품 조건은 구매 전 확인해야 하는 상품 정보로 함께 제공합니다.</p>
                  </div>
                  <div className="shipping-info-list">
                    <article className="shipping-info-item">
                      <strong>배송 안내</strong>
                      <p>주문 결제 완료 후 상품 준비가 시작되며, 실제 배송 일정은 주문/결제 화면의 정책을 따릅니다.</p>
                    </article>
                    <article className="shipping-info-item">
                      <strong>교환·반품 안내</strong>
                      <p>개봉 여부, 사용 흔적, 상품 상태에 따라 교환·반품 가능 여부가 달라질 수 있습니다.</p>
                    </article>
                  </div>
                </div>
              </section>

              <section className="detail-section" id="ingredients">
                <div className="section-kicker">Ingredients</div>
                <h2>성분 정보</h2>
                <div className="review-ingredient-layout ingredients-only">
                  <div className="ingredient-panel">
                    <div className="ingredient-tags" id="ingredientTags">
                      <div className="ingredient-tag-group">
                        <div className="ingredient-tag-label">대표 성분</div>
                        <div className="core-ingredient-list">
                          {detailData.coreIngredients.length > 0 ? (
                            detailData.coreIngredients.map((ingredient) => (
                              <article className="core-ingredient-item" key={ingredient.name}>
                                <strong>{ingredient.name}</strong>
                                <p>{ingredient.purpose || "성분 목적 정보가 준비 중입니다."}</p>
                              </article>
                            ))
                          ) : (
                            <span className="ingredient-tag empty">대표 성분 정보 없음</span>
                          )}
                        </div>
                      </div>
                    </div>
                    {detailData.effectGroups.length > 0 ? (
                      <div className="effect-toggle-list" id="effectToggleList">
                          <div className="effect-toggle-title">효능별 핵심 성분</div>
                          {detailData.effectGroups.map((group) => (
                            <button
                              className="effect-toggle-row"
                              type="button"
                              onClick={() => setSelectedEffect(group)}
                              key={group.effect}
                            >
                              <span className="effect-toggle-icon">{group.icon}</span>
                              <span className="effect-toggle-copy">
                                <span className="effect-toggle-label">{group.label}</span>
                                <span className="effect-toggle-meta">관련 성분 {group.items.length}개</span>
                              </span>
                              <span className="effect-toggle-caret">⌄</span>
                            </button>
                          ))}
                      </div>
                    ) : null}
                    <div className="ingredient-copy" id="ingredientCopy">
                      <div className="ingredient-copy-label">전성분</div>
                      <p className="ingredient-copy-text">
                        {detailData.visibleIngredients.length > 0
                          ? detailData.visibleIngredients.join(", ")
                          : "성분 정보가 준비 중입니다."}
                      </p>
                      {detailData.hasMoreIngredients ? (
                        <div className="ingredient-copy-actions">
                          <button
                            className="ingredient-copy-toggle"
                            type="button"
                            aria-expanded={isIngredientExpanded}
                            aria-controls="ingredientCopy"
                            onClick={() => setIsIngredientExpanded((current) => !current)}
                          >
                            {isIngredientExpanded ? "접기" : "전성분 전체 보기"}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
                <div className="detail-subsection ingredient-evidence-section" id="ingredientEvidence">
                  <div className="detail-subsection-head">
                    <h3>성분 근거</h3>
                    <p>성분명, 기대 효능, 근거 수준, 출처를 한곳에서 확인할 수 있습니다.</p>
                  </div>
                  <div className="ingredient-evidence-list" id="evidenceList">
                    {product.evidence.length > 0 ? (
                      product.evidence.map((evidence) => {
                        const sourceUrl = getSourceUrlForEvidence(product, evidence.source_title);
                        return (
                          <article
                            className="ingredient-evidence-card"
                            key={`${evidence.ingredient_name}-${evidence.effect_name}-${evidence.source_title}`}
                          >
                            <div className="ingredient-evidence-card-head">
                              <strong>{evidence.ingredient_name || "성분"}</strong>
                              <span>{evidenceLevelLabel[evidence.evidence_level]}</span>
                            </div>
                            <p>{evidence.evidence_text || `${evidence.effect_name} 효능 근거를 확인했습니다.`}</p>
                            {evidence.source_title ? (
                              <a
                                className="ingredient-evidence-source-link"
                                href={sourceUrl || "#sourceList"}
                                target={sourceUrl ? "_blank" : undefined}
                                rel={sourceUrl ? "noopener noreferrer" : undefined}
                              >
                                {evidence.source_title}
                              </a>
                            ) : null}
                          </article>
                        );
                      })
                    ) : (
                      <div className="ingredient-evidence-card"><p>표시할 성분 효능 근거가 없습니다.</p></div>
                    )}
                  </div>
                  <div className="ingredient-source-list" id="sourceList">
                    {product.sources.length > 0 ? (
                      <>
                        <div className="ingredient-source-title">근거 출처</div>
                        <div className="ingredient-source-items">
                          {product.sources.map((source) => (
                            <a
                              className="ingredient-source-item"
                              href={source.url || "#sourceList"}
                              target={source.url ? "_blank" : undefined}
                              rel={source.url ? "noopener noreferrer" : undefined}
                              key={`${source.title}-${source.url}`}
                            >
                              <span>{source.source_type || "source"}</span>
                              <strong>{source.title || "출처"}</strong>
                            </a>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="ingredient-source-empty"><p>표시할 근거 출처 정보가 없습니다.</p></div>
                    )}
                  </div>
                </div>
              </section>

              <section className="detail-section" id="reviews">
                <div className="section-kicker">Reviews</div>
                <h2>리뷰</h2>
                <div className="detail-empty-state">
                  <strong>리뷰 기능을 준비 중입니다.</strong>
                  <p>리뷰 API 계약이 확정되면 실제 구매자 리뷰와 요약 정보를 이 영역에 연결합니다.</p>
                </div>
              </section>

              <section className="detail-section" id="qna">
                <div className="section-kicker">QnA</div>
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

      {selectedEffect ? (
        <>
          <div
            className="ingredient-sheet-backdrop open"
            id="ingredientSheetBackdrop"
            onClick={() => setSelectedEffect(null)}
          />
          <aside
            className="ingredient-sheet open"
            id="ingredientSheet"
            aria-hidden="false"
            aria-labelledby="ingredientSheetTitle"
            role="dialog"
          >
            <button className="ingredient-sheet-close" type="button" aria-label="닫기" onClick={() => setSelectedEffect(null)}>
              ×
            </button>
            <div className="ingredient-sheet-handle" />
            <div className="ingredient-sheet-head">
              <div className="ingredient-sheet-icon" id="ingredientSheetIcon">{selectedEffect.icon}</div>
              <div>
                <h3 id="ingredientSheetTitle">{selectedEffect.label}</h3>
                <p id="ingredientSheetDescription">해당 성분명은 식품의약품안전처 기준 및 성분 근거 데이터에 따른 표시입니다.</p>
              </div>
              <strong id="ingredientSheetCount">{selectedEffect.items.length}</strong>
            </div>
            <div className="ingredient-sheet-list" id="ingredientSheetList">
              {selectedEffect.items.map((item, index) => (
                <div className="ingredient-sheet-item" key={`${item.ingredient_name}-${item.source_title}-${index}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{item.ingredient_name || "성분"}</strong>
                    <p>{item.evidence_text || item.source_title || "성분 효능 근거를 확인했습니다."}</p>
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </>
      ) : null}
    </>
  );
}

export default ProductDetailSpaPage;
