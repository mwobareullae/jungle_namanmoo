import { useCallback, useEffect, useMemo, useState } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { createFallbackRecommendation } from "../lib/fallbackProducts";
import type {
  HomeSection,
  HomeSectionProduct,
  ProductCardItem,
  RecommendationResponse,
  RecommendationPagination,
  Sensitivity,
  SkinType,
} from "../types/recommendation";
import HomeProductCard from "./HomeProductCard";

const resultTabs = ["전체", "성분 근거", "피부 타입", "가격"];

const createFallbackPagination = (productCount: number): RecommendationPagination => ({
  page: 1,
  page_size: productCount,
  total_items: productCount,
  total_pages: productCount > 0 ? 1 : 0,
  has_next: false,
  has_prev: false,
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
  risk_flags: [],
});

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const hasUsableImageUrl = (url: string | null) =>
  Boolean(url && !/(^|\/)(noimg|no-image|no_image|placeholder)[^/]*\.(gif|png|jpe?g|webp)(\?|$)/i.test(url));

const openProductDetail = (product: ProductCardItem) => {
  window.location.href = `/product-detail?id=${encodeURIComponent(product.product_id)}`;
};

const isPersonalRecommendationSection = (section: HomeSection) => {
  const text = `${section.section_id} ${section.title} ${section.subtitle} ${section.section_type} ${section.algorithm}`;
  return /너에게|당신에게|추천하는 제품|personal|recommend/i.test(text);
};

function SearchLoadingState({ message = "피부 고민을 분석하고 있어요." }: { message?: string }) {
  return (
    <div className="search-loading-state" aria-live="polite">
      <div className="search-loading-banner">
        <div>
          <div className="search-loading-title">{message}</div>
          <div className="search-loading-subtitle">필요 효능, 근거 성분, 상품 점수를 순서대로 계산하는 중입니다.</div>
        </div>
        <div className="search-loading-meter" aria-hidden="true" />
      </div>
      <ProductSkeletonList count={3} variant="search" />
    </div>
  );
}

function ProductSkeletonList({ count, variant = "home" }: { count: number; variant?: "home" | "search" }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div className={`product-skeleton ${variant}`} key={index} aria-hidden="true">
          <div className="product-skeleton-media skeleton-shimmer" />
          <div className="product-skeleton-body">
            <div className="skeleton-line skeleton-brand skeleton-shimmer" />
            <div className="skeleton-line skeleton-title skeleton-shimmer" />
            <div className="skeleton-line skeleton-title short skeleton-shimmer" />
            <div className="skeleton-pill-row">
              <div className="skeleton-pill skeleton-shimmer" />
              <div className="skeleton-pill skeleton-shimmer" />
              <div className="skeleton-pill skeleton-shimmer" />
            </div>
          </div>
          {variant === "search" ? (
            <div className="product-skeleton-side">
              <div className="skeleton-line skeleton-brand skeleton-shimmer" />
              <div className="skeleton-price skeleton-shimmer" />
            </div>
          ) : null}
        </div>
      ))}
    </>
  );
}

