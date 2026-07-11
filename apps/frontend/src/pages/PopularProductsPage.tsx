import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ProductThumbnail from "../components/ProductThumbnail";
import Skeleton from "../components/ui/Skeleton";
import HeartIcon from "../components/ui/HeartIcon";
import ActivityToast from "../components/ui/ActivityToast";
import { useAuth } from "../contexts/useAuth";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";

type PopularItem = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number;
  popularity_score: number;
};

type PopularResponse = { items: PopularItem[]; window_days: number };

const categories = [
  { code: "", label: "전체" },
  { code: "toner", label: "토너", icon: "/category-icons/toner.png" },
  { code: "serum", label: "세럼", icon: "/category-icons/serum.png" },
  { code: "cream", label: "크림", icon: "/category-icons/cream.png" },
  { code: "sunscreen", label: "선크림", icon: "/category-icons/sunscreen.png" }
];

const formatPrice = (value: number) => `${value.toLocaleString("ko-KR")}원`;

const getCurrentMonthWeekLabel = () => {
  const today = new Date();
  const month = today.getMonth() + 1;
  const weekOfMonth = Math.ceil(today.getDate() / 7);
  return `${month}월 ${weekOfMonth}주차`;
};

const getCurrentDateLabel = () => {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}.${month}.${day}.`;
};

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
  const { message: toastMessage, showToast } = useActivityToast();

  useEffect(() => {
    if (!user) {
      setWishedProductIds(new Set());
      return;
    }

    getMyWishlist()
      .then((wishlistItems) => setWishedProductIds(new Set(wishlistItems.map((item) => item.productId))))
      .catch(() => setWishedProductIds(new Set()));
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
      if (wasWished) next.delete(productId);
      else next.add(productId);
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
        if (wasWished) next.add(productId);
        else next.delete(productId);
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
    setIsLoading(items.length === 0);
    setErrorMessage("");
    const query = new URLSearchParams({ limit: "50", window_days: String(windowDays) });
    if (category) query.set("category_code", category);

    fetchWithTimeout(`${API_BASE_URL}/products/popular?${query}`)
      .then((response) => parseJson<PopularResponse>(response))
      .then((data) => {
        if (isMounted) setItems(data.items);
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
          <div className="popular-products-kicker">{getCurrentMonthWeekLabel()}</div>
          <h1>많이 본 BEST</h1>
          <div className="popular-category-tabs" role="tablist" aria-label="상품 카테고리">
            {categories.map((item) => (
              <button
                className={category === item.code ? "is-active" : ""}
                key={item.code || "all"}
                onClick={() => setCategory(item.code)}
                role="tab"
                type="button"
              >
                <span className="popular-category-icon">
                  {item.icon ? (
                    <img
                      alt=""
                      onError={(event) => {
                        event.currentTarget.style.display = "none";
                      }}
                      src={item.icon}
                    />
                  ) : item.code ? "✦" : "ALL"}
                </span>
                <span>{item.label}</span>
              </button>
            ))}
          </div>
          <div className="popular-products-toolbar">
            <div className="popular-period-tabs" role="tablist" aria-label="인기 기간">
              <button className={windowDays === 1 ? "is-active" : ""} onClick={() => setWindowDays(1)} type="button">일간</button>
              <button className={windowDays === 7 ? "is-active" : ""} onClick={() => setWindowDays(7)} type="button">주간</button>
            </div>
            <span className="popular-ranking-info">
              <span>인기 기준</span>
              <button aria-label="인기상품 순위 기준 안내" className="popular-ranking-info__trigger" type="button">
                <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="9.5" />
                  <path d="M12 10.5v5" />
                  <circle cx="12" cy="7.2" r="0.8" fill="currentColor" stroke="none" />
                </svg>
              </button>
              <span className="popular-ranking-info__tooltip" role="tooltip">
                {getCurrentDateLabel()} 기준, {windowDays === 1 ? "오늘" : "최근 7일간"} 고객들의 다양한 상품 활동을 종합해 인기상품 순위를 제공하고 있습니다.
              </span>
            </span>
          </div>
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
              : items.map((item, index) => (
                  <article
                    className="popular-product-card"
                    key={item.product_id}
                    onClick={() => { window.location.href = `/product-detail?id=${encodeURIComponent(item.product_id)}`; }}
                    role="link"
                    tabIndex={0}
                  >
                    <div className="popular-product-card__image-wrap">
                      <span className="popular-product-card__rank">{index + 1}</span>
                      <ProductThumbnail className="popular-product-card__image" src={getProductImageUrl(item.thumbnail_url, "w400")} alt={`${item.brand} ${item.name}`} />
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
                    </div>
                    <div className="popular-product-card__brand">{item.brand}</div>
                    <div className="popular-product-card__name">{item.name}</div>
                    <div className="popular-product-card__price">{formatPrice(item.lowest_price)}</div>
                  </article>
                ))}
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
