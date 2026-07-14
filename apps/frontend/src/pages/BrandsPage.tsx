import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import Skeleton from "../components/ui/Skeleton";
import { api } from "../lib/api";
import type { BrandListItem } from "../types/product";

const PAGE_SIZE = 24;

function BrandsPage() {
  const navigate = useNavigate();
  const [brands, setBrands] = useState<BrandListItem[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingPage, setIsLoadingPage] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);

  const loadBrands = useCallback(async (page: number, append = false) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setIsLoadingPage(true);
    try {
      const response = await api.getBrands("", page, PAGE_SIZE);
      setBrands((previous) => append ? [...previous, ...response.items.filter((item) => !previous.some((brand) => brand.code === item.code))] : response.items);
      setCurrentPage(page);
      setHasNextPage(response.items.length === PAGE_SIZE);
      setErrorMessage("");
    } catch {
      if (!append) {
        setBrands([]);
        setHasNextPage(false);
        setErrorMessage("브랜드 목록을 불러오지 못했습니다.");
      }
    } finally {
      setIsLoading(false);
      setIsLoadingPage(false);
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    setIsLoading(true);
    void loadBrands(1);
  }, [loadBrands]);

  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel || !hasNextPage || isLoading || errorMessage) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void loadBrands(currentPage + 1, true);
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [currentPage, errorMessage, hasNextPage, isLoading, loadBrands]);

  const visibleBrands = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return brands;
    return brands.filter((brand) => brand.name.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [brands, query]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) navigate(`/catalog-search?q=${encodeURIComponent(query.trim())}`);
  };

  return (
    <div className="category-page brand-index-page">
      <HomeHeader />
      <main className="category-page__main">
        <nav className="category-page__breadcrumb" aria-label="브랜드 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>브랜드</span>
        </nav>
        <h1 className="category-page__title">브랜드</h1>
        <p className="new-products-page__description">원하는 브랜드를 선택해 상품을 찾아보세요.</p>
        <form className="brand-index-page__search" onSubmit={submitSearch}>
          <input
            aria-label="브랜드 검색어"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="브랜드명을 입력하세요"
            value={query}
          />
          <button type="submit">상품 검색</button>
        </form>
        {isLoading ? (
          <div className="brand-index-page__grid" aria-hidden="true">
            {Array.from({ length: 12 }, (_, index) => <Skeleton className="brand-index-page__skeleton" key={index} />)}
          </div>
        ) : errorMessage ? (
          <div className="search-empty">{errorMessage}</div>
        ) : visibleBrands.length > 0 ? (
          <section className="brand-index-page__grid" aria-label="브랜드 목록">
            {visibleBrands.map((brand) => (
              <button
                className="brand-index-page__card"
                key={brand.code}
                onClick={() => navigate(`/catalog-search?q=${encodeURIComponent(brand.name)}`)}
                type="button"
              >
                <strong>{brand.name}</strong>
                <span>{brand.product_count.toLocaleString("ko-KR")}개 상품</span>
              </button>
            ))}
          </section>
        ) : (
          <div className="search-empty">일치하는 브랜드가 없습니다.</div>
        )}
        {!isLoading && !errorMessage && hasNextPage ? (
          <div className="brand-index-page__load-more" ref={loadMoreRef} aria-live="polite">
            {isLoadingPage ? "브랜드를 더 불러오는 중입니다." : ""}
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default BrandsPage;
