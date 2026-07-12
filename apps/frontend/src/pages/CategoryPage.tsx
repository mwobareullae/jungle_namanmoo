import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import { api } from "../lib/api";
import { getCategoryCodesByGroupTitle } from "../lib/categoryMapping";
import type { ProductCardItem } from "../types/recommendation";
import type { ProductListingItem } from "../types/product";

const PAGE_SIZE = 20;

const getCategoryTitle = (value?: string) => {
  if (!value) {
    return "";
  }

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
  thumbnail_url: item.thumbnail_url,
  lowest_price: item.lowest_price,
  evidence_tags: [],
  key_ingredients: [],
  risk_flags: []
});

function CategoryPage() {
  const { categoryTitle: rawTitle } = useParams();
  const categoryTitle = getCategoryTitle(rawTitle);
  const categoryCodes = useMemo(() => getCategoryCodesByGroupTitle(categoryTitle), [categoryTitle]);

  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  const loadProducts = useCallback(async (page: number, append: boolean) => {
    if (categoryCodes.length === 0) return;
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);

    try {
      const response = await api.getProductListing({
        page,
        pageSize: PAGE_SIZE,
        categoryCodes,
        sort: "popular"
      });
      const mapped = response.items.map((item, index) =>
        mapListingItemToCard(item, (page - 1) * PAGE_SIZE + index + 1)
      );
      setProducts((current) => (append ? [...current, ...mapped] : mapped));
      setNextPage(response.pagination.has_next ? page + 1 : null);
      setErrorMessage("");
    } catch {
      if (!append) {
        setProducts([]);
        setNextPage(null);
        setErrorMessage("상품을 불러오지 못했습니다.");
      }
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [categoryCodes]);

  useEffect(() => {
    if (categoryCodes.length === 0) {
      setProducts([]);
      setNextPage(null);
      setIsLoading(false);
      setErrorMessage("존재하지 않는 카테고리입니다.");
      return;
    }

    setProducts([]);
    setNextPage(null);
    setErrorMessage("");
    void loadProducts(1, false);
  }, [categoryCodes, loadProducts]);

  return (
    <div className="category-page">
      <HomeHeader />
      <main className="category-page__main">
        <nav className="category-page__breadcrumb" aria-label="카테고리 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>{categoryTitle || "카테고리"}</span>
        </nav>
        <h1 className="category-page__title">{categoryTitle || "카테고리"}</h1>
        <div className="product-grid">
          {isLoading ? (
            <div className="search-loading-state">불러오는 중...</div>
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length ? (
            products.map((product) => <HomeProductCard key={product.product_id} product={product} />)
          ) : (
            <div className="search-empty">표시할 상품이 없습니다.</div>
          )}
        </div>
        {!isLoading && !errorMessage && nextPage !== null ? (
          <div className="category-page__load-more">
            <button
              className="page-btn nav"
              disabled={isLoadingMore}
              onClick={() => void loadProducts(nextPage, true)}
              type="button"
            >
              {isLoadingMore ? "불러오는 중" : "더보기"}
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default CategoryPage;
