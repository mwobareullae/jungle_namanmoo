import { useCallback, useEffect, useRef, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import ProductListLoadingState from "../components/ProductListLoadingState";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import HeartIcon from "../components/ui/HeartIcon";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ActivityToast from "../components/ui/ActivityToast";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { useListHistoryRestoration } from "../hooks/useListHistoryRestoration";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import type { ProductListingItem } from "../types/product";
import type { ProductCardItem } from "../types/recommendation";

const PAGE_SIZE = 20;

const mapNewProductToCard = (item: ProductListingItem, rank: number): ProductCardItem => ({
  product_id: item.product_id,
  rank,
  total_score: item.rating ?? 0,
  reason_summary: "",
  brand: item.brand,
  name: item.name,
  thumbnail_url: getProductImageUrl(item.thumbnail_url, "w400") || null,
  lowest_price: item.lowest_price,
  evidence_tags: [],
  key_ingredients: [],
  risk_flags: [],
  sales_status: item.sales_status,
  stock_status: item.stock_status,
  available_quantity: item.available_quantity,
  in_stock: item.in_stock
});

function NewProductsPage() {
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const { restoration, restoreListPosition, saveListRestoration } = useListHistoryRestoration();
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadedPageCount, setLoadedPageCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isRestorationPending, setIsRestorationPending] = useState(() => Boolean(restoration));
  const [isAutoLoadEnabled, setIsAutoLoadEnabled] = useState(() => !restoration);
  const [errorMessage, setErrorMessage] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const productCardRefs = useRef(new Map<string, HTMLElement>());
  const restoredLocationKeys = useRef(new Set<string>());

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
    getMyWishlist(50, user?.id)
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
    if (!user) { setIsLoginDialogOpen(true); return; }
    if (pendingWishlistProductIds.has(productId)) return;
    const wasWished = wishedProductIds.has(productId);
    setWishedProductIds((current) => { const next = new Set(current); if (wasWished) next.delete(productId); else next.add(productId); return next; });
    setPendingWishlistProductIds((current) => new Set(current).add(productId));
    try {
      if (wasWished) { await deleteMyWishlistItem(productId, user.id); showToast(wishlistToastMessage.removed); }
      else { await addMyWishlistItem(productId, user.id); showToast(wishlistToastMessage.added); }
    } catch {
      setWishedProductIds((current) => { const next = new Set(current); if (wasWished) next.add(productId); else next.delete(productId); return next; });
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((current) => { const next = new Set(current); next.delete(productId); return next; });
    }
  };

  const fetchProductPage = useCallback(async (page: number) => {
    const response = await api.getProductListing({ page, pageSize: PAGE_SIZE, sort: "newest" });
    return {
      items: response.items.map((item, index) =>
        mapNewProductToCard(item, (page - 1) * PAGE_SIZE + index + 1)
      ),
      response,
    };
  }, []);

  const loadInitialProducts = useCallback(async (pageCount: number) => {
    setIsLoading(true);

    try {
      const pages = await Promise.all(
        Array.from({ length: pageCount }, (_, index) => fetchProductPage(index + 1))
      );
      const lastPage = pages[pages.length - 1];
      setProducts(pages.flatMap((page) => page.items));
      setNextPage(lastPage?.response.pagination.has_next ? pageCount + 1 : null);
      setLoadedPageCount(pageCount);
      setErrorMessage("");
      setLoadMoreError("");
    } catch {
      setProducts([]);
      setNextPage(null);
      setLoadedPageCount(0);
      setErrorMessage("신상품을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [fetchProductPage]);

  const loadProducts = useCallback(async (page: number) => {
    setIsLoadingMore(true);

    try {
      const { items, response } = await fetchProductPage(page);
      setProducts((current) => [...current, ...items]);
      setNextPage(response.pagination.has_next ? page + 1 : null);
      setLoadedPageCount((current) => Math.max(current, page));
      setLoadMoreError("");
    } catch {
      setLoadMoreError("다음 신상품을 불러오지 못했습니다.");
    } finally {
      setIsLoadingMore(false);
    }
  }, [fetchProductPage]);

  useEffect(() => {
    queueMicrotask(() => void loadInitialProducts(restoration?.loadedPageCount ?? 1));
  }, [loadInitialProducts, restoration?.loadedPageCount]);

  useEffect(() => {
    if (!restoration || restoredLocationKeys.current.has(restoration.locationKey)) return;
    if (!errorMessage && (isLoading || loadedPageCount < restoration.loadedPageCount)) return;

    restoredLocationKeys.current.add(restoration.locationKey);
    void restoreListPosition(productCardRefs.current.get(restoration.productId) ?? null).then(() => {
      queueMicrotask(() => setIsRestorationPending(false));
    });
  }, [errorMessage, isLoading, loadedPageCount, restoration, restoreListPosition]);

  useEffect(() => {
    if (isAutoLoadEnabled) return;

    const enableAutoLoad = () => setIsAutoLoadEnabled(true);
    window.addEventListener("wheel", enableAutoLoad, { once: true, passive: true });
    window.addEventListener("touchmove", enableAutoLoad, { once: true, passive: true });
    window.addEventListener("keydown", enableAutoLoad, { once: true });

    return () => {
      window.removeEventListener("wheel", enableAutoLoad);
      window.removeEventListener("touchmove", enableAutoLoad);
      window.removeEventListener("keydown", enableAutoLoad);
    };
  }, [isAutoLoadEnabled]);

  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel || nextPage === null || isLoading || isLoadingMore || loadMoreError || isRestorationPending || !isAutoLoadEnabled) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void loadProducts(nextPage);
      },
      { rootMargin: "320px 0px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [isAutoLoadEnabled, isLoading, isLoadingMore, isRestorationPending, loadMoreError, loadProducts, nextPage]);

  const handleProductNavigation = (productId: string) => {
    saveListRestoration(productId, loadedPageCount);
    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(productId)}`);
  };

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page new-products-page">
        <div className="popular-products-shell">
        <div className="popular-products-kicker">NEW ARRIVALS</div>
        <h1>신상품</h1>
        <p className="new-products-page__description">최근 출시된 상품부터 확인해 보세요.</p>
        <div className="popular-products-grid new-products-page__grid">
          {isLoading ? (
            <ProductListLoadingState />
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length > 0 ? (
            products.map((product) => {
              const isSoldOut = isProductSoldOut(product);
              return <article className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}`} data-agent-product-id={product.product_id} key={product.product_id} onClick={() => handleProductNavigation(product.product_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); handleProductNavigation(product.product_id); } }} ref={(element) => { if (element) productCardRefs.current.set(product.product_id, element); else productCardRefs.current.delete(product.product_id); }} role="link" tabIndex={0}><div className="popular-product-card__image-wrap"><ProductThumbnail className="popular-product-card__image" src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />{isSoldOut ? <ProductSoldOutOverlay /> : null}<button aria-label={wishedProductIds.has(product.product_id) ? `${product.name} 찜 해제` : `${product.name} 찜하기`} className={`popular-product-card__heart${wishedProductIds.has(product.product_id) ? " is-wished" : ""}`} disabled={pendingWishlistProductIds.has(product.product_id)} onClick={(event) => { event.stopPropagation(); void toggleWishlist(product.product_id); }} type="button"><HeartIcon size={12} /></button></div><div className="popular-product-card__brand">{product.brand}</div><div className="popular-product-card__name">{product.name}</div><div className={`popular-product-card__price${isSoldOut ? " product-price--sold-out" : ""}`}>{product.lowest_price === null ? "가격 정보 없음" : `${product.lowest_price.toLocaleString("ko-KR")}원`}</div></article>;
            })
          ) : (
            <div className="search-empty">표시할 신상품이 없습니다.</div>
          )}
        </div>
        {!isLoading && !errorMessage && nextPage !== null ? (
          <div aria-live="polite" className="new-products-page__load-state" ref={loadMoreRef}>
            {isLoadingMore ? "신상품을 더 불러오는 중..." : null}
            {loadMoreError ? <span>{loadMoreError}</span> : null}
          </div>
        ) : null}
        </div>
      </main>
      <LoginRequiredDialog onOpenChange={setIsLoginDialogOpen} open={isLoginDialogOpen} redirectTo={`${window.location.pathname}${window.location.search}`} />
      <ActivityToast message={toastMessage} />
    </>
  );
}

export default NewProductsPage;
