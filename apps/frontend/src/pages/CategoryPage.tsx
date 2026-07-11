import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import { api } from "../lib/api";
import { getCategoryCodesByGroupTitle } from "../lib/categoryMapping";
import type { ProductCardItem } from "../types/recommendation";
import type { PopularProductItem } from "../types/product";

const PAGE_SIZE = 20;
const POPULAR_LIMIT = 50;

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

const mapPopularItemToCard = (item: PopularProductItem, index: number): ProductCardItem => ({
  product_id: item.product_id,
  rank: index + 1,
  total_score: item.popularity_score,
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
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let isMounted = true;

    if (categoryCodes.length === 0) {
      Promise.resolve().then(() => {
        if (!isMounted) return;
        setProducts([]);
        setVisibleCount(PAGE_SIZE);
        setIsLoading(false);
      setErrorMessage("존재하지 않는 카테고리입니다.");
      });

      return () => {
        isMounted = false;
      };
    }

    Promise.resolve().then(() => {
      if (!isMounted) return;
      setIsLoading(true);
      setErrorMessage("");
      setVisibleCount(PAGE_SIZE);
    });

    Promise.all(
      categoryCodes.map((categoryCode) => api.getPopularProducts({ categoryCode, limit: POPULAR_LIMIT }))
    )
      .then((responses) => {
        if (!isMounted) return;

        const seenProductIds = new Set<string>();
        const mergedItems: PopularProductItem[] = [];
        responses.forEach((response) => {
          response.items.forEach((item) => {
            if (seenProductIds.has(item.product_id)) return;
            seenProductIds.add(item.product_id);
            mergedItems.push(item);
          });
        });
        mergedItems.sort((a, b) => b.popularity_score - a.popularity_score);

        setProducts(mergedItems.map(mapPopularItemToCard));
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
  }, [categoryCodes]);

  const visibleProducts = products.slice(0, visibleCount);

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
          ) : visibleProducts.length ? (
            visibleProducts.map((product) => <HomeProductCard key={product.product_id} product={product} />)
          ) : (
            <div className="search-empty">표시할 상품이 없습니다.</div>
          )}
        </div>
        {!isLoading && !errorMessage && visibleCount < products.length ? (
          <div className="category-page__load-more">
            <button className="page-btn nav" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)} type="button">
              더보기
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default CategoryPage;
