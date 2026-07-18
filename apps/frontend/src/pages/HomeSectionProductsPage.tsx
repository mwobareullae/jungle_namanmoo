import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import HeartIcon from "../components/ui/HeartIcon";
import ActivityToast from "../components/ui/ActivityToast";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import { trackEvent } from "../lib/appSignals/client";
import { observeProductImpressions } from "../lib/appSignals/impressions";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import type { HomeSectionProduct, ProductCardItem } from "../types/recommendation";

type HomeSectionProductsPageProps = {
  sectionType: "evidence-picks" | "for-you";
};

const pageConfig = {
  "evidence-picks": {
    fallbackTitle: "성분 근거가 좋은 제품",
    kicker: "EVIDENCE PICKS",
    source: "evidence_picks"
  },
  "for-you": {
    fallbackTitle: "나를 위한 맞춤 추천",
    kicker: "PERSONALIZED PICKS",
    source: "for_you"
  }
} as const;

const FOR_YOU_SKIN_TYPES = new Set(["건성", "지성", "복합성", "수부지", "중성"]);

const mapHomeProductToCard = (product: HomeSectionProduct, index: number): ProductCardItem => ({
  product_id: product.product_id,
  rank: index + 1,
  total_score: product.display_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: product.thumbnail_url,
  lowest_price: product.lowest_price,
  evidence_tags: product.tags,
  key_ingredients: product.tags,
  risk_flags: [],
  sales_status: product.sales_status,
  stock_status: product.stock_status,
  available_quantity: product.available_quantity,
  in_stock: product.in_stock
});

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function HomeSectionProductsPage({ sectionType }: HomeSectionProductsPageProps) {
  const config = pageConfig[sectionType];
  const requestedSkinType = new URLSearchParams(window.location.search).get("skin_type");
  const forYouSkinType = requestedSkinType && FOR_YOU_SKIN_TYPES.has(requestedSkinType)
    ? requestedSkinType
    : undefined;
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const [title, setTitle] = useState<string>(config.fallbackTitle);
  const [subtitle, setSubtitle] = useState("");
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);

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

  useEffect(() => {
    let isMounted = true;
    const request = sectionType === "evidence-picks"
      ? api.getEvidencePicks({ limit: 20 })
      : api.getForYou({ skinType: forYouSkinType, limit: 20 });

    queueMicrotask(() => {
      if (isMounted) setIsLoading(true);
    });
    request
      .then((section) => {
        if (!isMounted) return;
        setTitle(section.title || config.fallbackTitle);
        setSubtitle(section.subtitle || "");
        setProducts(section.products.map(mapHomeProductToCard));
        setErrorMessage("");
      })
      .catch(() => {
        if (!isMounted) return;
        setProducts([]);
        setErrorMessage("상품을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [config.fallbackTitle, forYouSkinType, sectionType]);

  useEffect(() => observeProductImpressions(), [products]);

  const toggleWishlist = async (productId: string) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (pendingWishlistProductIds.has(productId)) return;

    const wasWished = wishedProductIds.has(productId);
    setWishedProductIds((current) => {
      const next = new Set(current);
      if (wasWished) next.delete(productId);
      else next.add(productId);
      return next;
    });
    setPendingWishlistProductIds((current) => new Set(current).add(productId));

    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId);
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setWishedProductIds((current) => {
        const next = new Set(current);
        if (wasWished) next.add(productId);
        else next.delete(productId);
        return next;
      });
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((current) => {
        const next = new Set(current);
        next.delete(productId);
        return next;
      });
    }
  };

  const openDetail = (product: ProductCardItem) => {
    trackEvent("search_result_click", {
      productId: product.product_id,
      rank: product.rank,
      source: config.source,
      page: "recommendation_result",
      metadata: { section_id: config.source }
    });
    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`);
  };

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page home-section-products-page">
        <div className="popular-products-shell">
          <div className="popular-products-kicker">{config.kicker}</div>
          <h1>{title}</h1>
          {subtitle ? <p className="new-products-page__description">{subtitle}</p> : null}
          {errorMessage ? <p className="popular-products-error">{errorMessage}</p> : null}
          <section aria-label={`${title} 목록`} className="popular-products-grid">
            {isLoading ? (
              <div className="search-loading-state">상품을 불러오는 중...</div>
            ) : !errorMessage ? (
              products.map((product) => {
                const isSoldOut = isProductSoldOut(product);
                const isWished = wishedProductIds.has(product.product_id);
                return (
                  <article
                    aria-label={`${product.brand} ${product.name} 상세 보기`}
                    className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}`}
                    data-agent-product-id={product.product_id}
                    data-event-page="recommendation_result"
                    data-event-source={config.source}
                    data-impression-event="search_result_impression"
                    data-product-id={product.product_id}
                    data-rank={product.rank}
                    data-section-id={config.source}
                    key={product.product_id}
                    onClick={() => openDetail(product)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDetail(product);
                      }
                    }}
                    role="link"
                    tabIndex={0}
                  >
                    <div className="popular-product-card__image-wrap">
                      <ProductThumbnail
                        alt={`${product.brand} ${product.name}`}
                        className="popular-product-card__image"
                        src={product.thumbnail_url}
                      />
                      {isSoldOut ? <ProductSoldOutOverlay /> : null}
                      <button
                        aria-label={isWished ? `${product.name} 찜 해제` : `${product.name} 찜하기`}
                        className={`popular-product-card__heart${isWished ? " is-wished" : ""}`}
                        disabled={pendingWishlistProductIds.has(product.product_id)}
                        onClick={(event) => {
                          event.stopPropagation();
                          void toggleWishlist(product.product_id);
                        }}
                        type="button"
                      >
                        <HeartIcon size={12} />
                      </button>
                    </div>
                    <div className="popular-product-card__brand">{product.brand}</div>
                    <div className="popular-product-card__name">{product.name}</div>
                    <div className={`popular-product-card__price${isSoldOut ? " product-price--sold-out" : ""}`}>
                      {formatPrice(product.lowest_price)}
                    </div>
                  </article>
                );
              })
            ) : null}
          </section>
          {!isLoading && !errorMessage && products.length === 0 ? (
            <section aria-label={`${title} 없음`} className="popular-products-empty">
              <h2>상품이 없습니다</h2>
              <p>조건에 맞는 상품을 준비하고 있어요.</p>
            </section>
          ) : null}
        </div>
      </main>
      <LoginRequiredDialog
        onOpenChange={setIsLoginDialogOpen}
        open={isLoginDialogOpen}
        redirectTo={`${window.location.pathname}${window.location.search}`}
      />
      <ActivityToast message={toastMessage} />
    </>
  );
}

export default HomeSectionProductsPage;
