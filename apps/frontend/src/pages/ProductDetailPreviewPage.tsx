import "./ProductDetailPreviewPage.css";
import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { useLocation } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductComparisonPanel from "../components/ProductComparisonPanel";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import { api } from "../lib/api";
import type { ProductDetail, RecommendationSummary } from "../types/recommendation";
import type { ProductListingItem } from "../types/product";
import { getProductImageUrl } from "../lib/imageUrls";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ActivityToast from "../components/ui/ActivityToast";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyRecentProduct, addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { addCartItem } from "../lib/cartApi";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import { useProductReviewsApi } from "../hooks/useProductReviewsApi";
import type { ProductReview } from "../hooks/useProductReviews";
import HeartIcon from "../components/ui/HeartIcon";
import ShoppingBagIcon from "../components/ui/ShoppingBagIcon";
import StarIcon from "../components/ui/StarIcon";
import PlusIcon from "../components/ui/PlusIcon";
import MinusIcon from "../components/ui/MinusIcon";
import CaretRightIcon from "../components/ui/CaretRightIcon";
import CaretDownIcon from "../components/ui/CaretDownIcon";
import CaretUpIcon from "../components/ui/CaretUpIcon";
import RecommendationCriteriaMockPanel from "../components/product-detail/RecommendationCriteriaMockPanel";
import ScoreAnalysisPanel from "../components/product-detail/ScoreAnalysisPanel";
import { useProductComparison } from "../contexts/ProductComparisonContext";

const tabs = ["상세정보", "성분정보", "리뷰", "점수분석", "Q&A"];
type EvidenceIconKey = "brighten" | "wrinkle" | "acne" | "moisture" | "soothe";

const getEvidenceIconKey = (effect: string): EvidenceIconKey => {
  if (effect.includes("미백") || effect.includes("톤")) return "brighten";
  if (effect.includes("주름") || effect.includes("탄력")) return "wrinkle";
  if (effect.includes("여드름") || effect.includes("피지") || effect.includes("모공")) return "acne";
  if (effect.includes("보습") || effect.includes("장벽")) return "moisture";
  return "soothe";
};

