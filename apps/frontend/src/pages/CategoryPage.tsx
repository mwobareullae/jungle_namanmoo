import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import { api } from "../lib/api";
import { getCategoryCodesByGroupTitle } from "../lib/categoryMapping";
import { getProductImageUrl } from "../lib/imageUrls";
import type { ProductCardItem } from "../types/recommendation";
import type { ProductListingItem } from "../types/product";

const PAGE_SIZE = 20;

const SKINCARE_FILTERS = [
  { label: "전체", code: "" },
  { label: "스킨/토너", code: "toner" },
  { label: "앰플/세럼", code: "serum" },
  { label: "크림", code: "cream" }
] as const;

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
  thumbnail_url: getProductImageUrl(item.thumbnail_url, "w400") || null,
  lowest_price: item.lowest_price,
  evidence_tags: [],
  key_ingredients: [],
  risk_flags: [],
  sales_status: item.sales_status,
  in_stock: item.in_stock
});

function CategoryPage() {
  const { categoryTitle: rawTitle } = useParams();
  const categoryTitle = getCategoryTitle(rawTitle);
  const categoryCodes = useMemo(() => getCategoryCodesByGroupTitle(categoryTitle), [categoryTitle]);
  const [selectedCategoryCode, setSelectedCategoryCode] = useState("");
  const effectiveCategoryCodes = useMemo(
    () => selectedCategoryCode ? [selectedCategoryCode] : categoryCodes,
    [categoryCodes, selectedCategoryCode]
  );

  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  const loadProducts = useCallback(async (page: number, append: boolean) => {
    if (effectiveCategoryCodes.length === 0) return;
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);

    try {
      const response = await api.getProductListing({
        page,
        pageSize: PAGE_SIZE,
        categoryCodes: effectiveCategoryCodes,
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
  }, [effectiveCategoryCodes]);

  useEffect(() => {
    queueMicrotask(() => setSelectedCategoryCode(""));
  }, [categoryTitle]);

  useEffect(() => {
    if (categoryCodes.length === 0) {
      queueMicrotask(() => {
        setProducts([]);
        setNextPage(null);
        setIsLoading(false);
        setErrorMessage("존재하지 않는 카테고리입니다.");
      });
      return;
    }

    queueMicrotask(() => {
      setProducts([]);
      setNextPage(null);
      setErrorMessage("");
    });
    queueMicrotask(() => void loadProducts(1, false));
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
        {categoryTitle === "스킨케어" ? (
          <div className="category-page__filters" aria-label="스킨케어 세부 카테고리" role="group">
            {SKINCARE_FILTERS.map((filter) => (
              <button
                aria-pressed={selectedCategoryCode === filter.code}
                className={selectedCategoryCode === filter.code ? "is-active" : ""}
                key={filter.code || "all"}
                onClick={() => setSelectedCategoryCode(filter.code)}
                type="button"
              >
                {filter.label}
              </button>
            ))}
          </div>
        ) : null}
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
