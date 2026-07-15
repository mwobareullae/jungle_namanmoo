import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import ProductThumbnail from "../components/ProductThumbnail";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import type { ProductCardItem } from "../types/recommendation";
import type { CategoryListItem, ProductListingItem } from "../types/product";

const PAGE_SIZE = 20;

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

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function CategoryPage() {
  const { groupCode = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedCategoryCode = searchParams.get("category_code") ?? "";
  const [categories, setCategories] = useState<CategoryListItem[]>([]);
  const [isCategoryMetadataLoading, setIsCategoryMetadataLoading] = useState(true);
  const [categoryMetadataError, setCategoryMetadataError] = useState("");
  const categoryItems = useMemo(
    () => categories.filter((category) => category.group === groupCode),
    [categories, groupCode]
  );
  const categoryCodes = useMemo(
    () => categoryItems.map((category) => category.code),
    [categoryItems]
  );
  const categoryTitle = categoryItems[0]?.group_name ?? "카테고리";
  const hasInvalidCategoryCode = Boolean(
    selectedCategoryCode && !categoryCodes.includes(selectedCategoryCode)
  );
  const effectiveCategoryCodes = useMemo(
    () => selectedCategoryCode && !hasInvalidCategoryCode ? [selectedCategoryCode] : categoryCodes,
    [categoryCodes, hasInvalidCategoryCode, selectedCategoryCode]
  );

  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let isMounted = true;

    void api.getCategories()
      .then((response) => {
        if (!isMounted) return;
        setCategories(response.items);
        setCategoryMetadataError("");
      })
      .catch(() => {
        if (isMounted) setCategoryMetadataError("카테고리 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsCategoryMetadataLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

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
    if (isCategoryMetadataLoading) return;

    if (categoryMetadataError) {
      queueMicrotask(() => {
        setProducts([]);
        setNextPage(null);
        setIsLoading(false);
        setErrorMessage(categoryMetadataError);
      });
      return;
    }

    if (!groupCode || categoryCodes.length === 0 || hasInvalidCategoryCode) {
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
      void loadProducts(1, false);
    });
  }, [categoryCodes, categoryMetadataError, groupCode, hasInvalidCategoryCode, isCategoryMetadataLoading, loadProducts]);

  const handleCategoryFilterChange = (categoryCode: string) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    if (categoryCode) nextSearchParams.set("category_code", categoryCode);
    else nextSearchParams.delete("category_code");
    setSearchParams(nextSearchParams);
  };

  return (
    <>
      <HomeHeader />
      <main className="popular-products-page new-products-page category-page category-listing-page">
        <div className="popular-products-shell">
        <div className="popular-products-kicker">CATEGORY</div>
        <h1>{categoryTitle}</h1>
        <p className="new-products-page__description">{categoryTitle} 상품을 확인해 보세요.</p>
        {categoryItems.length > 1 ? (
          <div className="category-page__filters" aria-label={`${categoryTitle} 세부 카테고리`} role="group">
            {[{ code: "", name: "전체" }, ...categoryItems].map((filter) => (
              <button
                aria-pressed={selectedCategoryCode === filter.code}
                className={selectedCategoryCode === filter.code ? "is-active" : ""}
                key={filter.code || "all"}
                onClick={() => handleCategoryFilterChange(filter.code)}
                type="button"
              >
                {filter.name}
              </button>
            ))}
          </div>
        ) : null}
        <div className="popular-products-grid new-products-page__grid category-listing-page__grid">
          {isLoading ? (
            <div className="search-loading-state">불러오는 중...</div>
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length ? (
            products.map((product) => {
              const isSoldOut = isProductSoldOut(product);

              return (
                <article
                  className={`popular-product-card${isSoldOut ? " is-sold-out" : ""}`}
                  data-agent-product-id={product.product_id}
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
                  <div className="popular-product-card__image-wrap">
                    <ProductThumbnail
                      alt={`${product.brand} ${product.name}`}
                      className="popular-product-card__image"
                      src={product.thumbnail_url}
                    />
                    {isSoldOut ? <ProductSoldOutOverlay /> : null}
                  </div>
                  <div className="popular-product-card__brand">{product.brand}</div>
                  <div className="popular-product-card__name">{product.name}</div>
                  <div className={`popular-product-card__price${isSoldOut ? " product-price--sold-out" : ""}`}>
                    {formatPrice(product.lowest_price)}
                  </div>
                </article>
              );
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
              onClick={() => void loadProducts(nextPage, true)}
              type="button"
            >
              {isLoadingMore ? "불러오는 중" : "더보기"}
            </button>
          </div>
        ) : null}
        </div>
      </main>
    </>
  );
}

export default CategoryPage;
