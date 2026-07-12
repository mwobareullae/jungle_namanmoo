import { useCallback, useEffect, useMemo, useState } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { trackEvent } from "../lib/appSignals/client";
import { navigateWithinApp } from "../lib/navigation";
import { createFallbackRecommendation } from "../lib/fallbackProducts";
import type {
  HomeSection,
  HomeSectionProduct,
  ProductCardItem,
  RecommendationResponse,
  RecommendationPagination,
  RecommendationProfile
} from "../types/recommendation";
import HomeProductCard from "./HomeProductCard";
import ProductThumbnail from "./ProductThumbnail";
import Skeleton from "./ui/Skeleton";

const createFallbackPagination = (productCount: number): RecommendationPagination => ({
  page: 1,
  page_size: productCount,
  total_items: productCount,
  total_pages: productCount > 0 ? 1 : 0,
  has_next: false,
  has_prev: false
});

const mapHomeProductToCard = (product: HomeSectionProduct, index: number): ProductCardItem => ({
  product_id: product.product_id,
  rank: index + 1,
  total_score: product.display_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: product.thumbnail_url,
  lowest_price: product.lowest_price,
  evidence_tags: product.tags,
  key_ingredients: product.tags,
  risk_flags: []
});

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const openProductDetail = (product: ProductCardItem) => {
  void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`);
};

function SearchLoadingState({ message = "피부 고민을 분석하고 있어요." }: { message?: string }) {
  return (
    <div className="search-loading-state" aria-live="polite">
      <div className="search-loading-banner">
        <div>
          <div className="search-loading-title">{message}</div>
          <div className="search-loading-subtitle">
            필요 효능, 근거 성분, 상품 점수를 순서대로 계산하는 중입니다.
          </div>
        </div>
        <div className="search-loading-meter" aria-hidden="true" />
      </div>
      <ProductSkeletonList count={3} variant="search" />
    </div>
  );
}

function ProductSkeletonList({
  count,
  variant = "home"
}: {
  count: number;
  variant?: "home" | "search";
}) {
  if (variant === "home") {
    return (
      <>
        {Array.from({ length: count }, (_, index) => (
          <article className="product-card product-card-loading" key={index} aria-hidden="true">
            <Skeleton className="product-img" />
            <div className="product-info">
              <Skeleton className="skeleton-line skeleton-brand" />
              <Skeleton className="skeleton-line skeleton-title" />
              <Skeleton className="skeleton-line skeleton-title short" />
              <div className="skeleton-pill-row">
                <Skeleton className="skeleton-pill" />
                <Skeleton className="skeleton-pill" />
              </div>
              <Skeleton className="skeleton-price" />
            </div>
          </article>
        ))}
      </>
    );
  }

  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div className={`product-skeleton ${variant}`} key={index} aria-hidden="true">
          <Skeleton className="product-skeleton-media" />
          <div className="product-skeleton-body">
            <Skeleton className="skeleton-line skeleton-brand" />
            <Skeleton className="skeleton-line skeleton-title" />
            <Skeleton className="skeleton-line skeleton-title short" />
            <div className="skeleton-pill-row">
              <Skeleton className="skeleton-pill" />
              <Skeleton className="skeleton-pill" />
              <Skeleton className="skeleton-pill" />
            </div>
          </div>
          {variant === "search" ? (
            <div className="product-skeleton-side">
              <Skeleton className="skeleton-line skeleton-brand" />
              <Skeleton className="skeleton-price" />
            </div>
          ) : null}
        </div>
      ))}
    </>
  );
}

function HomeSectionLoadingSkeleton() {
  return (
    <div className="home-section-stack home-loading-stack" aria-label="상품 섹션 로딩 중">
      <section className="home-api-section home-ranking-section home-loading-section">
        <HomeLoadingSectionHead />
        <div className="home-ranking-wrap">
          <div className="home-ranking-rail home-ranking-loading-rail">
            {Array.from({ length: 5 }, (_, index) => (
              <article className="home-ranking-card home-ranking-loading-card" key={index} aria-hidden="true">
                <div className="home-ranking-visual">
                  <Skeleton className="home-ranking-media" />
                </div>
                <Skeleton className="home-ranking-brand" />
                <Skeleton className="home-ranking-name" />
                <Skeleton className="home-ranking-price" />
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="home-api-section home-original-section home-personal-section home-loading-section">
        <HomeLoadingSectionHead />
        <div className="product-grid" id="defaultProductGrid">
          <ProductSkeletonList count={8} />
        </div>
      </section>

      <section className="home-api-section home-deal-section home-loading-section">
        <HomeLoadingSectionHead />
        <div className="home-deal-grid">
          {Array.from({ length: 8 }, (_, index) => (
            <article className="home-deal-card home-deal-loading-card" key={index} aria-hidden="true">
              <Skeleton className="home-deal-media" />
              <div className="home-deal-body">
                <Skeleton className="home-ranking-brand" />
                <Skeleton className="home-deal-name" />
                <div className="home-deal-tags">
                  <Skeleton as="span" />
                  <Skeleton as="span" />
                </div>
                <Skeleton className="home-deal-price" />
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function HomeLoadingSectionHead() {
  return (
    <div className="home-section-head home-loading-head" aria-hidden="true">
      <div>
        <Skeleton className="home-section-kicker" />
        <Skeleton className="section-title" />
        <Skeleton className="section-subtitle" />
      </div>
      <Skeleton className="home-see-all" />
    </div>
  );
}

function HomeSectionErrorState() {
  return (
    <section className="home-section-error-state" aria-live="polite">
      <div className="home-section-error-icon" aria-hidden="true">
        !
      </div>
      <h2>상품을 불러오지 못했습니다.</h2>
      <p>잠시 후 새로고침 해주세요.</p>
    </section>
  );
}

function HomeRankingSection({
  products,
  section
}: {
  products: ProductCardItem[];
  section: HomeSection;
  sectionIndex: number;
}) {
  const [pageIndex, setPageIndex] = useState(0);
  const rankingPages = useMemo(() => {
    const pages: ProductCardItem[][] = [];

    for (let index = 0; index < products.length; index += 5) {
      pages.push(products.slice(index, index + 5));
    }

    return pages;
  }, [products]);
  const pageCount = rankingPages.length;
  const lastPageIndex = Math.max(0, pageCount - 1);
  const safePageIndex = Math.min(pageIndex, lastPageIndex);
  const canScrollPrev = safePageIndex > 0;
  const canScrollNext = safePageIndex < lastPageIndex;

  const moveRankingPage = (direction: "prev" | "next") => {
    setPageIndex((currentPage) => {
      if (direction === "prev") {
        return Math.max(0, currentPage - 1);
      }

      return Math.min(lastPageIndex, currentPage + 1);
    });
  };

  return (
    <section className="home-api-section home-ranking-section">
      <div className="home-section-head">
        <div>
          <div className="home-section-kicker">피부 조건 기준 큐레이션</div>
          <div className="section-title">{section.title}</div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
        <a className="home-see-all" href="/products/popular">
          전체보기
          <span aria-hidden="true">→</span>
        </a>
      </div>

      <div className="home-ranking-wrap">
        {products.length > 5 ? (
          <button
            aria-label="이전 인기 제품 보기"
            className="home-ranking-nav home-ranking-nav-prev"
            disabled={!canScrollPrev}
            onClick={() => moveRankingPage("prev")}
            type="button"
          >
            ‹
          </button>
        ) : null}
        <div className="home-ranking-viewport">
          <div
            className="home-ranking-swiper"
            style={{ transform: `translate3d(-${safePageIndex * 100}%, 0, 0)` }}
          >
            {rankingPages.map((pageProducts, pageOffset) => (
              <div className="home-ranking-slide" key={`ranking-page-${pageOffset}`}>
                <div className="home-ranking-rail">
                  {pageProducts.map((product, index) => {
                    const displayRank = pageOffset * 5 + index + 1;

                    return (
                      <article
                        aria-label={`${product.brand} ${product.name} 상세 보기`}
                        className="home-ranking-card"
                        key={product.product_id}
                        onClick={() => openProductDetail(product)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            openProductDetail(product);
                          }
                        }}
                        role="link"
                        tabIndex={0}
                      >
                        <div className="home-ranking-visual">
                          {(product.rank || displayRank) <= 10 ? (
                            <span className="home-rank-badge">
                              {String(product.rank || displayRank).padStart(2, "0")}
                            </span>
                          ) : null}
                          <div className="home-ranking-media">
                            <ProductThumbnail src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
                          </div>
                        </div>
                        <div className="home-ranking-brand">{product.brand}</div>
                        <div className="home-ranking-name">{product.name}</div>
                        <div className="home-ranking-price">{formatPrice(product.lowest_price)}</div>
                      </article>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
        {products.length > 5 ? (
          <button
            aria-label="다음 인기 제품 보기"
            className="home-ranking-nav home-ranking-nav-next"
            disabled={!canScrollNext}
            onClick={() => moveRankingPage("next")}
            type="button"
          >
            ›
          </button>
        ) : null}
      </div>
    </section>
  );
}

function HomeDealSection({
  products,
  section
}: {
  products: ProductCardItem[];
  section: HomeSection;
}) {
  const visibleProducts = products.slice(0, 8);

  return (
    <section className="home-api-section home-deal-section">
      <div className="home-section-head">
        <div>
          <div className="home-section-kicker">맞춤 추천 섹션</div>
          <div className="section-title">{section.title}</div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
        <a className="home-see-all" href="/#defaultSection">
          전체보기
          <span aria-hidden="true">→</span>
        </a>
      </div>
      <div className="home-deal-grid">
        {visibleProducts.length ? (
          visibleProducts.map((product) => {
            return (
              <article
                aria-label={`${product.brand} ${product.name} 상세 보기`}
                className="home-deal-card"
                key={product.product_id}
                onClick={() => openProductDetail(product)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openProductDetail(product);
                  }
                }}
                role="link"
                tabIndex={0}
              >
                <div className="home-deal-media">
                  <ProductThumbnail src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
                </div>
                <div className="home-deal-body">
                  <div className="home-ranking-brand">{product.brand}</div>
                  <div className="home-deal-name">{product.name}</div>
                  <div className="home-deal-tags">
                    {product.key_ingredients.slice(0, 2).map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                  <div className="home-deal-price">{formatPrice(product.lowest_price)}</div>
                </div>
              </article>
            );
          })
        ) : (
          <div className="empty-state">표시할 상품이 없습니다.</div>
        )}
      </div>
      <a className="home-section-more" href="/#defaultSection">
        {section.title} 전체보기
        <span aria-hidden="true">→</span>
      </a>
    </section>
  );
}

function HomeOriginalGridSection({
  products,
  section
}: {
  products: ProductCardItem[];
  section: HomeSection;
}) {
  const visibleProducts = products.slice(0, 8);

  return (
    <section className="home-api-section home-original-section home-personal-section">
      <div className="home-section-head">
        <div>
          <div className="home-section-kicker">피부 조건 기준 추천</div>
          <div className="section-title">{section.title}</div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
        <a className="home-see-all" href="/#defaultSection">
          전체보기
          <span aria-hidden="true">→</span>
        </a>
      </div>
      <div className="product-grid">
        {visibleProducts.length ? (
          visibleProducts.map((product) => <HomeProductCard key={product.product_id} product={product} />)
        ) : (
          <div className="empty-state">표시할 상품이 없습니다.</div>
        )}
      </div>
    </section>
  );
}

type HomeSearchEvent = CustomEvent<{
  query: string;
  profile: RecommendationProfile;
}>;

type HomeMainContentProps = {
  initialQuery?: string;
  initialPage?: number;
  initialRecommendationId?: string;
  initialProfile?: RecommendationProfile;
  mode?: "home" | "search";
  pageSize?: number;
  showDefaultSection?: boolean;
};

function HomeMainContent({
  initialQuery = "",
  initialPage = 1,
  initialRecommendationId,
  initialProfile = {
    skin: "수부지",
    sensitivity: "보통",
    avoidIngredients: []
  },
  mode = "home",
  pageSize = 10,
  showDefaultSection = true
}: HomeMainContentProps) {
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [marketPopularSection, setMarketPopularSection] = useState<HomeSection | null>(null);
  const [forYouSection, setForYouSection] = useState<HomeSection | null>(null);
  const [evidencePicksSection, setEvidencePicksSection] = useState<HomeSection | null>(null);
  const [isHomeSectionLoading, setIsHomeSectionLoading] = useState(showDefaultSection);
  const [homeSectionError, setHomeSectionError] = useState("");
  const [sortType, setSortType] = useState("score");
  const [errorMessage, setErrorMessage] = useState("");

  const updateSearchUrl = useCallback(
    (
      nextQuery: string,
      profile: RecommendationProfile,
      page: number,
      recommendationId?: string
    ) => {
      if (mode !== "search") return;

      const params = new URLSearchParams({
        keyword: nextQuery,
        skin_type: profile.skin,
        sensitivity: profile.sensitivity,
        page_size: String(pageSize)
      });
      if (page > 1) params.set("page", String(page));
      if (recommendationId) params.set("recommendation_id", recommendationId);
      window.history.replaceState(null, "", `/search?${params.toString()}`);
    },
    [mode, pageSize]
  );

  const runSearch = useCallback(
    async (
      nextQuery: string,
      profile: RecommendationProfile,
      page = 1,
      recommendationId?: string
    ) => {
      const trimmedQuery = nextQuery.trim();
      if (!trimmedQuery) return;

      setQuery(trimmedQuery);
      setIsLoading(true);
      setErrorMessage("");
      setRecommendation(null);
      window.dispatchEvent(
        new CustomEvent("home-recommendation-state", {
          detail: { status: "loading", query: trimmedQuery, recommendation: null }
        })
      );
      window.requestAnimationFrame(() => {
        document
          .getElementById("searchResultsSection")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      });

      try {
        const response = recommendationId
          ? await api.getRecommendation(recommendationId, {
              page,
              pageSize
            })
          : await api.createRecommendation(
              {
                concern_text: trimmedQuery,
                skin_type: profile.skin,
                sensitivity: profile.sensitivity,
                avoid_ingredients: profile.avoidIngredients
              },
              {
                page,
                pageSize
              }
            );
        if (response.products.length === 0) {
          trackEvent("search_no_result", {
            recommendationId: response.recommendation_id,
            source: "recommendation_result",
            page: mode === "search" ? "search" : "home",
            metadata: {
              has_concern_text: true,
              concern_length: trimmedQuery.length,
              skin_type: profile.skin,
              sensitivity: profile.sensitivity,
              total_items: response.pagination.total_items,
              unmatched_term_count: response.unmatched_terms.length
            }
          });
        }

        const displayResponse =
          response.products.length > 0
            ? response
            : createFallbackRecommendation(trimmedQuery, profile);
        const nextRecommendationId =
          displayResponse.recommendation_id === "fallback-original-design"
            ? undefined
            : displayResponse.recommendation_id;
        updateSearchUrl(
          trimmedQuery,
          profile,
          displayResponse.pagination.page,
          nextRecommendationId
        );
        setRecommendation(displayResponse);
        window.dispatchEvent(
          new CustomEvent("home-recommendation-state", {
            detail: { status: "success", query: trimmedQuery, recommendation: displayResponse }
          })
        );
      } catch {
        const fallbackResponse = createFallbackRecommendation(trimmedQuery, profile);
        updateSearchUrl(trimmedQuery, profile, fallbackResponse.pagination.page);
        setRecommendation(fallbackResponse);
        setErrorMessage("");
        window.dispatchEvent(
          new CustomEvent("home-recommendation-state", {
            detail: { status: "success", query: trimmedQuery, recommendation: fallbackResponse }
          })
        );
      } finally {
        setIsLoading(false);
      }
    },
    [mode, pageSize, updateSearchUrl]
  );

  useEffect(() => {
    const handleSearchRequest = async (event: Event) => {
      const { query: nextQuery, profile } = (event as HomeSearchEvent).detail;
      runSearch(nextQuery, profile);
    };

    window.addEventListener("home-search-request", handleSearchRequest);
    return () => window.removeEventListener("home-search-request", handleSearchRequest);
  }, [runSearch]);

  useEffect(() => {
    if (initialQuery) {
      queueMicrotask(() => {
        runSearch(initialQuery, initialProfile, initialPage, initialRecommendationId);
      });
    }
  }, [initialPage, initialProfile, initialQuery, initialRecommendationId, runSearch]);

  useEffect(() => {
    if (!showDefaultSection) return;

    let isMounted = true;

    const loadHomeSections = async () => {
      setIsHomeSectionLoading(true);
      setHomeSectionError("");

      try {
        const [marketPopular, forYou, evidencePicks] = await Promise.all([
          api.getMarketPopular({ limit: 10 }),
          api.getForYou({
            skinType: initialProfile.skin,
            sensitivity: initialProfile.sensitivity,
            limit: 10
          }),
          api.getEvidencePicks({ limit: 10 })
        ]);
        if (!isMounted) return;
        setMarketPopularSection(marketPopular);
        setForYouSection(forYou);
        setEvidencePicksSection(evidencePicks);
      } catch {
        if (!isMounted) return;
        setMarketPopularSection(null);
        setForYouSection(null);
        setEvidencePicksSection(null);
        setHomeSectionError("인기 상품을 불러오지 못했습니다.");
      } finally {
        if (isMounted) setIsHomeSectionLoading(false);
      }
    };

    loadHomeSections();

    return () => {
      isMounted = false;
    };
  }, [initialProfile.sensitivity, initialProfile.skin, showDefaultSection]);

  const sortedProducts = useMemo(() => {
    const products = recommendation?.products ?? [];
    return [...products].sort((a, b) => {
      if (sortType === "price-low")
        return (
          (a.lowest_price ?? Number.MAX_SAFE_INTEGER) - (b.lowest_price ?? Number.MAX_SAFE_INTEGER)
        );
      if (sortType === "price-high") return (b.lowest_price ?? -1) - (a.lowest_price ?? -1);
      return b.total_score - a.total_score;
    });
  }, [recommendation, sortType]);

  const products = recommendation?.products ?? [];
  const pagination = recommendation?.pagination ?? createFallbackPagination(products.length);
  const isFallbackResult = recommendation?.recommendation_id === "fallback-original-design";
  const hasSearchState = isLoading || Boolean(recommendation) || Boolean(errorMessage);
  const showPagination = mode === "search" && !isLoading && pagination.total_pages > 1;
  const goToPage = (page: number) => {
    const nextPage = Math.min(Math.max(page, 1), pagination.total_pages || 1);
    if (nextPage === pagination.page) return;
    const currentRecommendationId =
      recommendation?.recommendation_id &&
      recommendation.recommendation_id !== "fallback-original-design"
        ? recommendation.recommendation_id
        : initialRecommendationId;
    runSearch(query || initialQuery, initialProfile, nextPage, currentRecommendationId);
  };

  return (
    <main
      className={`main-content${mode === "search" ? " search-main-content" : ""}`}
      id="mainContent"
    >
      <div id="searchResultsSection" style={{ display: hasSearchState ? "block" : "none" }}>
        <div className="search-results-shell">
          <aside aria-label="검색 조건" className="search-filter-sidebar" data-commerce-only>
            <div className="filter-card">
              <div className="filter-card-title">추천 기준</div>
              <div className="filter-options">
                <div className="filter-option">
                  <span className="filter-dot" />
                  <span id="filterConcern">{query || "피부 고민 분석"}</span>
                </div>
                <div className="filter-option">
                  <span className="filter-dot" />
                  <span id="filterProfile">
                    {initialProfile.skin} · 민감도 {initialProfile.sensitivity}
                  </span>
                </div>
                <div className="filter-note">
                  입력한 고민과 피부 조건을 기준으로 성분 효능 근거를 먼저 비교합니다.
                </div>
              </div>
            </div>
            <div className="filter-card">
              <div className="filter-card-title">결과 기준</div>
              <div className="filter-options">
                <div className="filter-option">
                  <span className="filter-check" />
                  <span>성분 효능 근거</span>
                </div>
                <div className="filter-option">
                  <span className="filter-check" />
                  <span>피부 타입 적합도</span>
                </div>
                <div className="filter-option">
                  <span className="filter-check" />
                  <span>가격 정보</span>
                </div>
                <div className="filter-note">표시되는 값은 추천 API 응답 기준입니다.</div>
              </div>
            </div>
          </aside>

          <section className="search-results-panel">
            <div className="results-header">
              <div>
                <div className="results-query">
                  &quot;<strong id="queryDisplay">{query}</strong>
                  &quot; 검색 결과 ·{" "}
                  <span id="sortDisplay">
                    {sortType === "price-low"
                      ? "가격 낮은순"
                      : sortType === "price-high"
                        ? "가격 높은순"
                        : "매칭 점수순"}
                  </span>
                </div>
                <div className="section-subtitle" style={{ marginTop: 4 }}>
                  {isLoading
                    ? "추천 결과를 불러오는 중입니다"
                    : `${pagination.total_items}개 제품이 피부 고민에 매칭되었습니다`}
                </div>
              </div>
              <select
                aria-label="검색 결과 정렬"
                className="sort-select"
                onChange={(event) => setSortType(event.target.value)}
                value={sortType}
              >
                <option value="score">매칭 점수순</option>
                <option value="price-low">가격 낮은순</option>
                <option value="price-high">가격 높은순</option>
              </select>
            </div>
            <div
              className={`api-result-summary${recommendation?.unmatched_terms.length || isFallbackResult ? " active" : ""}`}
              id="apiResultSummary"
            >
              {isFallbackResult ? (
                <span className="api-summary-chip warning">
                  API 응답 전 원본 샘플 결과를 표시 중입니다
                </span>
              ) : null}
              {recommendation?.unmatched_terms.map((term) => (
                <span className="api-summary-chip warning" key={term}>
                  추가 확인 필요: {term}
                </span>
              ))}
            </div>
            <div className="product-grid" id="searchResultsGrid">
              {isLoading ? (
                <SearchLoadingState />
              ) : errorMessage ? (
                <div className="search-empty">{errorMessage}</div>
              ) : sortedProducts.length ? (
                sortedProducts.map((product) => (
                  <HomeProductCard
                    key={product.product_id}
                    product={product}
                    recommendationId={recommendation?.recommendation_id}
                    showScore
                  />
                ))
              ) : hasSearchState ? (
                <div className="search-empty">
                  검색 결과가 없습니다. 다른 고민으로 다시 검색해 주세요.
                </div>
              ) : null}
            </div>
            <div className="search-pagination" id="searchPagination">
              {showPagination ? (
                <>
                  <button
                    className="page-btn nav"
                    disabled={!pagination.has_prev}
                    onClick={() => goToPage(pagination.page - 1)}
                    type="button"
                  >
                    이전
                  </button>
                  {Array.from({ length: pagination.total_pages }, (_, index) => index + 1).map(
                    (page) => (
                      <button
                        className={`page-btn${page === pagination.page ? " active" : ""}`}
                        key={page}
                        onClick={() => goToPage(page)}
                        type="button"
                      >
                        {page}
                      </button>
                    )
                  )}
                  <button
                    className="page-btn nav"
                    disabled={!pagination.has_next}
                    onClick={() => goToPage(pagination.page + 1)}
                    type="button"
                  >
                    다음
                  </button>
                  <span className="search-page-summary">
                    {(pagination.page - 1) * pagination.page_size + 1}-
                    {Math.min(pagination.page * pagination.page_size, pagination.total_items)} /{" "}
                    {pagination.total_items}개
                  </span>
                </>
              ) : null}
            </div>
            <div
              className="search-related-placeholder"
              data-commerce-only
              style={{
                borderTop: "1.5px solid var(--border)",
                marginTop: 40,
                paddingTop: 40
              }}
            >
              <div className="section-header">
                <div>
                  <div className="sec-eyebrow">함께 구매</div>
                  <div className="section-title">비슷한 고민의 고객이 함께 구매한 제품</div>
                </div>
                <a
                  className="see-all"
                  href="/#defaultSection"
                  onClick={(event) => {
                    event.preventDefault();
                    callOriginal("showToast", "함께 구매 데이터는 준비 중입니다");
                  }}
                >
                  전체보기
                </a>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div
        id="defaultSection"
        style={{ display: showDefaultSection && !hasSearchState ? "block" : "none" }}
      >
        {isHomeSectionLoading ? (
          <HomeSectionLoadingSkeleton />
        ) : homeSectionError ? (
          <HomeSectionErrorState />
        ) : marketPopularSection || forYouSection || evidencePicksSection ? (
          <div className="home-section-stack">
            {marketPopularSection ? (
              <HomeRankingSection
                key={marketPopularSection.section_id}
                products={marketPopularSection.products.map(mapHomeProductToCard)}
                section={marketPopularSection}
                sectionIndex={0}
              />
            ) : null}
            {forYouSection ? (
              <HomeOriginalGridSection
                key={forYouSection.section_id}
                products={forYouSection.products.map(mapHomeProductToCard)}
                section={forYouSection}
              />
            ) : null}
            {evidencePicksSection ? (
              <HomeDealSection
                key={evidencePicksSection.section_id}
                products={evidencePicksSection.products.map(mapHomeProductToCard)}
                section={evidencePicksSection}
              />
            ) : null}
          </div>
        ) : (
          <div className="empty-state">표시할 섹션이 없습니다.</div>
        )}
      </div>
    </main>
  );
}

export default HomeMainContent;