function HomeRankingSection({
  products,
  section,
}: {
  products: ProductCardItem[];
  section: HomeSection;
  sectionIndex: number;
}) {
  const visibleProducts = products.slice(0, 5);

  return (
    <section className="home-api-section home-ranking-section">
      <div className="home-section-head">
        <div>
          <div className="home-section-kicker">피부 조건 기준 큐레이션</div>
          <div className="section-title">{section.title}</div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
        <a className="home-see-all" href="/#defaultSection">
          전체보기
          <span aria-hidden="true">→</span>
        </a>
      </div>

      <div className="home-ranking-wrap">
        <div className="home-ranking-rail">
          {visibleProducts.map((product, index) => {
            const hasImage = hasUsableImageUrl(product.thumbnail_url);
            return (
              <article
                aria-label={`${product.brand} ${product.name} 상세 보기`}
                className="home-ranking-card"
                key={product.product_id}
                onClick={() => openProductDetail(product)}
                role="link"
                tabIndex={0}
              >
                <div className="home-ranking-visual">
                  {(product.rank || index + 1) <= 10 ? (
                    <span className="home-rank-badge">{product.rank || index + 1}</span>
                  ) : null}
                  <div className="home-ranking-media">
                    {hasImage ? (
                      <img src={product.thumbnail_url ?? ""} alt={`${product.brand} ${product.name}`} loading="lazy" />
                    ) : (
                      <div className="home-rank-empty">이미지 준비중</div>
                    )}
                  </div>
                </div>
                <div className="home-ranking-brand">{product.brand}</div>
                <div className="home-ranking-name">{product.name}</div>
                <div className="home-ranking-price">{formatPrice(product.lowest_price)}</div>
                <div className="home-ranking-reason">{product.reason_summary}</div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function HomeDealSection({
  products,
  section,
  sectionIndex,
}: {
  products: ProductCardItem[];
  section: HomeSection;
  sectionIndex: number;
}) {
  const visibleProducts = products.slice(0, 8);
  const toneClass = sectionIndex % 2 === 0 ? "tone-soft" : "tone-mint";

  return (
    <section className={`home-api-section home-deal-section ${toneClass}`}>
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
            const hasImage = hasUsableImageUrl(product.thumbnail_url);
            return (
              <article
                aria-label={`${product.brand} ${product.name} 상세 보기`}
                className="home-deal-card"
                key={product.product_id}
                onClick={() => openProductDetail(product)}
                role="link"
                tabIndex={0}
              >
                <div className="home-deal-media">
                  {hasImage ? (
                    <img src={product.thumbnail_url ?? ""} alt={`${product.brand} ${product.name}`} loading="lazy" />
                  ) : (
                    <div className="home-deal-empty">이미지 준비중</div>
                  )}
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
  section,
}: {
  products: ProductCardItem[];
  section: HomeSection;
}) {
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
        {products.length ? (
          products.map((product) => (
            <HomeProductCard key={product.product_id} product={product} />
          ))
        ) : (
          <div className="empty-state">표시할 상품이 없습니다.</div>
        )}
      </div>
    </section>
  );
}

type HomeSearchEvent = CustomEvent<{
  query: string;
  profile: {
    skin: SkinType;
    sensitivity: Sensitivity;
  };
}>;

type HomeMainContentProps = {
  initialQuery?: string;
  initialPage?: number;
  initialRecommendationId?: string;
  initialProfile?: {
    skin: SkinType;
    sensitivity: Sensitivity;
  };
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
  },
  mode = "home",
  pageSize = 10,
  showDefaultSection = true,
}: HomeMainContentProps) {
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [homeSections, setHomeSections] = useState<HomeSection[]>([]);
  const [isHomeSectionLoading, setIsHomeSectionLoading] = useState(showDefaultSection);
  const [homeSectionError, setHomeSectionError] = useState("");
  const [sortType, setSortType] = useState("score");
  const [errorMessage, setErrorMessage] = useState("");

  const updateSearchUrl = useCallback((
    nextQuery: string,
    profile: { skin: SkinType; sensitivity: Sensitivity },
    page: number,
    recommendationId?: string,
  ) => {
    if (mode !== "search") return;

    const params = new URLSearchParams({
      keyword: nextQuery,
      skin_type: profile.skin,
      sensitivity: profile.sensitivity,
      page_size: String(pageSize),
    });
    if (page > 1) params.set("page", String(page));
    if (recommendationId) params.set("recommendation_id", recommendationId);
    window.history.replaceState(null, "", `/search?${params.toString()}`);
  }, [mode, pageSize]);

  const runSearch = useCallback(async (
    nextQuery: string,
    profile: { skin: SkinType; sensitivity: Sensitivity },
    page = 1,
    recommendationId?: string,
  ) => {
    const trimmedQuery = nextQuery.trim();
    if (!trimmedQuery) return;

    setQuery(trimmedQuery);
    setIsLoading(true);
    setErrorMessage("");
    setRecommendation(null);
    window.dispatchEvent(new CustomEvent("home-recommendation-state", {
      detail: { status: "loading", query: trimmedQuery, recommendation: null },
    }));
    window.requestAnimationFrame(() => {
      document.getElementById("searchResultsSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    try {
      const response = recommendationId
        ? await api.getRecommendation(recommendationId, {
          page,
          pageSize,
        })
        : await api.createRecommendation({
          concern_text: trimmedQuery,
          skin_type: profile.skin,
          sensitivity: profile.sensitivity,
          avoid_ingredients: [],
        }, {
          page,
          pageSize,
        });
      const displayResponse =
        response.products.length > 0 ? response : createFallbackRecommendation(trimmedQuery, profile);
      const nextRecommendationId =
        displayResponse.recommendation_id === "fallback-original-design"
          ? undefined
          : displayResponse.recommendation_id;
      updateSearchUrl(trimmedQuery, profile, displayResponse.pagination.page, nextRecommendationId);
      setRecommendation(displayResponse);
      window.dispatchEvent(new CustomEvent("home-recommendation-state", {
        detail: { status: "success", query: trimmedQuery, recommendation: displayResponse },
      }));
    } catch {
      const fallbackResponse = createFallbackRecommendation(trimmedQuery, profile);
      updateSearchUrl(trimmedQuery, profile, fallbackResponse.pagination.page);
      setRecommendation(fallbackResponse);
      setErrorMessage("");
      window.dispatchEvent(new CustomEvent("home-recommendation-state", {
        detail: { status: "success", query: trimmedQuery, recommendation: fallbackResponse },
      }));
    } finally {
      setIsLoading(false);
    }
  }, [pageSize, updateSearchUrl]);

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
        const response = await api.getHomeSections({
          skinType: initialProfile.skin,
          sensitivity: initialProfile.sensitivity,
          limitPerSection: 10,
        });
        if (!isMounted) return;
        setHomeSections(response.sections);
      } catch {
        if (!isMounted) return;
        setHomeSections([]);
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
      if (sortType === "price-low") return (a.lowest_price ?? Number.MAX_SAFE_INTEGER) - (b.lowest_price ?? Number.MAX_SAFE_INTEGER);
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
      recommendation?.recommendation_id && recommendation.recommendation_id !== "fallback-original-design"
        ? recommendation.recommendation_id
        : initialRecommendationId;
    runSearch(query || initialQuery, initialProfile, nextPage, currentRecommendationId);
  };

  return (
    <main className={`main-content${mode === "search" ? " search-main-content" : ""}`} id="mainContent">
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
                  <span id="filterProfile">{initialProfile.skin} · 민감도 {initialProfile.sensitivity}</span>
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
                  &quot; 검색 결과 · <span id="sortDisplay">{sortType === "price-low" ? "가격 낮은순" : sortType === "price-high" ? "가격 높은순" : "매칭 점수순"}</span>
                </div>
                <div className="section-subtitle" style={{ marginTop: 4 }}>
                  {isLoading ? "추천 결과를 불러오는 중입니다" : `${pagination.total_items}개 제품이 피부 고민에 매칭되었습니다`}
                </div>
              </div>
              <select aria-label="검색 결과 정렬" className="sort-select" onChange={(event) => setSortType(event.target.value)} value={sortType}>
                <option value="score">매칭 점수순</option>
                <option value="price-low">가격 낮은순</option>
                <option value="price-high">가격 높은순</option>
              </select>
            </div>
            <div className={`api-result-summary${recommendation?.unmatched_terms.length || isFallbackResult ? " active" : ""}`} id="apiResultSummary">
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
            <div aria-label="결과 유형" className="search-result-tabs" data-commerce-only>
              {resultTabs.map((tab) => (
                <button
                  className={`search-result-tab${tab === "전체" ? " active" : ""}`}
                  key={tab}
                  onClick={tab === "전체" ? undefined : () => callOriginal("showToast", "필터 기능은 준비 중입니다")}
                  type="button"
                >
                  {tab}
                </button>
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
                <div className="search-empty">검색 결과가 없습니다. 다른 고민으로 다시 검색해 주세요.</div>
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
                  {Array.from({ length: pagination.total_pages }, (_, index) => index + 1).map((page) => (
                    <button
                      className={`page-btn${page === pagination.page ? " active" : ""}`}
                      key={page}
                      onClick={() => goToPage(page)}
                      type="button"
                    >
                      {page}
                    </button>
                  ))}
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
                    {Math.min(pagination.page * pagination.page_size, pagination.total_items)} / {pagination.total_items}개
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
                paddingTop: 40,
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

      <div id="defaultSection" style={{ display: showDefaultSection && !hasSearchState ? "block" : "none" }}>
        {isHomeSectionLoading ? (
          <section className="home-api-section">
            <div className="section-header">
              <div>
                <div className="sec-eyebrow">Best Sellers</div>
                <div className="section-title">상품 섹션을 불러오는 중입니다</div>
                <div className="section-subtitle">피부 조건에 맞는 섹션을 준비하고 있습니다</div>
              </div>
            </div>
            <div className="product-grid" id="defaultProductGrid">
              <ProductSkeletonList count={6} />
            </div>
          </section>
        ) : homeSectionError ? (
          <div className="empty-state">{homeSectionError}</div>
        ) : homeSections.length ? (
          <div className="home-section-stack">
            {homeSections.map((section, sectionIndex) => {
              const sectionProducts = section.products.map(mapHomeProductToCard);
              if (isPersonalRecommendationSection(section)) {
                return (
                  <HomeOriginalGridSection
                    key={section.section_id || sectionIndex}
                    products={sectionProducts}
                    section={section}
                  />
                );
              }

              if (sectionIndex === 0) {
                return (
                  <HomeRankingSection
                    key={section.section_id || sectionIndex}
                    products={sectionProducts}
                    section={section}
                    sectionIndex={sectionIndex}
                  />
                );
              }

              return (
                <HomeDealSection
                  key={section.section_id || sectionIndex}
                  products={sectionProducts}
                  section={section}
                  sectionIndex={sectionIndex}
                />
              );
            })}
          </div>
        ) : (
          <div className="empty-state">표시할 섹션이 없습니다.</div>
        )}
      </div>
    </main>
  );
}

export default HomeMainContent;
