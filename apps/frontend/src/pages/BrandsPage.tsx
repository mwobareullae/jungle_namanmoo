import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import Skeleton from "../components/ui/Skeleton";
import { api } from "../lib/api";
import type { BrandListItem } from "../types/product";

function BrandsPage() {
  const navigate = useNavigate();
  const [brands, setBrands] = useState<BrandListItem[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let isMounted = true;
    queueMicrotask(() => {
      if (isMounted) setIsLoading(true);
    });
    const loadAllBrands = async () => {
      const allBrands: BrandListItem[] = [];
      const pageSize = 100;
      for (let page = 1; page <= 20; page += 1) {
        const response = await api.getBrands("", page, pageSize);
        allBrands.push(...response.items);
        if (response.items.length < pageSize) break;
      }
      return allBrands;
    };

    loadAllBrands()
      .then((items) => {
        if (isMounted) setBrands(items);
      })
      .catch(() => {
        if (isMounted) {
          setBrands([]);
          setErrorMessage("브랜드 목록을 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, []);

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
      </main>
    </div>
  );
}

export default BrandsPage;
