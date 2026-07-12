import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
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
  in_stock: item.in_stock
});

function NewProductsPage() {
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  const loadProducts = useCallback(async (page: number, append: boolean) => {
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);

    try {
      const response = await api.getProductListing({ page, pageSize: PAGE_SIZE, sort: "newest" });
      const mapped = response.items.map((item, index) =>
        mapNewProductToCard(item, (page - 1) * PAGE_SIZE + index + 1)
      );
      setProducts((current) => (append ? [...current, ...mapped] : mapped));
      setNextPage(response.pagination.has_next ? page + 1 : null);
      setErrorMessage("");
      setLoadMoreError("");
    } catch {
      if (!append) {
        setProducts([]);
        setNextPage(null);
        setErrorMessage("신상품을 불러오지 못했습니다.");
      } else setLoadMoreError("다음 신상품을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void loadProducts(1, false));
  }, [loadProducts]);

  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel || nextPage === null || isLoading || isLoadingMore || loadMoreError) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void loadProducts(nextPage, true);
      },
      { rootMargin: "320px 0px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [isLoading, isLoadingMore, loadMoreError, loadProducts, nextPage]);

  return (
    <div className="category-page new-products-page">
      <HomeHeader />
      <main className="category-page__main">
        <nav className="category-page__breadcrumb" aria-label="신상품 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>신상품</span>
        </nav>
        <h1 className="category-page__title">신상품</h1>
        <p className="new-products-page__description">최근 출시된 상품부터 확인해 보세요.</p>
        <div className="product-grid">
          {isLoading ? (
            <div className="search-loading-state">불러오는 중...</div>
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length > 0 ? (
            products.map((product) => <HomeProductCard key={product.product_id} product={product} />)
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
      </main>
    </div>
  );
}

export default NewProductsPage;
