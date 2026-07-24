import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import HeartIcon from "../components/ui/HeartIcon";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ActivityToast from "../components/ui/ActivityToast";
import Skeleton from "../components/ui/Skeleton";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { isProductSoldOut } from "../lib/productAvailability";
import { navigateWithinApp } from "../lib/navigation";
import type { CatalogSearchItem, CatalogSearchSort, CatalogSuggestionItem } from "../types/product";

const PAGE_SIZE = 20;
const catalogSorts: CatalogSearchSort[] = ["relevance", "popular", "newest", "price_asc", "price_desc", "rating"];

function CatalogSearchSkeletons() {
  return (
    <>
      {Array.from({ length: PAGE_SIZE }, (_, index) => (
        <article className="catalog-search-result-card product-card search-product-card is-loading" key={index} aria-hidden="true">
          <Skeleton className="catalog-search-result-card__image product-img" />
          <div className="catalog-search-result-card__copy product-info">
            <Skeleton style={{ width: 72, height: 14 }} />
            <Skeleton style={{ width: "78%", height: 19 }} />
            <Skeleton style={{ width: "56%", height: 14 }} />
          </div>
          <div className="catalog-search-result-card__meta search-result-side">
            <Skeleton style={{ width: 70, height: 14 }} />
            <Skeleton style={{ width: 96, height: 22 }} />
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

function CatalogSearchPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const params = useMemo(() => readParams(location.search), [location.search]);
  const [inputValue, setInputValue] = useState(params.query);
  const [items, setItems] = useState<CatalogSearchItem[]>([]);
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);
  const [correctedQuery, setCorrectedQuery] = useState<string | null>(null);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoading, setIsLoading] = useState(Boolean(params.query));
  const [errorMessage, setErrorMessage] = useState("");
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);

  useEffect(() => {
    let isMounted = true;
    if (!user) {
      void Promise.resolve().then(() => {
        if (isMounted) setWishedProductIds(new Set());
      });
      return () => {
        isMounted = false;
      };
    }
    getMyWishlist(50, user?.id)
      .then((wishlist) => {
        if (isMounted) setWishedProductIds(new Set(wishlist.map((item) => item.productId)));
      })
      .catch(() => {
        if (isMounted) setWishedProductIds(new Set());
      });
    return () => {
      isMounted = false;
    };
  }, [user]);

  const toggleWishlist = async (productId: string) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (pendingWishlistProductIds.has(productId)) return;
    const wasWished = wishedProductIds.has(productId);
    setWishedProductIds((current) => {
      const next = new Set(current);
      if (wasWished) next.delete(productId); else next.add(productId);
      return next;
    });
    setPendingWishlistProductIds((current) => new Set(current).add(productId));
    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId, user.id);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId, user.id);
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setWishedProductIds((current) => {
        const next = new Set(current);
        if (wasWished) next.add(productId); else next.delete(productId);
        return next;
      });
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((current) => {
        const next = new Set(current);
        next.delete(productId);
        return next;
      });
    }
  };

  useEffect(() => {
    queueMicrotask(() => setInputValue(params.query));
  }, [params.query]);

  useEffect(() => {
    if (!params.query) {
      queueMicrotask(() => {
        setItems([]);
        setTotalItems(0);
        setTotalPages(0);
        setCorrectedQuery(null);
        setIsLoading(false);
        setErrorMessage("");
      });
      return;
    }

    let isMounted = true;
    queueMicrotask(() => {
      if (isMounted) {
        setIsLoading(true);
        setErrorMessage("");
      }
    });

    api.searchCatalog({ query: params.query, page: params.page, pageSize: PAGE_SIZE, sort: params.sort })
      .then((response) => {
        if (!isMounted) return;
        setItems(response.items);
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

  const openAiSearch = () => {
    const next = new URLSearchParams({ search_mode: "ai" });
    if (inputValue.trim()) next.set("keyword", inputValue.trim());
    navigate(`/search?${next.toString()}`);
  };

  const formatRating = (item: CatalogSearchItem) => {
    if (item.rating === null) return "평점 정보 없음";
    return item.review_count > 0
      ? `평점 ${item.rating.toFixed(1)} · 리뷰 ${item.review_count.toLocaleString("ko-KR")}개`
      : `평점 ${item.rating.toFixed(1)}`;
  };

  return (
    <div className="search-page-shell catalog-search-page">
      <HomeHeader />
      <section className="search-page-top catalog-search-page__top">
        <div className="search-page-top-inner">
          <div className="search-container catalog-search-page__search-container">
            <div aria-label="검색 방식" className="search-mode-tabs" role="tablist">
              <button aria-selected="true" className="active" role="tab" type="button">일반 검색</button>
              <button aria-selected="false" onClick={openAiSearch} role="tab" type="button">AI 추천</button>
            </div>
            <form className="search-combo catalog-search-page__form" onSubmit={handleSubmit}>
              <div className="search-box">
                <div aria-hidden="true" className="search-icon">
                  <svg fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="18">
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.35-4.35" />
                  </svg>
                </div>
                <input
                  aria-label="일반 상품 검색어"
                  autoComplete="off"
                  className="catalog-search-page__input"
                  onChange={(event) => setInputValue(event.target.value)}
                  placeholder="상품명, 브랜드, 성분을 검색하세요"
                  value={inputValue}
                />
                <button className="search-btn" type="submit">
                  <svg aria-hidden="true" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" viewBox="0 0 24 24" width="16">
                    <path d="m22 2-7 20-4-9-9-4z" />
                  </svg>
                  검색
                </button>
              </div>
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
          </div>
        </div>
      </section>

      <main className="main-content search-main-content catalog-search-page__main">
        <div className="search-results-shell ai-search-results catalog-search-page__results">
          <section className="search-results-panel" id="searchResultsSection" aria-live="polite">
            <header className="results-header catalog-search-page__results-header">
              <div>
                <div className="results-query">
                  {params.query ? <><strong>“{params.query}”</strong> 검색 결과</> : "상품을 검색해 보세요"}
                </div>
                <div className="section-subtitle">
                  {isLoading
                    ? "상품 검색 결과를 불러오는 중입니다"
                    : params.query
                      ? `${totalItems.toLocaleString("ko-KR")}개 제품을 찾았습니다`
                      : "상품명, 브랜드, 성분으로 원하는 상품을 찾아보세요"}
                  {correctedQuery ? ` · 추천 검색어: ${correctedQuery}` : ""}
                </div>
              </div>
              {params.query ? (
                <div aria-label="일반 검색 결과 정렬" className="catalog-search-page__sort-tabs" role="tablist">
                  {[
                    ["relevance", "관련도순"],
                    ["popular", "인기순"],
                    ["newest", "신상품순"],
                    ["price_asc", "낮은 가격순"],
                    ["price_desc", "높은 가격순"],
                    ["rating", "평점순"]
                  ].map(([value, label]) => (
                    <button
                      aria-selected={params.sort === value}
                      className={params.sort === value ? "active" : ""}
                      key={value}
                      onClick={() => goToSearch(params.query, 1, value as CatalogSearchSort)}
                      role="tab"
                      type="button"
                    >
                      {label}
                    </button>
                  ))}
                </div>
              ) : null}
            </header>

            <div className="catalog-search-page__result-list" id="searchResultsGrid">
              {isLoading ? (
                <CatalogSearchSkeletons />
              ) : errorMessage ? (
                <div className="search-empty">{errorMessage}</div>
              ) : items.length > 0 ? (
                items.map((product) => {
                  const isSoldOut = isProductSoldOut(product);
                  const isWished = wishedProductIds.has(product.product_id);
                  return (
                    <article
                      className={`catalog-search-result-card product-card product-card-hit search-product-card${isSoldOut ? " is-sold-out" : ""}`}
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
                      <div className="catalog-search-result-card__image-wrap product-img">
                        <ProductThumbnail className="catalog-search-result-card__image product-photo" src={getProductImageUrl(product.thumbnail_url, "w400")} alt={`${product.brand} ${product.name}`} />
                        {isSoldOut ? <ProductSoldOutOverlay /> : null}
                        <button aria-label={isWished ? `${product.name} 찜 해제` : `${product.name} 찜하기`} className={`popular-product-card__heart${isWished ? " is-wished" : ""}`} disabled={pendingWishlistProductIds.has(product.product_id)} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void toggleWishlist(product.product_id); }} type="button"><HeartIcon size={12} /></button>
                      </div>
                      <div className="catalog-search-result-card__copy product-info">
                        <div className="catalog-search-result-card__brand product-brand">{product.brand}</div>
                        <div className="product-name">{product.name}</div>
                      </div>
                      <div className="catalog-search-result-card__meta search-result-side">
                        <span className={`search-result-note${isSoldOut ? " is-sold-out" : ""}`}>{isSoldOut ? "일시품절" : formatRating(product)}</span>
                        <div className="product-price-row">
                          <div>
                            <div>
                              <span className={`sale-price${isSoldOut ? " product-price--sold-out" : ""}`}>{product.lowest_price === null ? "가격 정보 없음" : `${product.lowest_price.toLocaleString("ko-KR")}원`}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })
              ) : params.query ? (
                <div className="search-empty">검색 결과가 없습니다.</div>
              ) : (
                <div className="search-empty">검색어를 입력하면 상품을 찾아드려요.</div>
              )}
            </div>

            {!isLoading && !errorMessage && totalPages > 1 ? (
              <div className="search-pagination catalog-search-page__pagination">
                <button className="page-btn nav" disabled={params.page <= 1} onClick={() => goToSearch(params.query, params.page - 1)} type="button">이전</button>
                <span>{params.page} / {totalPages}</span>
                <button className="page-btn nav" disabled={params.page >= totalPages} onClick={() => goToSearch(params.query, params.page + 1)} type="button">다음</button>
              </div>
            ) : null}
          </section>
        </div>
      </main>
      <LoginRequiredDialog onOpenChange={setIsLoginDialogOpen} open={isLoginDialogOpen} redirectTo={`${window.location.pathname}${window.location.search}`} />
      <ActivityToast message={toastMessage} />
    </div>
  );
}

export default CatalogSearchPage;
