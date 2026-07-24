import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductListLoadingState from "../components/ProductListLoadingState";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import HeartIcon from "../components/ui/HeartIcon";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ActivityToast from "../components/ui/ActivityToast";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import type { ProductListingItem } from "../types/product";
import type { ProductCardItem } from "../types/recommendation";

const PAGE_SIZE = 20;

const getBrandName = (value?: string) => {
  if (!value) return "브랜드";
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
};

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

function BrandPage() {
  const { brandName } = useParams();
  const decodedBrandName = getBrandName(brandName);
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const [brandCode, setBrandCode] = useState("");
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
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
        await deleteMyWishlistItem(productId, user.id);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId, user.id);
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

  const loadProducts = useCallback(async (code: string, page: number, append: boolean) => {
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);
    try {
      const response = await api.getProductListing({
        page,
        pageSize: PAGE_SIZE,
        brandCodes: [code],
        sort: "popular"
      });
      const mapped = response.items.map((item, index) =>
        mapListingItemToCard(item, (page - 1) * PAGE_SIZE + index + 1)
      );
      setProducts((current) => append ? [...current, ...mapped] : mapped);
      setNextPage(response.pagination.has_next ? page + 1 : null);
      setErrorMessage("");
    } catch {
      if (!append) setProducts([]);
      setNextPage(null);
      setErrorMessage("브랜드 상품을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    queueMicrotask(() => {
      if (!isMounted) return;
      setProducts([]);
      setNextPage(null);
      setErrorMessage("");
      setIsLoading(true);
    });

    api.getBrands(decodedBrandName, 1, 100)
      .then(async (response) => {
        if (!isMounted) return;
        const normalizedName = decodedBrandName.toLocaleLowerCase("ko-KR");
        const brand = response.items.find((item) => item.name.toLocaleLowerCase("ko-KR") === normalizedName);
        if (!brand) {
          setBrandCode("");
          setErrorMessage("브랜드 정보를 찾을 수 없습니다.");
          setIsLoading(false);
          return;
        }
        setBrandCode(brand.code);
        await loadProducts(brand.code, 1, false);
      })
      .catch(() => {
        if (isMounted) {
          setBrandCode("");
          setProducts([]);
          setErrorMessage("브랜드 정보를 불러오지 못했습니다.");
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [decodedBrandName, loadProducts]);

  const openDetail = (productId: string) => {
    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(productId)}`);
  };

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page new-products-page">
        <div className="popular-products-shell">
        <div className="popular-products-kicker">BRAND</div>
        <h1>{decodedBrandName}</h1>
        <p className="new-products-page__description">{decodedBrandName}의 상품을 확인해 보세요.</p>
        <div className="popular-products-grid new-products-page__grid">
          {isLoading ? (
            <ProductListLoadingState />
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length > 0 ? (
            products.map((product) => {
              const isSoldOut = isProductSoldOut(product);
              const isWished = wishedProductIds.has(product.product_id);
              return <article className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}`} key={product.product_id} onClick={() => openDetail(product.product_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDetail(product.product_id); } }} role="link" tabIndex={0}>
                <div className="popular-product-card__image-wrap">
                  <ProductThumbnail className="popular-product-card__image" src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
                  {isSoldOut ? <ProductSoldOutOverlay /> : null}
                  <button aria-label={isWished ? `${product.name} 찜 해제` : `${product.name} 찜하기`} className={`popular-product-card__heart${isWished ? " is-wished" : ""}`} disabled={pendingWishlistProductIds.has(product.product_id)} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void toggleWishlist(product.product_id); }} type="button"><HeartIcon size={12} /></button>
                </div>
                <div className="popular-product-card__brand">{product.brand}</div>
                <div className="popular-product-card__name">{product.name}</div>
                <div className={`popular-product-card__price${isSoldOut ? " product-price--sold-out" : ""}`}>{product.lowest_price === null ? "가격 정보 없음" : `${product.lowest_price.toLocaleString("ko-KR")}원`}</div>
              </article>;
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
              onClick={() => void loadProducts(brandCode, nextPage, true)}
              type="button"
            >
              {isLoadingMore ? "불러오는 중" : "더보기"}
            </button>
          </div>
        ) : null}
        </div>
      </main>
      <LoginRequiredDialog onOpenChange={setIsLoginDialogOpen} open={isLoginDialogOpen} redirectTo={`${window.location.pathname}${window.location.search}`} />
      <ActivityToast message={toastMessage} />
    </>
  );
}

export default BrandPage;
