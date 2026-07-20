import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ProductListLoadingState from "../components/ProductListLoadingState";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import ProductThumbnail from "../components/ProductThumbnail";
import ActivityToast from "../components/ui/ActivityToast";
import HeartIcon from "../components/ui/HeartIcon";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import { useListHistoryRestoration } from "../hooks/useListHistoryRestoration";
import type { ProductCardItem } from "../types/recommendation";
import type { CategoryListItem, ProductListingItem } from "../types/product";

const PAGE_SIZE = 20;

const mapListingItemToCard = (item: ProductListingItem, rank: number): ProductCardItem => ({
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

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function CategoryPage() {
  const { groupCode = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const selectedCategoryCode = searchParams.get("subcategory") ?? "";
  const { restoration, restoreListPosition, saveListRestoration } = useListHistoryRestoration();
  const [categories, setCategories] = useState<CategoryListItem[]>([]);
  const [isCategoryMetadataLoading, setIsCategoryMetadataLoading] = useState(true);
  const [categoryMetadataError, setCategoryMetadataError] = useState("");
  const categoryItems = useMemo(
    () => categories.filter((category) => category.group === groupCode),
    [categories, groupCode]
  );
  const categoryCodes = useMemo(
    () => categoryItems.map((category) => category.code),
    [categoryItems]
  );
  const categoryTitle = categoryItems[0]?.group_name ?? "카테고리";
  const hasInvalidCategoryCode = Boolean(
    selectedCategoryCode && !categoryCodes.includes(selectedCategoryCode)
  );
  const effectiveCategoryCodes = useMemo(
    () => selectedCategoryCode && !hasInvalidCategoryCode ? [selectedCategoryCode] : categoryCodes,
    [categoryCodes, hasInvalidCategoryCode, selectedCategoryCode]
  );

  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadedPageCount, setLoadedPageCount] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");
  const productCardRefs = useRef(new Map<string, HTMLElement>());
  const restoredLocationKeys = useRef(new Set<string>());
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);

  useEffect(() => {
    let isMounted = true;

    if (!user) {
      void Promise.resolve().then(() => {
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
    setWishedProductIds((current) => {
      const next = new Set(current);
      if (wasWished) next.delete(productId); else next.add(productId);
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
        if (wasWished) next.add(productId); else next.delete(productId);
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

  useEffect(() => {
    let isMounted = true;

    void api.getCategories()
      .then((response) => {
        if (!isMounted) return;
        setCategories(response.items);
        setCategoryMetadataError("");
      })
      .catch(() => {
        if (isMounted) setCategoryMetadataError("카테고리 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsCategoryMetadataLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const fetchProductPage = useCallback(async (page: number) => {
    const response = await api.getProductListing({
      page,
      pageSize: PAGE_SIZE,
      categoryCodes: effectiveCategoryCodes,
      sort: "popular"
    });

    return {
      items: response.items.map((item, index) =>
        mapListingItemToCard(item, (page - 1) * PAGE_SIZE + index + 1)
      ),
      response,
    };
  }, [effectiveCategoryCodes]);

  const loadInitialProducts = useCallback(async (pageCount: number) => {
    if (effectiveCategoryCodes.length === 0) return;
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
    } catch {
      setProducts([]);
      setNextPage(null);
      setLoadedPageCount(0);
      setErrorMessage("상품을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [effectiveCategoryCodes.length, fetchProductPage]);

  const loadProducts = useCallback(async (page: number) => {
    setIsLoadingMore(true);

    try {
      const { items, response } = await fetchProductPage(page);
      setProducts((current) => [...current, ...items]);
      setNextPage(response.pagination.has_next ? page + 1 : null);
      setLoadedPageCount((current) => Math.max(current, page));
      setErrorMessage("");
    } catch {
      // 기존 목록은 유지하고, 다음 시도에서 다시 불러온다.
    } finally {
      setIsLoadingMore(false);
    }
  }, [fetchProductPage]);

  useEffect(() => {
    if (isCategoryMetadataLoading) return;

    if (categoryMetadataError) {
      queueMicrotask(() => {
        setProducts([]);
        setNextPage(null);
        setLoadedPageCount(0);
        setIsLoading(false);
        setErrorMessage(categoryMetadataError);
      });
      return;
    }

    if (!groupCode || categoryCodes.length === 0 || hasInvalidCategoryCode) {
      queueMicrotask(() => {
        setProducts([]);
        setNextPage(null);
        setLoadedPageCount(0);
        setIsLoading(false);
        setErrorMessage("존재하지 않는 카테고리입니다.");
      });
      return;
    }

    queueMicrotask(() => {
      setProducts([]);
      setNextPage(null);
      setLoadedPageCount(0);
      setErrorMessage("");
      void loadInitialProducts(restoration?.loadedPageCount ?? 1);
    });
  }, [categoryCodes, categoryMetadataError, groupCode, hasInvalidCategoryCode, isCategoryMetadataLoading, loadInitialProducts, restoration?.loadedPageCount]);

  useEffect(() => {
    if (!restoration || isLoading || loadedPageCount < restoration.loadedPageCount) return;
    if (restoredLocationKeys.current.has(restoration.locationKey)) return;

    restoredLocationKeys.current.add(restoration.locationKey);
    void restoreListPosition(productCardRefs.current.get(restoration.productId) ?? null);
  }, [isLoading, loadedPageCount, restoration, restoreListPosition]);

  const handleCategoryFilterChange = (categoryCode: string) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    if (categoryCode) nextSearchParams.set("subcategory", categoryCode);
    else nextSearchParams.delete("subcategory");
    setSearchParams(nextSearchParams);
  };

  const handleProductNavigation = (productId: string) => {
    saveListRestoration(productId, loadedPageCount);
    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(productId)}`);
  };

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page new-products-page category-page category-listing-page">
        <div className="popular-products-shell">
        <div className="popular-products-kicker">CATEGORY</div>
        <h1>{categoryTitle}</h1>
        <p className="new-products-page__description">{categoryTitle} 상품을 확인해 보세요.</p>
        {categoryItems.length > 1 ? (
          <div className="category-page__filters" aria-label={`${categoryTitle} 세부 카테고리`} role="group">
            {[{ code: "", name: "전체" }, ...categoryItems].map((filter) => (
              <button
                aria-pressed={selectedCategoryCode === filter.code}
                className={selectedCategoryCode === filter.code ? "is-active" : ""}
                key={filter.code || "all"}
                onClick={() => handleCategoryFilterChange(filter.code)}
                type="button"
              >
                {filter.name}
              </button>
            ))}
          </div>
        ) : null}
        <div className="popular-products-grid new-products-page__grid category-listing-page__grid">
          {isLoading ? (
            <ProductListLoadingState />
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length ? (
            products.map((product) => {
              const isSoldOut = isProductSoldOut(product);
              const isWished = wishedProductIds.has(product.product_id);

              return (
                <article
                  className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}`}
                  data-agent-product-id={product.product_id}
                  key={product.product_id}
                  onClick={() => handleProductNavigation(product.product_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      handleProductNavigation(product.product_id);
                    }
                  }}
                  ref={(element) => {
                    if (element) productCardRefs.current.set(product.product_id, element);
                    else productCardRefs.current.delete(product.product_id);
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
                      aria-pressed={isWished}
                      className={`popular-product-card__heart${isWished ? " is-wished" : ""}`}
                      disabled={pendingWishlistProductIds.has(product.product_id)}
                      onClick={(event) => {
                        event.preventDefault();
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
          ) : (
            <div className="search-empty">표시할 상품이 없습니다.</div>
          )}
        </div>
        {!isLoading && !errorMessage && nextPage !== null ? (
          <div className="category-page__load-more">
            <button
              className="page-btn nav"
              disabled={isLoadingMore}
              onClick={() => void loadProducts(nextPage)}
              type="button"
            >
              {isLoadingMore ? "불러오는 중" : "더보기"}
            </button>
          </div>
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

export default CategoryPage;
