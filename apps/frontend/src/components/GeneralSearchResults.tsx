import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { navigateWithinApp } from "../lib/navigation";
import type { CatalogSearchResponse, CatalogSearchSort } from "../types/recommendation";
import ProductThumbnail from "./ProductThumbnail";

type GeneralSearchResultsProps = {
  initialPage: number;
  initialQuery: string;
  pageSize: number;
};

const sortOptions: Array<{ label: string; value: CatalogSearchSort }> = [
  { value: "relevance", label: "관련도순" },
  { value: "popular", label: "인기순" },
  { value: "newest", label: "신상품순" },
  { value: "price_asc", label: "낮은 가격순" },
  { value: "price_desc", label: "높은 가격순" },
  { value: "rating", label: "평점순" }
];

const formatPrice = (price: number | null) => price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function GeneralSearchResults({ initialPage, initialQuery, pageSize }: GeneralSearchResultsProps) {
  const [response, setResponse] = useState<CatalogSearchResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(Boolean(initialQuery));
  const [page, setPage] = useState(initialPage);
  const [selectedBrands, setSelectedBrands] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [inStock, setInStock] = useState(false);
  const [sort, setSort] = useState<CatalogSearchSort>("relevance");

  useEffect(() => {
    if (!initialQuery.trim()) return;
    let isMounted = true;

    api.getCatalogSearchProducts({
      query: initialQuery,
      page,
      pageSize,
      brands: selectedBrands,
      categories: selectedCategories,
      inStock,
      sort
    }).then((nextResponse) => {
      if (isMounted) {
        setResponse(nextResponse);
        setErrorMessage("");
      }
    }).catch(() => {
      if (isMounted) setErrorMessage("상품 검색을 일시적으로 사용할 수 없습니다.");
    }).finally(() => {
      if (isMounted) setIsLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, [inStock, initialQuery, page, pageSize, selectedBrands, selectedCategories, sort]);

  const toggleFilter = (value: string, setValues: (values: string[]) => void, values: string[]) => {
    setIsLoading(true);
    setErrorMessage("");
    setPage(1);
    setValues(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  };

  const updateSort = (nextSort: CatalogSearchSort) => {
    setIsLoading(true);
    setErrorMessage("");
    setPage(1);
    setSort(nextSort);
  };

  const updateInStock = () => {
    setIsLoading(true);
    setErrorMessage("");
    setPage(1);
    setInStock((current) => !current);
  };

  const pagination = response?.pagination;

  return (
    <main className="general-search-page" id="generalSearchResults">
      <div className="general-search-layout">
        <aside aria-label="검색 필터" className="general-search-filters">
          <div className="general-search-filter-head">
            <strong>필터</strong>
            <button onClick={() => { setIsLoading(true); setErrorMessage(""); setSelectedBrands([]); setSelectedCategories([]); setInStock(false); setPage(1); }} type="button">초기화</button>
          </div>
          <label className="general-search-stock-filter">
            <input checked={inStock} onChange={updateInStock} type="checkbox" />
            <span>판매 가능 상품</span>
          </label>
          <section>
            <h2>카테고리</h2>
            <div className="general-search-filter-list">
              {response?.facets.categories.slice(0, 8).map((facet) => (
                <label key={facet.value}>
                  <input checked={selectedCategories.includes(facet.value)} onChange={() => toggleFilter(facet.value, setSelectedCategories, selectedCategories)} type="checkbox" />
                  <span>{facet.label}</span><em>{facet.count}</em>
                </label>
              ))}
            </div>
          </section>
          <section>
            <h2>브랜드</h2>
            <div className="general-search-filter-list">
              {response?.facets.brands.slice(0, 8).map((facet) => (
                <label key={facet.value}>
                  <input checked={selectedBrands.includes(facet.value)} onChange={() => toggleFilter(facet.value, setSelectedBrands, selectedBrands)} type="checkbox" />
                  <span>{facet.label}</span><em>{facet.count}</em>
                </label>
              ))}
            </div>
          </section>
        </aside>

        <section className="general-search-results" aria-live="polite">
          <header className="general-search-results-head">
            <div>
              <p><strong>&quot;{initialQuery}&quot;</strong> 검색 결과</p>
              <span>{isLoading ? "상품을 찾는 중입니다" : `${pagination?.total_items ?? 0}개 제품`}</span>
            </div>
            <select aria-label="일반 검색 결과 정렬" onChange={(event) => updateSort(event.target.value as CatalogSearchSort)} value={sort}>
              {sortOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </header>

          {errorMessage ? <div className="general-search-empty">{errorMessage}</div> : null}
          {!errorMessage && !isLoading && response?.items.length === 0 ? <div className="general-search-empty">검색 결과가 없습니다. 상품명이나 브랜드를 다시 확인해 주세요.</div> : null}
          <div className="general-search-product-list">
            {response?.items.map((product) => (
              <article
                className="general-search-product"
                key={product.product_id}
                onClick={() => void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`);
                  }
                }}
                role="link"
                tabIndex={0}
              >
                <ProductThumbnail alt={`${product.brand} ${product.name}`} src={product.thumbnail_url} />
                <div className="general-search-product-copy">
                  <span>{product.brand}</span>
                  <h2>{product.name}</h2>
                  <p>{product.category_name}{product.rating ? ` · 평점 ${product.rating.toFixed(1)} (${product.review_count.toLocaleString("ko-KR")})` : ""}</p>
                </div>
                <div className="general-search-product-price">
                  <span className={product.sales_status === "SOLD_OUT" ? "sold-out" : ""}>{product.sales_status === "SOLD_OUT" ? "품절" : "판매 중"}</span>
                  <strong>{formatPrice(product.lowest_price)}</strong>
                </div>
              </article>
            ))}
          </div>

          {pagination && pagination.total_pages > 1 ? <nav aria-label="검색 결과 페이지" className="search-pagination">
            <button className="page-btn nav" disabled={!pagination.has_prev} onClick={() => { setIsLoading(true); setPage(page - 1); }} type="button">이전</button>
            {Array.from({ length: pagination.total_pages }, (_, index) => index + 1).map((nextPage) => <button className={`page-btn${nextPage === page ? " active" : ""}`} key={nextPage} onClick={() => { setIsLoading(true); setPage(nextPage); }} type="button">{nextPage}</button>)}
            <button className="page-btn nav" disabled={!pagination.has_next} onClick={() => { setIsLoading(true); setPage(page + 1); }} type="button">다음</button>
          </nav> : null}
        </section>
      </div>
    </main>
  );
}

export default GeneralSearchResults;
