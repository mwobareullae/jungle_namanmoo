import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import Skeleton from "../components/ui/Skeleton";
import { api } from "../lib/api";
import type { CatalogSearchItem, CatalogSearchSort, CatalogSuggestionItem } from "../types/product";
import type { ProductCardItem } from "../types/recommendation";

const PAGE_SIZE = 20;
const catalogSorts: CatalogSearchSort[] = ["relevance", "popular", "newest", "price_asc", "price_desc", "rating"];

function CatalogSearchSkeletons() {
  return (
    <>
      {Array.from({ length: PAGE_SIZE }, (_, index) => (
        <article className="product-card product-card-loading" key={index} aria-hidden="true">
          <Skeleton className="product-img" />
          <div className="product-info">
            <Skeleton style={{ width: 72, height: 14, marginBottom: 10 }} />
            <Skeleton style={{ width: "88%", height: 18, marginBottom: 18 }} />
            <Skeleton style={{ width: 96, height: 20 }} />
          </div>
        </article>
      ))}
    </>
  );
}

const readParams = (search: string) => {
  const params = new URLSearchParams(search);
  const page = Number(params.get("page") || 1);
  const requestedSort = params.get("sort") as CatalogSearchSort | null;
  return {
    query: params.get("q")?.trim() ?? "",
    page: Number.isFinite(page) && page > 0 ? Math.floor(page) : 1,
    sort: requestedSort && catalogSorts.includes(requestedSort) ? requestedSort : "relevance"
  };
};

const mapSearchItemToCard = (item: CatalogSearchItem, rank: number): ProductCardItem => ({
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
  risk_flags: [],
  sales_status: item.sales_status,
  in_stock: item.sales_status === "ON_SALE"
});

function CatalogSearchPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => readParams(location.search), [location.search]);
  const [inputValue, setInputValue] = useState(params.query);
  const [items, setItems] = useState<ProductCardItem[]>([]);
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);
  const [correctedQuery, setCorrectedQuery] = useState<string | null>(null);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoading, setIsLoading] = useState(Boolean(params.query));
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => setInputValue(params.query), [params.query]);

  useEffect(() => {
    if (!params.query) {
      setItems([]);
      setTotalItems(0);
      setTotalPages(0);
      setCorrectedQuery(null);
      setIsLoading(false);
      setErrorMessage("");
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setErrorMessage("");

    api.searchCatalog({ query: params.query, page: params.page, pageSize: PAGE_SIZE, sort: params.sort })
      .then((response) => {
        if (!isMounted) return;
        setItems(response.items.map((item, index) => mapSearchItemToCard(item, (response.pagination.page - 1) * PAGE_SIZE + index + 1)));
        setCorrectedQuery(response.corrected_query);
        setTotalItems(response.pagination.total_items);
        setTotalPages(response.pagination.total_pages);
      })
      .catch(() => {
        if (!isMounted) return;
        setItems([]);
        setTotalItems(0);
        setTotalPages(0);
        setCorrectedQuery(null);
        setErrorMessage("검색 결과를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [params.page, params.query, params.sort]);

  useEffect(() => {
    const query = inputValue.trim();
    if (!query || query === params.query) {
      setSuggestions([]);
      return;
    }

    let isMounted = true;
    const timer = window.setTimeout(() => {
      api.getCatalogSuggestions(query)
        .then((response) => {
          if (isMounted) setSuggestions(response.items);
        })
        .catch(() => {
          if (isMounted) setSuggestions([]);
        });
    }, 250);

    return () => {
      isMounted = false;
      window.clearTimeout(timer);
    };
  }, [inputValue, params.query]);

  const goToSearch = (query: string, page = 1, sort = params.sort) => {
    const normalized = query.trim();
    if (!normalized) return;
    const next = new URLSearchParams({ q: normalized, sort });
    if (page > 1) next.set("page", String(page));
    setSuggestions([]);
    navigate(`/catalog-search?${next.toString()}`);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    goToSearch(inputValue);
  };

  const selectSuggestion = (suggestion: CatalogSuggestionItem) => {
    setSuggestions([]);
    if (suggestion.type === "PRODUCT" && suggestion.product_id) {
      navigate(`/product-detail?id=${encodeURIComponent(suggestion.product_id)}`);
      return;
    }
    setInputValue(suggestion.text);
    goToSearch(suggestion.text);
  };

  return (
    <div className="catalog-search-page">
      <HomeHeader />
      <main className="category-page__main">
        <div className="catalog-search-page__head">
          <div>
            <p>일반 상품 검색</p>
            <h1 className="category-page__title">상품명, 브랜드, 카테고리로 찾아보세요</h1>
          </div>
          {params.query ? (
            <select
              aria-label="상품 검색 정렬"
              className="sort-select"
              onChange={(event) => goToSearch(params.query, 1, event.target.value as CatalogSearchSort)}
              value={params.sort}
            >
              <option value="relevance">관련도순</option>
              <option value="popular">인기순</option>
              <option value="newest">신상품순</option>
              <option value="price_asc">가격 낮은순</option>
              <option value="price_desc">가격 높은순</option>
              <option value="rating">평점순</option>
            </select>
          ) : null}
        </div>

        <form className="catalog-search-page__form" onSubmit={handleSubmit}>
          <input
            aria-label="일반 상품 검색어"
            autoComplete="off"
            onChange={(event) => setInputValue(event.target.value)}
            placeholder="상품명이나 브랜드를 입력하세요"
            value={inputValue}
          />
          <button type="submit">검색</button>
          {suggestions.length > 0 ? (
            <div className="catalog-search-page__suggestions" role="listbox">
              {suggestions.map((suggestion) => (
                <button
                  key={`${suggestion.type}-${suggestion.product_id ?? suggestion.text}`}
                  onClick={() => selectSuggestion(suggestion)}
                  role="option"
                  type="button"
                >
                  <span>{suggestion.text}</span>
                  <small>{suggestion.type === "PRODUCT" ? "상품" : suggestion.type === "BRAND" ? "브랜드" : suggestion.type === "CATEGORY" ? "카테고리" : "추천 검색어"}</small>
                </button>
              ))}
            </div>
          ) : null}
        </form>

        {params.query ? (
          <div className="catalog-search-page__summary">
            <strong>‘{params.query}’</strong> 검색 결과 {totalItems.toLocaleString("ko-KR")}개
            {correctedQuery ? <span>추천 검색어: {correctedQuery}</span> : null}
          </div>
        ) : null}

        <div className="product-grid">
          {isLoading ? (
            <CatalogSearchSkeletons />
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : items.length > 0 ? (
            items.map((product) => (
              <HomeProductCard
                eventContext={{
                  sectionId: "catalog_search_results",
                  page: "catalog_search",
                  source: "search_result",
                  clickEvent: "search_result_click",
                  impressionEvent: "search_result_impression"
                }}
                key={product.product_id}
                product={product}
              />
            ))
          ) : params.query ? (
            <div className="search-empty">검색 결과가 없습니다.</div>
          ) : (
            <div className="search-empty">검색어를 입력하면 상품을 찾아드려요.</div>
          )}
        </div>

        {!isLoading && !errorMessage && totalPages > 1 ? (
          <div className="catalog-search-page__pagination">
            <button className="page-btn nav" disabled={params.page <= 1} onClick={() => goToSearch(params.query, params.page - 1)} type="button">이전</button>
            <span>{params.page} / {totalPages}</span>
            <button className="page-btn nav" disabled={params.page >= totalPages} onClick={() => goToSearch(params.query, params.page + 1)} type="button">다음</button>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default CatalogSearchPage;