function EvidenceIcon({ icon }: { icon: EvidenceIconKey }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {icon === "moisture" ? <path d="M12 2.5c4 5 7 8.5 7 12a7 7 0 1 1-14 0c0-3.5 3-7 7-12z" /> : null}
    {icon === "soothe" ? <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" /> : null}
    {icon === "brighten" ? <><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" /></> : null}
    {icon === "wrinkle" ? <><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3" /><path d="M18 3v4h-4M6 21v-4h4" /></> : null}
    {icon === "acne" ? <path d="M12 3l7 3.5v5c0 5-3 8.5-7 9.5-4-1-7-4.5-7-9.5v-5L12 3z" /> : null}
  </svg>;
}

function ProductDetailPreviewPage() {
  const location = useLocation();
  const searchParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const recommendationId = searchParams.get("recommendation_id");
  const productId = searchParams.get("id");
  const [activeTab, setActiveTab] = useState(0);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [recommendationSummary, setRecommendationSummary] = useState<RecommendationSummary | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(productId));
  const [loadErrorMessage, setLoadErrorMessage] = useState(
    productId ? "" : "상품 정보를 찾을 수 없습니다.",
  );
  const [comparisonProducts, setComparisonProducts] = useState<ProductDetail[]>([]);
  const [comparisonErrorMessage, setComparisonErrorMessage] = useState("");
  const [isComparisonLoading, setIsComparisonLoading] = useState(false);
  const [isDetailsExpanded, setIsDetailsExpanded] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [selectedEvidenceEffect, setSelectedEvidenceEffect] = useState<string | null>(null);
  const [brandProducts, setBrandProducts] = useState<ProductListingItem[]>([]);
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);
  const [reviewSort, setReviewSort] = useState<"latest" | "helpful" | "rating_high" | "rating_low">("helpful");
  const [reviewType, setReviewType] = useState<"ALL" | "GENERAL" | "MONTH_USE">("ALL");
  const [reviewRepurchase, setReviewRepurchase] = useState(false);
  const [reviewSkinType, setReviewSkinType] = useState("");
  const [reviewCursor, setReviewCursor] = useState<string | null>(null);
  const [isPurchasePending, setIsPurchasePending] = useState(false);
  const { user } = useAuth();
  const { clearComparison, comparisonIntent } = useProductComparison();
  const { message: toastMessage, showToast } = useActivityToast();
  const reviewApi = useProductReviewsApi(product?.product_id, product?.review_summary, {
    cursor: reviewCursor,
    sort: reviewSort,
    reviewType: reviewType === "ALL" ? undefined : reviewType,
    repurchase: reviewRepurchase || undefined,
    skinType: reviewSkinType || undefined,
  });
  const hasProductReviews = (product?.review_summary?.review_count ?? 0) > 0 || reviewApi.reviews.length > 0;
  const hasScoreAnalysis = Boolean(product?.score_breakdown);
  const isSoldOut = isProductSoldOut(product?.purchase_info);
  const visibleTabs = useMemo(
    () => tabs
      .map((label, index) => ({ index, label }))
      .filter((tab) => tab.index !== 3 || hasScoreAnalysis),
    [hasScoreAnalysis],
  );

  const activeComparison = comparisonIntent?.sourceProductId === productId ? comparisonIntent : null;
  const activeComparisonCreatedAt = activeComparison?.createdAt;

  useEffect(() => {
    if (!productId) {
      return;
    }

    let isMounted = true;

    const loadProduct = async () => {
      await Promise.resolve();
      if (!isMounted) return;
      setIsLoading(true);
      setLoadErrorMessage("");
      setProduct(null);
      setBrandProducts([]);

      let response: ProductDetail;
      try {
        response = await api.getProduct(productId, recommendationId ?? undefined);
      } catch {
        if (!isMounted) return;
        setLoadErrorMessage("상품 상세 정보를 불러오지 못했습니다.");
        setIsLoading(false);
        return;
      }

      if (!isMounted) return;
      setProduct(response);
      setIsLoading(false);

      try {
        const brands = await api.getBrands(response.brand, 1, 100);
        if (!isMounted) return;
        const brand = brands.items.find((item) => item.name.trim() === response.brand.trim());
        if (!brand) {
          setBrandProducts([]);
          return;
        }
        const listing = await api.getProductListing({ brandCodes: [brand.code], page: 1, pageSize: 8, sort: "popular" });
        if (!isMounted) return;
        setBrandProducts(listing.items.filter((item) => item.product_id !== response.product_id).slice(0, 4));
      } catch {
        if (!isMounted) return;
        setBrandProducts([]);
      }
    };

    void loadProduct();

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  useEffect(() => {
    let isMounted = true;
    if (!recommendationId) {
      void Promise.resolve().then(() => {
        if (isMounted) setRecommendationSummary(null);
      });
      return () => {
        isMounted = false;
      };
    }
    api.getRecommendation(recommendationId, { page: 1, pageSize: 1 })
      .then((response) => {
        if (isMounted) setRecommendationSummary(response.summary);
      })
      .catch(() => {
        if (isMounted) setRecommendationSummary(null);
      });
    return () => {
      isMounted = false;
    };
  }, [recommendationId]);

  useEffect(() => {
    if (!user || !productId || product?.product_id !== productId) {
      return;
    }

    void addMyRecentProduct(productId).catch(() => {
      // 최근 본 상품 기록 실패가 상품 상세 이용을 막지 않도록 한다.
    });
  }, [product, productId, user]);

  useEffect(() => {
    if (!activeComparison) {
      return;
    }

    let isMounted = true;

    const loadComparisonProducts = async () => {
      setIsComparisonLoading(true);
      setComparisonErrorMessage("");

      const responses = await Promise.all(activeComparison.compareProductIds.map(async (compareProductId) => {
        try {
          return await api.getProduct(compareProductId, recommendationId ?? undefined);
        } catch {
          return null;
        }
      }));

      if (!isMounted) return;
      const loadedProducts = responses.filter((response): response is ProductDetail => response !== null);
      setComparisonProducts(loadedProducts);
      if (loadedProducts.length === 0) {
        setComparisonErrorMessage("비교 상품 정보를 불러오지 못했습니다.");
      } else if (loadedProducts.length < activeComparison.compareProductIds.length) {
        setComparisonErrorMessage("일부 비교 상품 정보를 불러오지 못했습니다.");
      }
      setIsComparisonLoading(false);
    };

    void loadComparisonProducts();

    return () => {
      isMounted = false;
    };
  }, [activeComparison, recommendationId]);

  useEffect(() => {
    if (!activeComparisonCreatedAt || !product) return;

    const frame = window.requestAnimationFrame(() => {
      document.getElementById("productComparisonPanel")?.scrollIntoView({
        block: "start",
        behavior: "smooth",
      });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeComparisonCreatedAt, product]);

  useEffect(() => {
    let isMounted = true;
    if (!user) {
      queueMicrotask(() => {
        if (isMounted) setWishedProductIds(new Set());
      });
      return () => {
        isMounted = false;
      };
    }
    getMyWishlist()
      .then((items) => {
        if (isMounted) setWishedProductIds(new Set(items.map((item) => item.productId)));
      })
      .catch(() => {
        if (isMounted) setWishedProductIds(new Set());
      });
    return () => {
      isMounted = false;
    };
  }, [user]);

  const toggleWishlist = async (productId: string) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (pendingWishlistProductIds.has(productId)) return;
    const wasWished = wishedProductIds.has(productId);
    setWishedProductIds((previous) => {
      const next = new Set(previous);
      if (wasWished) next.delete(productId); else next.add(productId);
      return next;
    });
    setPendingWishlistProductIds((previous) => new Set(previous).add(productId));
    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId);
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setWishedProductIds((previous) => {
        const next = new Set(previous);
        if (wasWished) next.add(productId); else next.delete(productId);
        return next;
      });
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((previous) => {
        const next = new Set(previous);
        next.delete(productId);
        return next;
      });
    }
  };

  const handlePurchase = async () => {
    if (!product || isPurchasePending) return;
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (product.purchase_info && !product.purchase_info.can_purchase) {
      showToast("현재 구매할 수 없는 상품입니다.");
      return;
    }

    setIsPurchasePending(true);
    try {
      const updatedCart = await addCartItem({
        product_id: product.product_id,
        quantity,
        source: "product_detail",
        recommendation_id: recommendationId,
      });
      window.dispatchEvent(new Event("cart:updated"));
      const checkoutItem = updatedCart.items.find((item) => item.product_id === product.product_id);
      if (!checkoutItem) throw new Error("주문서로 이동할 상품을 찾지 못했습니다.");
      await navigateWithinApp(`/checkout?cart_item_ids=${checkoutItem.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "구매하기 처리에 실패했습니다.");
    } finally {
      setIsPurchasePending(false);
    }
  };

  const handleAddToCart = async () => {
    if (!product) return;
    try {
      await addCartItem({
        product_id: product.product_id,
        quantity,
        source: "product_detail",
        recommendation_id: recommendationId,
      });
      window.dispatchEvent(new Event("cart:updated"));
      showToast("장바구니에 담았습니다.");
      await navigateWithinApp("/cart");
    } catch {
      showToast("장바구니 담기에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  useEffect(() => {
    const sections = visibleTabs
      .map((tab) => document.getElementById(`preview-${tab.index}`))
      .filter((section): section is HTMLElement => Boolean(section));
    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) {
          const sectionId = (visible[0].target as HTMLElement).id;
          const nextIndex = Number(sectionId.replace("preview-", ""));
          if (Number.isInteger(nextIndex)) setActiveTab(nextIndex);
        }
      },
      { rootMargin: "-88px 0px -55% 0px", threshold: 0.1 },
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [visibleTabs]);

  useEffect(() => {
    if (hasScoreAnalysis || activeTab !== 3) return undefined;
    const animationFrame = window.requestAnimationFrame(() => {
      setActiveTab(0);
      window.history.replaceState(null, "", "#preview-0");
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeTab, hasScoreAnalysis]);

  const handleTabClick = (event: MouseEvent<HTMLAnchorElement>, index: number) => {
    event.preventDefault();
    const section = document.getElementById(`preview-${index}`);
    if (!section) return;
    setActiveTab(index);
    window.history.replaceState(null, "", `#preview-${index}`);
    window.scrollTo({ top: section.getBoundingClientRect().top + window.scrollY - 88, behavior: "smooth" });
  };

  const handleShowAllReviews = () => {
    const reviewSection = document.getElementById("preview-2");
    if (!reviewSection) return;
    setActiveTab(2);
    window.history.replaceState(null, "", "#preview-2");
    window.scrollTo({
      top: reviewSection.getBoundingClientRect().top + window.scrollY - 88,
      behavior: "smooth",
    });
  };

  const reviewSummary = product?.review_summary;
  const highRatingCount = reviewSummary
    ? (reviewSummary.rating_distribution[4] ?? 0) + (reviewSummary.rating_distribution[5] ?? 0)
    : 0;
  const highRatingPercent = reviewSummary && reviewSummary.review_count > 0
    ? Math.round((highRatingCount / reviewSummary.review_count) * 100)
    : null;
  const ingredientEvidenceGroups = product?.evidence.reduce<Array<{ effect: string; items: ProductDetail["evidence"] }>>(
    (groups, evidence) => {
      const effect = evidence.effect_name.trim();
      if (!effect) return groups;
      const existing = groups.find((group) => group.effect === effect);
      if (existing) existing.items.push(evidence);
      else groups.push({ effect, items: [evidence] });
      return groups;
    },
    [],
  ) ?? [];

  if (!productId || loadErrorMessage) {
    return <div className="product-detail-loading-overlay product-detail-loading-error" role="alert"><p>{loadErrorMessage || "상품 상세 정보를 불러오지 못했습니다."}</p></div>;
  }

  if (isLoading || product?.product_id !== productId) {
    return <div className="product-detail-loading-overlay" role="status" aria-label="상품 상세 불러오는 중"><span className="product-detail-loading-spinner" aria-hidden="true" /></div>;
  }

  return (
    <>
      <HomeHeader />
      <main className="naver-preview-page">

      <section className="naver-preview-product-top">
        <div className="naver-preview-gallery">
          <div className="naver-preview-gallery-main">
            {product?.image_urls[0] ? <img src={product.image_urls[0]} alt={product.name} /> : "대표 이미지"}
            {isSoldOut ? <ProductSoldOutOverlay /> : null}
          </div>
        </div>
        <div className="naver-preview-info">
          <h1>{product?.name ?? "상품명이 표시되는 영역입니다. 네이버 상품 상세 제목이 들어갑니다"}</h1>
          {hasProductReviews ? <div className="naver-preview-review-line"><b><StarIcon size={16} /> {product?.review_summary?.average_rating?.toFixed(2) ?? "0.00"}</b> <u>{Math.max(product?.review_summary?.review_count ?? 0, reviewApi.reviews.length).toLocaleString()}건 리뷰</u></div> : null}
          <div className="naver-preview-single-price"><span>판매가</span><strong className={isSoldOut ? "product-price--sold-out" : ""}>{product?.lowest_price?.toLocaleString() ?? "-"}{product?.lowest_price !== null && product?.lowest_price !== undefined ? "원" : ""}</strong></div>
          <div className="naver-preview-info-row naver-preview-brand-row"><b>브랜드</b><a href={`/brand/${encodeURIComponent(product?.brand ?? "믹순")}`}><span>{product?.brand ?? "믹순"} <CaretRightIcon size={14} /></span></a></div>
          {recommendationId && product ? <RecommendationCriteriaMockPanel product={product} summary={recommendationSummary} /> : null}
          <div className="naver-preview-buy-grid"><button className="buy" disabled={isPurchasePending || isSoldOut} type="button" onClick={() => void handlePurchase()}>{isSoldOut ? "일시품절" : isPurchasePending ? "주문서 준비 중" : "구매하기"}</button><button className={product && wishedProductIds.has(product.product_id) ? "is-wished" : ""} type="button" onClick={() => product && void toggleWishlist(product.product_id)}><HeartIcon size={20} />찜하기</button><button data-agent-cart-target disabled={isSoldOut} type="button" onClick={() => void handleAddToCart()}><ShoppingBagIcon size={20} />장바구니</button></div>
        </div>
      </section>

      {product && activeComparison ? (
        <ProductComparisonPanel
          differences={activeComparison.differences}
          errorMessage={comparisonErrorMessage}
          expectedProductCount={activeComparison.compareProductIds.length + 1}
          initiallyPriceOnly
          isLoading={isComparisonLoading}
          onClose={clearComparison}
          products={[product, ...comparisonProducts]}
          recommendationReason={activeComparison.recommendationReason}
          sensitivity={new URLSearchParams(window.location.search).get("sensitivity") ?? undefined}
          skinType={new URLSearchParams(window.location.search).get("skin_type") ?? undefined}
          source={activeComparison.source}
          summary={activeComparison.summary}
        />
      ) : null}

      {!recommendationId && hasProductReviews ? <section className="naver-preview-review-strip"><h2>4점 이상 리뷰가 <strong>{highRatingPercent === null ? "-" : `${highRatingPercent}%`}</strong>예요 ⓘ</h2><div>{reviewSummary ? Object.entries(reviewSummary.rating_distribution).slice(0, 3).map(([rating, count]) => <article key={rating}><b><StarIcon size={14} /> {rating}점</b><p>실제 리뷰 {count.toLocaleString()}건</p></article>) : null}</div><button type="button" onClick={handleShowAllReviews}>리뷰 전체보기 ›</button></section> : null}

      <nav className="naver-preview-tabs">{visibleTabs.map((tab) => <a className={tab.index === activeTab ? "active" : ""} href={`#preview-${tab.index}`} key={tab.label} onClick={(event) => handleTabClick(event, tab.index)}>{tab.label}</a>)}</nav>
      <section className="naver-preview-detail-layout">
        <div className="naver-preview-detail-main">
          <div className="naver-preview-warning">ⓘ 판매자 안내 및 현금 결제, 개인정보 유도 시 결제/입력하지 마시고 즉시 신고해주세요.</div>
          <article id="preview-0"><h2>상세정보</h2>{product?.image_urls?.length ? <><div className={`naver-preview-detail-images${isDetailsExpanded ? " is-expanded" : ""}`}>{product.image_urls.slice(1).map((imageUrl) => <img key={imageUrl} src={imageUrl} alt={`${product.name} 상세 이미지`} />)}</div>{product.image_urls.length > 2 ? <button className="naver-preview-detail-expand" type="button" onClick={() => setIsDetailsExpanded((expanded) => !expanded)}>{isDetailsExpanded ? "상세정보 접기" : "상세정보 펼쳐보기"}{isDetailsExpanded ? <CaretUpIcon size={24} /> : <CaretDownIcon size={24} />}</button> : null}</> : <div className="naver-preview-empty">상세 이미지를 불러오는 중입니다.</div>}</article>
          {brandProducts.length ? <section className="naver-preview-brand-products" aria-label="같은 브랜드 상품"><div className="naver-preview-brand-products-head"><h2>이 브랜드의 다른 상품</h2><a href={`/brand/${encodeURIComponent(product?.brand ?? "")}`}>더보기</a></div><div className="naver-preview-brand-product-grid">{brandProducts.map((item) => { const isWished = wishedProductIds.has(item.product_id); const itemSoldOut = isProductSoldOut(item); return <a className={`naver-preview-brand-product-card${itemSoldOut ? " is-sold-out" : ""}`} href={`/product-detail?id=${encodeURIComponent(item.product_id)}`} key={item.product_id}><div className="naver-preview-brand-product-image">{item.thumbnail_url ? <img src={getProductImageUrl(item.thumbnail_url, "w400")} alt={item.name} /> : <span>이미지 없음</span>}{itemSoldOut ? <ProductSoldOutOverlay /> : null}<button className={`naver-preview-brand-wishlist${isWished ? " is-wished" : ""}`} type="button" aria-label={isWished ? `${item.name} 찜 해제` : `${item.name} 찜하기`} aria-pressed={isWished} disabled={pendingWishlistProductIds.has(item.product_id)} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void toggleWishlist(item.product_id); }}><HeartIcon size={12} /></button></div><strong>{item.brand}</strong><p>{item.name}</p>{item.lowest_price !== null ? <b className={itemSoldOut ? "product-price--sold-out" : ""}>{item.lowest_price.toLocaleString("ko-KR")}원</b> : <b>가격 정보 없음</b>}</a>; })}</div></section> : null}
          <article id="preview-1" className="naver-preview-ingredients"><h2>성분정보</h2><div className="naver-preview-ingredient-block"><h3>전성분</h3><div className="naver-preview-ingredient-copy">{product?.ingredients?.length ? product.ingredients.map((ingredient, index) => <span key={`${ingredient.name}-${index}`}>{ingredient.name}{index < product.ingredients.length - 1 ? ", " : ""}</span>) : <span className="naver-preview-empty-copy">성분 정보를 불러오는 중입니다.</span>}</div>{product?.ingredients?.length ? <p className="naver-preview-ingredient-note">해당 성분명은 식품의약품안전처 기준 및 성분 근거 데이터에 따른 표시입니다.</p> : null}</div>{ingredientEvidenceGroups.length ? <div className="naver-preview-ingredient-block"><h3>성분 근거</h3><div className="naver-preview-evidence-grid">{ingredientEvidenceGroups.map((group) => <button aria-pressed={selectedEvidenceEffect === group.effect} className={`naver-preview-evidence-card${selectedEvidenceEffect === group.effect ? " is-selected" : ""}`} key={group.effect} type="button" onClick={() => setSelectedEvidenceEffect(group.effect)}><div className="naver-preview-evidence-icon" aria-hidden="true"><EvidenceIcon icon={getEvidenceIconKey(group.effect)} /></div><strong>{group.effect}</strong><span>관련 성분 {group.items.length}개</span></button>)}</div>{selectedEvidenceEffect ? <div className="naver-preview-evidence-detail" role="dialog" aria-label={`${selectedEvidenceEffect} 성분 근거`}><div className="naver-preview-evidence-detail-head"><div><span>선택한 근거</span><strong>{selectedEvidenceEffect}</strong></div><button type="button" aria-label="성분 근거 닫기" onClick={() => setSelectedEvidenceEffect(null)}>×</button></div>{ingredientEvidenceGroups.find((group) => group.effect === selectedEvidenceEffect)?.items.map((evidence) => <div className="naver-preview-evidence-detail-item" key={`${evidence.ingredient_name}-${evidence.source_title}`}><strong>{evidence.ingredient_name}</strong><p>{evidence.evidence_text}</p>{evidence.source_title ? <small>출처: {evidence.source_title}</small> : null}</div>)}</div> : null}</div> : null}</article>
          <article id="preview-2" className="naver-preview-reviews"><h2>리뷰</h2>{hasProductReviews ? <div className="naver-preview-review-controls"><select aria-label="리뷰 정렬" value={reviewSort} onChange={(event) => { setReviewCursor(null); setReviewSort(event.target.value as typeof reviewSort); }}><option value="helpful">추천순</option><option value="latest">최신순</option><option value="rating_high">평점 높은순</option><option value="rating_low">평점 낮은순</option></select><select aria-label="리뷰 유형" value={reviewType} onChange={(event) => { setReviewCursor(null); setReviewType(event.target.value as typeof reviewType); }}><option value="ALL">전체 리뷰</option><option value="GENERAL">일반 리뷰</option><option value="MONTH_USE">한달 사용 리뷰</option></select><label><input type="checkbox" checked={reviewRepurchase} onChange={(event) => { setReviewCursor(null); setReviewRepurchase(event.target.checked); }} /> 재구매</label><select aria-label="피부 타입" value={reviewSkinType} onChange={(event) => { setReviewCursor(null); setReviewSkinType(event.target.value); }}><option value="">전체 피부 타입</option>{["건성", "지성", "복합성", "수부지", "중성", "민감성"].map((type) => <option value={type} key={type}>{type}</option>)}</select></div> : null}{reviewApi.isLoading && reviewApi.reviews.length === 0 ? <div className="naver-preview-empty">리뷰를 불러오는 중입니다.</div> : null}{reviewApi.errorMessage ? <div className="naver-preview-empty">리뷰를 불러오지 못했습니다.</div> : null}{!reviewApi.isLoading && !reviewApi.errorMessage && reviewApi.reviews.length === 0 ? <div className="naver-preview-empty">{hasProductReviews ? "조건에 맞는 리뷰가 없습니다." : "리뷰가 없습니다."}</div> : null}<div className="naver-preview-review-list">{reviewApi.reviews.map((review: ProductReview) => <article className="naver-preview-review-card" key={review.id}><div className="naver-preview-review-card-head"><strong>{review.nickname}</strong><span><StarIcon size={14} /> {review.rating.toFixed(1)}</span></div><div className="naver-preview-review-meta">{review.skinType}{review.isRepurchase ? " · 재구매" : ""}{review.usedOverMonth ? " · 한달 사용" : ""} · {review.createdAt}</div><p>{review.body}</p>{review.photos.length ? <div className="naver-preview-review-photos">{review.photos.slice(0, 3).map((photo) => <img src={photo} alt="리뷰 첨부 이미지" key={photo} />)}</div> : null}<small>도움돼요 {review.likeCount}</small></article>)}</div>{reviewApi.hasNext && reviewApi.nextCursor ? <button className="naver-preview-review-more" type="button" onClick={() => setReviewCursor(reviewApi.nextCursor)}>다음 리뷰 보기</button> : null}</article>
          {hasScoreAnalysis ? <section id="preview-3"><ScoreAnalysisPanel product={product} /></section> : null}
          <article id="preview-4" className="naver-preview-qna"><h2>Q&amp;A</h2><details><summary>주의사항</summary><p>상품별 사용법과 성분 정보를 확인한 뒤 피부 상태에 맞게 사용해 주세요.</p></details><details><summary>배송 안내</summary><p>배송 정보와 도착 예정일은 주문 시점과 배송지에 따라 달라질 수 있습니다.</p></details><details><summary>교환·반품 안내</summary><p>교환·반품 조건은 상품 상태와 신청 시점에 따라 달라질 수 있습니다.</p></details></article>
        </div>
        <aside className="naver-preview-sticky-buy"><div className={`naver-preview-quantity${isSoldOut ? " is-sold-out" : ""}`}><b>수량 선택</b><div><button disabled={isSoldOut} type="button" aria-label="수량 줄이기" onClick={() => setQuantity((value) => Math.max(1, value - 1))}><MinusIcon size={20} /></button><span>{quantity}</span><button disabled={isSoldOut} type="button" aria-label="수량 늘리기" onClick={() => setQuantity((value) => value + 1)}><PlusIcon size={20} /></button></div></div><div className="naver-preview-total"><span>총 {quantity}개</span><b>총 금액 <strong className={isSoldOut ? "product-price--sold-out" : ""}>{((product?.lowest_price ?? 0) * quantity).toLocaleString()}원</strong></b></div><div className="naver-preview-buy-grid"><button className="buy" disabled={isPurchasePending || isSoldOut} type="button" onClick={() => void handlePurchase()}>{isSoldOut ? "일시품절" : isPurchasePending ? "주문서 준비 중" : "구매하기"}</button><button className={product && wishedProductIds.has(product.product_id) ? "is-wished" : ""} type="button" onClick={() => product && void toggleWishlist(product.product_id)}><HeartIcon size={20} />찜</button><button data-agent-cart-target disabled={isSoldOut} type="button" onClick={() => void handleAddToCart()}><ShoppingBagIcon size={20} />장바구니</button></div></aside>
      </section>
      <div className="naver-preview-floating"><button type="button" aria-label="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><CaretUpIcon size={22} /></button></div>
      <LoginRequiredDialog onOpenChange={setIsLoginDialogOpen} open={isLoginDialogOpen} redirectTo={`${window.location.pathname}${window.location.search}`} />
      <ActivityToast message={toastMessage} />
      </main>
    </>
  );
}

export default ProductDetailPreviewPage;
