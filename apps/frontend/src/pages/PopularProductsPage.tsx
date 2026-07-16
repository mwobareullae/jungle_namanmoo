import { useEffect, useRef, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import Skeleton from "../components/ui/Skeleton";
import HeartIcon from "../components/ui/HeartIcon";
import ActivityToast from "../components/ui/ActivityToast";
import PopularProductsHeader from "../components/PopularProductsHeader";
import { useAuth } from "../contexts/useAuth";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { isProductSoldOut } from "../lib/productAvailability";

type PopularItem = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number;
  popularity_score: number;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
  in_stock: boolean;
};

type PopularResponse = { items: PopularItem[]; window_days: number };

const formatPrice = (value: number) => `${value.toLocaleString("ko-KR")}원`;

function PopularProductsPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<PopularItem[]>([]);
  const [category, setCategory] = useState("");
  const [windowDays, setWindowDays] = useState(7);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);
  const [agentMatchedProductIds, setAgentMatchedProductIds] = useState<Set<string>>(() => new Set());
  const [agentAddedProductIds, setAgentAddedProductIds] = useState<Set<string>>(() => new Set());
  const [agentAlreadyWishedProductIds, setAgentAlreadyWishedProductIds] = useState<Set<string>>(() => new Set());
  const agentAnimationTimerIdsRef = useRef<number[]>([]);
  const { message: toastMessage, showToast } = useActivityToast();

  useEffect(() => {
    const readProductIds = (value: unknown) => Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
      : [];
    const applyPayload = (payload: Record<string, unknown>, animate: boolean) => {
      agentAnimationTimerIdsRef.current.forEach((timerId) => window.clearTimeout(timerId));
      agentAnimationTimerIdsRef.current = [];
      const matchedIds = readProductIds(payload.matched_product_ids);
      const addedIds = readProductIds(payload.added_product_ids);
      const alreadyIds = readProductIds(payload.already_wished_product_ids);
      setAgentMatchedProductIds(new Set(matchedIds));
      setAgentAddedProductIds(new Set());
      setAgentAlreadyWishedProductIds(new Set(alreadyIds));
      if (!animate) return;
      addedIds.forEach((productId, index) => {
        const timerId = window.setTimeout(() => {
          setWishedProductIds((previous) => new Set(previous).add(productId));
          setAgentAddedProductIds((previous) => new Set(previous).add(productId));
        }, index * 240);
        agentAnimationTimerIdsRef.current.push(timerId);
      });
      if (addedIds.length > 0) showToast(`${addedIds.length}개 상품을 찜 목록에 반영했어요.`);
    };
    const readStoredPayload = (key: string) => {
      const raw = window.sessionStorage.getItem(key);
      if (!raw) return null;
      window.sessionStorage.removeItem(key);
      try {
        const value: unknown = JSON.parse(raw);
        return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
      } catch {
        return null;
      }
    };
    const preview = readStoredPayload("agent-popular-wishlist-preview");
    if (preview) applyPayload(preview, false);
    const result = readStoredPayload("agent-popular-wishlist-result");
    if (result) applyPayload(result, true);
    const handlePreviewed = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (detail) applyPayload(detail, false);
    };
    const handleUpdated = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (detail) applyPayload(detail, true);
    };
    window.addEventListener("agent-popular-wishlist-previewed", handlePreviewed);
    window.addEventListener("agent-popular-wishlist-updated", handleUpdated);
    return () => {
      agentAnimationTimerIdsRef.current.forEach((timerId) => window.clearTimeout(timerId));
      agentAnimationTimerIdsRef.current = [];
      window.removeEventListener("agent-popular-wishlist-previewed", handlePreviewed);
      window.removeEventListener("agent-popular-wishlist-updated", handleUpdated);
    };
  }, [showToast]);

  useEffect(() => {
    if (!user) {
      void Promise.resolve().then(() => setWishedProductIds(new Set()));
      return;
    }

    getMyWishlist(50, user?.id)
      .then((wishlistItems) => {
        const actualWishedProductIds = new Set(wishlistItems.map((item) => item.productId));
        setWishedProductIds(actualWishedProductIds);
        setAgentAddedProductIds((previous) => new Set(
          [...previous].filter((productId) => actualWishedProductIds.has(productId)),
        ));
        setAgentAlreadyWishedProductIds((previous) => new Set(
          [...previous].filter((productId) => actualWishedProductIds.has(productId)),
        ));
      })
      .catch(() => {
        setWishedProductIds(new Set());
        setAgentAddedProductIds(new Set());
        setAgentAlreadyWishedProductIds(new Set());
      });
  }, [user]);

  const toggleWishlist = async (productId: string) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (pendingWishlistProductIds.has(productId)) return;

    const wasWished = wishedProductIds.has(productId);
    const wasAgentAdded = agentAddedProductIds.has(productId);
    const wasAgentAlreadyWished = agentAlreadyWishedProductIds.has(productId);
    setWishedProductIds((previous) => {
      const next = new Set(previous);
      if (wasWished) next.delete(productId);
      else next.add(productId);
      return next;
    });
    setPendingWishlistProductIds((previous) => new Set(previous).add(productId));
    if (wasWished) {
      setAgentAddedProductIds((previous) => {
        const next = new Set(previous);
        next.delete(productId);
        return next;
      });
      setAgentAlreadyWishedProductIds((previous) => {
        const next = new Set(previous);
        next.delete(productId);
        return next;
      });
    }

    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId, user.id);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId, user.id);
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setWishedProductIds((previous) => {
        const next = new Set(previous);
        if (wasWished) next.add(productId);
        else next.delete(productId);
        return next;
      });
      if (wasAgentAdded) setAgentAddedProductIds((previous) => new Set(previous).add(productId));
      if (wasAgentAlreadyWished) {
        setAgentAlreadyWishedProductIds((previous) => new Set(previous).add(productId));
      }
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((previous) => {
        const next = new Set(previous);
        next.delete(productId);
        return next;
      });
    }
  };

  useEffect(() => {
    let isMounted = true;
    let skeletonShownAt: number | null = null;
    let minimumLoadingTimer: number | null = null;
    const minimumLoadingDuration = 600;
    const skeletonDelay = window.setTimeout(() => {
      if (!isMounted) return;
      skeletonShownAt = Date.now();
      setIsLoading(true);
    }, 150);
    const query = new URLSearchParams({ limit: "50", window_days: String(windowDays) });
    if (category) query.set("category_code", category);

    fetchWithTimeout(`${API_BASE_URL}/products/popular?${query}`)
      .then((response) => parseJson<PopularResponse>(response))
      .then((data) => {
        if (isMounted) {
          setItems(data.items);
          setErrorMessage("");
        }
      })
      .catch(() => {
        if (isMounted) setErrorMessage("인기상품을 불러오지 못했습니다.");
      })
      .finally(() => {
        window.clearTimeout(skeletonDelay);
        if (skeletonShownAt === null) {
          if (isMounted) setIsLoading(false);
          return;
        }
        const remainingDuration = Math.max(0, minimumLoadingDuration - (Date.now() - skeletonShownAt));
        minimumLoadingTimer = window.setTimeout(() => {
          if (isMounted) setIsLoading(false);
        }, remainingDuration);
      });

    return () => {
      isMounted = false;
      window.clearTimeout(skeletonDelay);
      if (minimumLoadingTimer !== null) window.clearTimeout(minimumLoadingTimer);
    };
  }, [category, windowDays]);

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page">
        <section className="popular-products-shell">
          <PopularProductsHeader category={category} onCategoryChange={setCategory} onWindowDaysChange={setWindowDays} windowDays={windowDays} />
          {errorMessage ? <p className="popular-products-error">{errorMessage}</p> : null}
          <section className="popular-products-grid" aria-label="인기상품 목록">
            {isLoading
              ? Array.from({ length: 50 }, (_, index) => (
                  <article className="popular-product-card popular-product-card--skeleton" key={index}>
                    <Skeleton className="popular-product-card__image" />
                    <div className="popular-product-card__skeleton-body">
                      <Skeleton className="popular-product-card__brand" />
                      <Skeleton className="popular-product-card__name" />
                      <Skeleton className="popular-product-card__price" />
                    </div>
                  </article>
                ))
              : items.map((item, index) => {
                  const isSoldOut = isProductSoldOut(item);
                  const isAgentAdded = wishedProductIds.has(item.product_id)
                    && agentAddedProductIds.has(item.product_id);
                  const isAgentAlreadyWished = wishedProductIds.has(item.product_id)
                    && agentAlreadyWishedProductIds.has(item.product_id);
                  return (
                  <article
                    className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}${agentMatchedProductIds.has(item.product_id) ? " is-agent-matched" : ""}${isAgentAdded ? " is-agent-wishlist-added" : ""}${isAgentAlreadyWished ? " is-agent-already-wished" : ""}`}
                    key={item.product_id}
                    data-agent-product-id={item.product_id}
                    onClick={() => { window.location.href = `/product-detail?id=${encodeURIComponent(item.product_id)}`; }}
                    role="link"
                    tabIndex={0}
                  >
                    <div className="popular-product-card__image-wrap">
                      <span className="popular-product-card__rank">{index + 1}</span>
                      <ProductThumbnail className="popular-product-card__image" src={getProductImageUrl(item.thumbnail_url, "w400")} alt={`${item.brand} ${item.name}`} />
                      {isSoldOut ? <ProductSoldOutOverlay /> : null}
                      <button
                        aria-label={wishedProductIds.has(item.product_id) ? `${item.name} 찜 해제` : `${item.name} 찜하기`}
                        className={`popular-product-card__heart${wishedProductIds.has(item.product_id) ? " is-wished" : ""}`}
                        disabled={pendingWishlistProductIds.has(item.product_id)}
                        onClick={(event) => {
                          event.stopPropagation();
                          void toggleWishlist(item.product_id);
                        }}
                        type="button"
                      >
                        <HeartIcon size={12} />
                      </button>
                      {agentMatchedProductIds.has(item.product_id) ? (
                        <span className={`popular-product-card__agent-state${isAgentAdded ? " added" : isAgentAlreadyWished ? " existing" : ""}`}>
                          {isAgentAdded ? "새로 찜했어요" : isAgentAlreadyWished ? "이미 찜한 상품" : "성분 확인"}
                        </span>
                      ) : null}
                    </div>
                    <div className="popular-product-card__brand">{item.brand}</div>
                    <div className="popular-product-card__name">{item.name}</div>
                    <div className={`popular-product-card__price${isSoldOut ? " product-price--sold-out" : ""}`}>{formatPrice(item.lowest_price)}</div>
                  </article>
                  );
                })}
          </section>
          {!isLoading && !errorMessage && items.length === 0 ? (
            <section className="popular-products-empty" aria-label="인기상품 없음">
              <svg aria-hidden="true" className="popular-products-empty__icon" fill="none" viewBox="0 0 24 24">
                <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" />
                <path d="m4 7.5 8 4.5 8-4.5M12 12v9" />
                <path d="m8 5.25 8 4.5" />
              </svg>
              <h2>상품이 없습니다</h2>
              <p>오늘의 인기상품을 준비하고 있어요.</p>
            </section>
          ) : null}
        </section>
        <LoginRequiredDialog
          onOpenChange={setIsLoginDialogOpen}
          open={isLoginDialogOpen}
          redirectTo={`${window.location.pathname}${window.location.search}`}
        />
        <ActivityToast message={toastMessage} />
      </main>
    </>
  );
}

export default PopularProductsPage;
