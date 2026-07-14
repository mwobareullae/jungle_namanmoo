import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
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
  const [brandCode, setBrandCode] = useState("");
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

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

  return (
    <div className="category-page brand-page">
      <HomeHeader />
      <main className="category-page__main">
        <nav className="category-page__breadcrumb" aria-label="브랜드 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <Link to="/brands">브랜드</Link>
          <span aria-hidden="true">&gt;</span>
          <span>{decodedBrandName}</span>
        </nav>
        <h1 className="category-page__title">{decodedBrandName}</h1>
        <div className="product-grid">
          {isLoading ? (
            <div className="search-loading-state">불러오는 중...</div>
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length > 0 ? (
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
              onClick={() => void loadProducts(brandCode, nextPage, true)}
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

export default BrandPage;
