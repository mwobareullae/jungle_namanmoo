import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { trackEvent } from "../lib/appSignals/client";
import { observeProductImpressions } from "../lib/appSignals/impressions";
import { navigateWithinApp } from "../lib/navigation";
import type {
  HomeSection,
  HomeSectionProduct,
  ProductCardItem,
  RecommendationResponse,
  RecommendationPagination,
  RecommendationProfile,
  RecommendationRefinementFilters,
  SearchMode
} from "../types/recommendation";
import HomeProductCard, { ProductIngredientTags } from "./HomeProductCard";
import ProductSoldOutOverlay from "./ProductSoldOutOverlay";
import ProductThumbnail from "./ProductThumbnail";
import { isProductSoldOut } from "../lib/productAvailability";
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
  risk_flags: [],
  sales_status: product.sales_status,
  stock_status: product.stock_status,
  available_quantity: product.available_quantity,
  in_stock: product.in_stock
});

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const getHomeSectionHref = (sectionId: string) => {
  if (sectionId === "market_popular") return "/products/popular";
  if (sectionId === "evidence_picks") return "/products/evidence-picks";
  if (sectionId === "for_you") return "/products/for-you";
  return "/catalog-search";
};

const getHomeSectionKicker = (sectionId: string) =>
  sectionId === "for_you" ? "맞춤 추천 섹션" : "성분 근거 기준 큐레이션";

function HomeSectionMoreLink({ href, title }: { href: string; title: string }) {
  return (
    <a className="home-section-more" href={href}>
      {title} 전체보기
      <span aria-hidden="true">→</span>
    </a>
  );
}

type HomeProductEventContext = {
  sectionId: string;
  source: string;
};

const openProductDetail = (product: ProductCardItem, eventContext?: HomeProductEventContext) => {
  if (eventContext) {
    trackEvent("home_product_click", {
      productId: product.product_id,
      rank: product.rank,
      page: "home",
      source: eventContext.source,
      metadata: { section_id: eventContext.sectionId }
    });
  }
  void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`);
};

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

type HomeSectionKey = "marketPopular" | "forYou" | "evidencePicks";

function HomeSectionLoadingSkeleton({ sectionKey }: { sectionKey: HomeSectionKey }) {
  return (
    <div className="home-section-stack home-loading-stack" aria-label="상품 섹션 로딩 중">
      {sectionKey === "marketPopular" ? <section className="home-api-section home-ranking-section home-loading-section">
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
      </section> : null}

      {sectionKey === "forYou" ? <section className="home-api-section home-deal-section tone-mint home-loading-section">
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
      </section> : null}

      {sectionKey === "evidencePicks" ? <section className="home-api-section home-original-section home-personal-section home-loading-section">
        <HomeLoadingSectionHead />
        <div className="product-grid" id="defaultProductGrid">
          <ProductSkeletonList count={8} />
        </div>
      </section> : null}
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
    </div>
  );
}

const DEFAULT_HOME_SECTION_ORDER: HomeSectionKey[] = ["marketPopular", "evidencePicks", "forYou"];

type ForYouFilters = {
  skinType: string;
};

const FOR_YOU_SKIN_TYPES = ["건성", "지성", "복합성", "수부지", "중성"];

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
          <div className="section-subtitle">
            {section.section_id === "for_you"
              ? "피부 프로필과 행동 신호를 함께 본 맞춤 후보"
              : section.subtitle}
          </div>
        </div>
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
                    const isSoldOut = isProductSoldOut(product);

                    return (
                      <article
                        aria-label={`${product.brand} ${product.name} 상세 보기`}
                        className={`home-ranking-card${isSoldOut ? " is-sold-out" : ""}`}
                        data-event-page="home"
                        data-event-source={section.section_id}
                        data-impression-event="home_product_impression"
                        data-product-id={product.product_id}
                        data-rank={product.rank || displayRank}
                        data-section-id={section.section_id}
                        key={product.product_id}
                        onClick={() => openProductDetail(product, { sectionId: section.section_id, source: section.section_id })}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            openProductDetail(product, { sectionId: section.section_id, source: section.section_id });
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
                            {isSoldOut ? <ProductSoldOutOverlay /> : null}
                          </div>
                        </div>
                        <div className="home-ranking-brand">{product.brand}</div>
                        <div className="home-ranking-name">{product.name}</div>
                        <div className={`home-ranking-price${isSoldOut ? " product-price--sold-out" : ""}`}>{formatPrice(product.lowest_price)}</div>
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
      <HomeSectionMoreLink href="/products/popular" title={section.title} />
    </section>
  );
}

function HomeDealSection({
  products,
  section,
  toneMint = false,
  forYouFilters,
  onForYouFilterChange
}: {
  products: ProductCardItem[];
  section: HomeSection;
  toneMint?: boolean;
  forYouFilters?: ForYouFilters;
  onForYouFilterChange?: (key: keyof ForYouFilters, value: string) => void;
}) {
  const visibleProducts = products.slice(0, 8);
  const [isInfoOpen, setIsInfoOpen] = useState(false);
  const [infoPosition, setInfoPosition] = useState({ left: 0, top: 0 });
  const infoButtonRef = useRef<HTMLButtonElement>(null);

  const openInfo = () => {
    const rect = infoButtonRef.current?.getBoundingClientRect();
    if (rect) {
      const maxLeft = Math.max(16, window.innerWidth - 336);
      setInfoPosition({ left: Math.min(rect.left, maxLeft), top: rect.bottom + 10 });
    }
    setIsInfoOpen(true);
  };

  const sourceLabels: Record<string, string> = {
    request_context: "이번 화면에서 선택한 피부 타입·조건",
    manual_skin_profile: "저장된 피부 프로필",
    skin_test_context: "피부 테스트 결과",
    behavior_affinity: "최근 조회·찜·장바구니 행동",
    fallback: "기본 추천 기준"
  };
  const personalizationSources = section.personalization_sources
    .map((source) => sourceLabels[source] ?? source)
    .filter((source, index, sources) => sources.indexOf(source) === index);
  const recommendationSources = [
    ...personalizationSources,
    "성분·효능 근거",
    "가격 및 인기 지표"
  ].filter((source, index, sources) => sources.indexOf(source) === index);

  return (
    <section className={`home-api-section home-deal-section${toneMint ? " tone-mint" : ""}${isInfoOpen ? " is-info-open" : ""}`}>
      <div className="home-section-head">
        <div>
          <div className="home-section-kicker">{getHomeSectionKicker(section.section_id)}</div>
          <div className="home-section-title-row">
            <div className="section-title">{section.title}</div>
            {section.section_id === "for_you" ? (
              <div
                className="home-recommendation-info"
                onMouseEnter={openInfo}
              >
                <button
                  aria-expanded={isInfoOpen}
                  aria-label="너를 위한 추천 기준 보기"
                  className="home-recommendation-info-button"
                  onClick={() => (isInfoOpen ? setIsInfoOpen(false) : openInfo())}
                  onFocus={openInfo}
                  ref={infoButtonRef}
                  type="button"
                >
                  i
                </button>
                {isInfoOpen ? createPortal(
                  <div
                    className="home-recommendation-info-popover"
                    role="dialog"
                    aria-label="너를 위한 추천 기준"
                    onMouseLeave={() => setIsInfoOpen(false)}
                    style={{ left: infoPosition.left, top: infoPosition.top }}
                  >
                    <div className="home-recommendation-info-head">
                      <strong>너를 위한 추천 기준</strong>
                      <button
                        aria-label="추천 기준 닫기"
                        className="home-recommendation-info-close"
                        onClick={() => setIsInfoOpen(false)}
                        type="button"
                      >
                        ×
                      </button>
                    </div>
                    <p>
                      {section.skin_type ?? "현재 선택한 피부 타입"}
                      {section.sensitivity ? ` · 민감도 ${section.sensitivity}` : ""}
                    </p>
                    <span>추천에 참고한 정보</span>
                    <ul>
                      {recommendationSources.map((source) => (
                        <li key={source}>{source}</li>
                      ))}
                    </ul>
                  </div>,
                  document.body
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
      </div>
      {section.section_id === "for_you" && forYouFilters && onForYouFilterChange ? (
        <div className="home-for-you-filters" aria-label="맞춤 추천 조건">
          <div className="home-for-you-filter-group">
            <div className="home-for-you-chips" role="group" aria-label="피부 타입 선택">
              {FOR_YOU_SKIN_TYPES.map((value) => (
                <button
                  className={forYouFilters.skinType === value ? "active" : ""}
                  key={value}
                  onClick={() => onForYouFilterChange("skinType", value)}
                  type="button"
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      <div className="home-deal-grid">
        {visibleProducts.length ? (
          visibleProducts.map((product) => {
            const isSoldOut = isProductSoldOut(product);
            return (
              <article
                aria-label={`${product.brand} ${product.name} 상세 보기`}
                className={`home-deal-card${isSoldOut ? " is-sold-out" : ""}`}
                data-event-page="home"
                data-event-source={section.section_id}
                data-impression-event="home_product_impression"
                data-product-id={product.product_id}
                data-rank={product.rank}
                data-section-id={section.section_id}
                key={product.product_id}
                onClick={() => openProductDetail(product, { sectionId: section.section_id, source: section.section_id })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openProductDetail(product, { sectionId: section.section_id, source: section.section_id });
                  }
                }}
                role="link"
                tabIndex={0}
              >
                <div className="home-deal-media">
                  <ProductThumbnail src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
                  {isSoldOut ? <ProductSoldOutOverlay /> : null}
                </div>
                <div className="home-deal-body">
                  <div className="home-ranking-brand">{product.brand}</div>
                  <div className="home-deal-name">{product.name}</div>
                  <ProductIngredientTags className="home-deal-tags" tags={product.key_ingredients.slice(0, 2)} />
                  <div className={`home-deal-price${isSoldOut ? " product-price--sold-out" : ""}`}>{formatPrice(product.lowest_price)}</div>
                </div>
              </article>
            );
          })
        ) : (
          <div className="empty-state">표시할 상품이 없습니다.</div>
        )}
      </div>
      <HomeSectionMoreLink href={getHomeSectionHref(section.section_id)} title={section.title} />
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
          <div className="home-section-kicker">{getHomeSectionKicker(section.section_id)}</div>
          <div className="section-title">{section.title}</div>
          <div className="section-subtitle">{section.subtitle}</div>
        </div>
      </div>
      <div className="product-grid">
        {visibleProducts.length ? (
          visibleProducts.map((product) => (
            <HomeProductCard
              eventContext={{
                sectionId: section.section_id,
                page: "home",
                source: section.section_id,
                clickEvent: "home_product_click",
                impressionEvent: "home_product_impression"
              }}
              key={product.product_id}
              product={product}
            />
          ))
        ) : (
          <div className="empty-state">표시할 상품이 없습니다.</div>
        )}
      </div>
      <HomeSectionMoreLink href={getHomeSectionHref(section.section_id)} title={section.title} />
    </section>
  );
}

type HomeSearchEvent = CustomEvent<{
  query: string;
  profile: RecommendationProfile;
  recommendationId?: string;
  refinementFilters?: RecommendationRefinementFilters;
}>;

type AgentRefinedProductsEvent = CustomEvent<{
  products?: Array<Record<string, unknown>>;
  filters?: Record<string, unknown>;
}>;

type HomeMainContentProps = {
  deferInitialSearch?: boolean;
  initialQuery?: string;
  initialPage?: number;
  initialRecommendationId?: string;
  initialRefinementFilters?: RecommendationRefinementFilters;
  initialSearchMode?: SearchMode;
  initialProfile?: RecommendationProfile;
  mode?: "home" | "search";
  pageSize?: number;
  showDefaultSection?: boolean;
  showForYouSkinTypeFilters?: boolean;
};

function HomeMainContent({
  deferInitialSearch = false,
  initialQuery = "",
  initialPage = 1,
  initialRecommendationId,
  initialRefinementFilters,
  initialSearchMode = "ai",
  initialProfile = {
    skin: "수부지",
    sensitivity: "보통",
    avoidIngredients: []
  },
  mode = "home",
  pageSize = 10,
  showDefaultSection = true,
  showForYouSkinTypeFilters = true
}: HomeMainContentProps) {
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(deferInitialSearch && mode === "search");
  const [marketPopularSection, setMarketPopularSection] = useState<HomeSection | null>(null);
  const [forYouSection, setForYouSection] = useState<HomeSection | null>(null);
  const [forYouSections, setForYouSections] = useState<Record<string, HomeSection | null>>({});
  const [forYouLoading, setForYouLoading] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(FOR_YOU_SKIN_TYPES.map((skinType) => [skinType, showDefaultSection]))
  );
  const [evidencePicksSection, setEvidencePicksSection] = useState<HomeSection | null>(null);
  const [homeSectionLoading, setHomeSectionLoading] = useState<Record<HomeSectionKey, boolean>>({
    marketPopular: showDefaultSection,
    forYou: showDefaultSection,
    evidencePicks: showDefaultSection
  });
  const [forYouFilters, setForYouFilters] = useState<ForYouFilters>({
    skinType: initialProfile.skin
  });
  const [sortType, setSortType] = useState("score");
  const [agentRefinementFilters, setAgentRefinementFilters] = useState<RecommendationRefinementFilters | null>(
    initialRefinementFilters ?? null,
  );
  const [errorMessage, setErrorMessage] = useState("");
  const isGeneralSearch = initialSearchMode === "general";

  const updateSearchUrl = useCallback(
    (
      nextQuery: string,
      profile: RecommendationProfile,
      page: number,
      recommendationId?: string,
      refinementFilters?: RecommendationRefinementFilters,
    ) => {
      if (mode !== "search") return;

      const params = new URLSearchParams({
        keyword: nextQuery,
        search_mode: initialSearchMode,
        page_size: String(pageSize)
      });
      if (!isGeneralSearch) {
        params.set("skin_type", profile.skin);
        params.set("sensitivity", profile.sensitivity);
      }
      if (page > 1) params.set("page", String(page));
      if (recommendationId) params.set("recommendation_id", recommendationId);
      if (refinementFilters?.min_price != null) params.set("refine_min_price", String(refinementFilters.min_price));
      if (refinementFilters?.max_price != null) params.set("refine_max_price", String(refinementFilters.max_price));
      if (refinementFilters?.category_code) params.set("refine_category_code", refinementFilters.category_code);
      if (refinementFilters?.skin_type) params.set("refine_skin_type", refinementFilters.skin_type);
      if (refinementFilters?.sensitivity) params.set("refine_sensitivity", refinementFilters.sensitivity);
      refinementFilters?.effect_keywords?.forEach((keyword) => params.append("refine_effect", keyword));
      window.history.replaceState(null, "", `/search?${params.toString()}`);
    },
    [initialSearchMode, isGeneralSearch, mode, pageSize]
  );

  const runSearch = useCallback(
    async (
      nextQuery: string,
      profile: RecommendationProfile,
      page = 1,
      recommendationId?: string,
      shouldScrollToResults = mode !== "search",
      refinementFilters?: RecommendationRefinementFilters,
    ) => {
      const trimmedQuery = nextQuery.trim();
      if (!trimmedQuery) return;

      setQuery(trimmedQuery);
      setIsLoading(true);
      setErrorMessage("");
      setAgentRefinementFilters(refinementFilters ?? null);
      setRecommendation(null);
      window.dispatchEvent(
        new CustomEvent("home-recommendation-state", {
          detail: { status: "loading", query: trimmedQuery, recommendation: null }
        })
      );
      if (shouldScrollToResults) {
        window.requestAnimationFrame(() => {
          document
            .getElementById("searchResultsSection")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }

      try {
        const response = isGeneralSearch
          ? await api.searchCatalogProducts({ query: trimmedQuery, page, pageSize })
          : recommendationId
            ? await api.getRecommendation(recommendationId, {
              page,
              pageSize,
              filters: refinementFilters,
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

        const displayResponse = response;
        const nextRecommendationId = isGeneralSearch ? undefined : displayResponse.recommendation_id;
        updateSearchUrl(
          trimmedQuery,
          profile,
          displayResponse.pagination.page,
          nextRecommendationId,
          refinementFilters,
        );
        setRecommendation(displayResponse);
        window.dispatchEvent(
          new CustomEvent("home-recommendation-state", {
            detail: { status: "success", query: trimmedQuery, recommendation: displayResponse }
          })
        );
      } catch {
        if (isGeneralSearch) {
          setErrorMessage("상품 검색을 일시적으로 사용할 수 없습니다.");
          return;
        }
        setRecommendation(null);
        setErrorMessage("추천 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
        window.dispatchEvent(
          new CustomEvent("home-recommendation-state", {
            detail: { status: "error", query: trimmedQuery, recommendation: null }
          })
        );
      } finally {
        setIsLoading(false);
      }
    },
    [isGeneralSearch, mode, pageSize, updateSearchUrl]
  );

  useEffect(() => {
    const handleSearchRequest = async (event: Event) => {
      const { query: nextQuery, profile, recommendationId, refinementFilters } = (event as HomeSearchEvent).detail;
      await runSearch(nextQuery, profile, 1, recommendationId, mode !== "search", refinementFilters);
    };

    window.addEventListener("home-search-request", handleSearchRequest);
    return () => window.removeEventListener("home-search-request", handleSearchRequest);
  }, [mode, runSearch]);

  useEffect(() => {
    if (mode !== "search") return;

    const handleAgentRefinement = (event: Event) => {
      const { products: rawProducts = [], filters = {} } = (event as AgentRefinedProductsEvent).detail;
      setAgentRefinementFilters(filters);
      setRecommendation((current) => {
        if (!current) return current;

        const currentProducts = new Map(
          current.products.map((product) => [product.product_id, product]),
        );
        const refinedProducts = rawProducts.flatMap<ProductCardItem>((rawProduct, index) => {
          const productId = String(rawProduct.product_id ?? rawProduct.id ?? "");
          if (!productId) return [];

          const existingProduct = currentProducts.get(productId);
          if (existingProduct) {
            return [{
              ...existingProduct,
              lowest_price: typeof rawProduct.price === "number"
                ? rawProduct.price
                : existingProduct.lowest_price,
              sales_status: typeof rawProduct.sales_status === "string"
                ? rawProduct.sales_status
                : existingProduct.sales_status,
              stock_status: typeof rawProduct.stock_status === "string"
                ? rawProduct.stock_status
                : existingProduct.stock_status,
              available_quantity: typeof rawProduct.available_quantity === "number"
                ? rawProduct.available_quantity
                : existingProduct.available_quantity,
              in_stock: rawProduct.in_stock === false ? false : existingProduct.in_stock,
            }];
          }

          const effects = Array.isArray(rawProduct.effects)
            ? rawProduct.effects.filter((value): value is string => typeof value === "string")
            : [];
          const ingredients = Array.isArray(rawProduct.key_ingredients)
            ? rawProduct.key_ingredients.filter((value): value is string => typeof value === "string")
            : Array.isArray(rawProduct.ingredients)
              ? rawProduct.ingredients.filter((value): value is string => typeof value === "string")
              : [];
          const cautionFlags = Array.isArray(rawProduct.caution_flags)
            ? rawProduct.caution_flags.filter((value): value is string => typeof value === "string")
            : [];

          return [{
            product_id: productId,
            rank: index + 1,
            total_score: 0,
            reason_summary: typeof rawProduct.summary === "string" ? rawProduct.summary : "현재 검색 결과 조건에 맞는 상품이에요.",
            brand: typeof rawProduct.brand === "string" ? rawProduct.brand : "브랜드 정보 없음",
            name: typeof rawProduct.name === "string" ? rawProduct.name : "상품명 정보 없음",
            thumbnail_url: typeof rawProduct.thumbnail_url === "string"
              ? rawProduct.thumbnail_url
              : typeof rawProduct.thumbnail_storage_key === "string"
                ? rawProduct.thumbnail_storage_key
                : null,
            lowest_price: typeof rawProduct.price === "number" ? rawProduct.price : null,
            evidence_tags: effects,
            key_ingredients: ingredients,
            risk_flags: cautionFlags,
            sales_status: typeof rawProduct.sales_status === "string" ? rawProduct.sales_status : "ON_SALE",
            stock_status: typeof rawProduct.stock_status === "string" ? rawProduct.stock_status : "IN_STOCK",
            available_quantity: typeof rawProduct.available_quantity === "number" ? rawProduct.available_quantity : null,
            in_stock: rawProduct.in_stock !== false,
          }];
        });

        return {
          ...current,
          products: refinedProducts,
          pagination: {
            page: 1,
            page_size: refinedProducts.length,
            total_items: refinedProducts.length,
            total_pages: refinedProducts.length ? 1 : 0,
            has_next: false,
            has_prev: false
          }
        };
      });
    };

    window.addEventListener("agent-refined-products", handleAgentRefinement);
    return () => window.removeEventListener("agent-refined-products", handleAgentRefinement);
  }, [mode]);

  useEffect(() => {
    if (deferInitialSearch && mode === "search" && initialQuery) {
      let isActive = true;
      queueMicrotask(() => {
        if (!isActive) return;
        setQuery(initialQuery);
        setIsLoading(true);
        window.dispatchEvent(
          new CustomEvent("home-recommendation-state", {
            detail: { status: "loading", query: initialQuery, recommendation: null }
          })
        );
      });
      return () => {
        isActive = false;
      };
    }

    if (initialQuery) {
      queueMicrotask(() => {
        runSearch(
          initialQuery,
          initialProfile,
          initialPage,
          initialRecommendationId,
          false,
          initialRefinementFilters,
        );
      });
    }
  }, [deferInitialSearch, initialPage, initialProfile, initialQuery, initialRecommendationId, initialRefinementFilters, mode, runSearch]);

  const loadHomeSection = useCallback(
    async (sectionKey: HomeSectionKey) => {
      setHomeSectionLoading((current) => ({ ...current, [sectionKey]: true }));

      try {
        if (sectionKey === "marketPopular") {
          setMarketPopularSection(await api.getMarketPopular({ limit: 10 }));
        } else if (sectionKey === "forYou") {
          setForYouLoading(Object.fromEntries(FOR_YOU_SKIN_TYPES.map((skinType) => [skinType, true])));
          const prefetched = await Promise.all(
            FOR_YOU_SKIN_TYPES.map(async (skinType) => {
              try {
                const section = await api.getForYou({ skinType, limit: 10 });
                setForYouSections((current) => ({ ...current, [skinType]: section }));
                if (skinType === "건성") setForYouSection(section);
                return [skinType, section] as const;
              } catch {
                return [skinType, null] as const;
              } finally {
                setForYouLoading((current) => ({ ...current, [skinType]: false }));
              }
            })
          );
          const nextSections = Object.fromEntries(prefetched) as Record<string, HomeSection | null>;
          setForYouSections(nextSections);
          setForYouSection(nextSections["건성"] ?? null);
        } else {
          setEvidencePicksSection(await api.getEvidencePicks({ limit: 10 }));
        }
      } catch {
        if (sectionKey === "marketPopular") setMarketPopularSection(null);
        else if (sectionKey === "forYou") setForYouSection(null);
        else setEvidencePicksSection(null);
      } finally {
        setHomeSectionLoading((current) => ({ ...current, [sectionKey]: false }));
      }
    },
    []
  );

  const updateForYouFilter = (key: keyof ForYouFilters, value: string) => {
    setForYouFilters((current) => ({ ...current, [key]: value }));
    if (key === "skinType") {
      setForYouSection(forYouSections[value] ?? null);
    }
  };

  useEffect(() => {
    if (!showDefaultSection) return;

    const loadHome = async () => {
      await Promise.all(DEFAULT_HOME_SECTION_ORDER.map(loadHomeSection));
    };

    void loadHome();
  }, [loadHomeSection, showDefaultSection]);

  useEffect(() => {
    return observeProductImpressions();
  }, [evidencePicksSection, forYouSection, isLoading, marketPopularSection, recommendation]);

  const hasVisibleHomeSection =
    Boolean(marketPopularSection?.products.length) ||
    Boolean(forYouSection?.products.length) ||
    Boolean(evidencePicksSection?.products.length);
  const selectedForYouSkinType = showForYouSkinTypeFilters
    ? forYouFilters.skinType
    : initialProfile.skin;
  const selectedForYouSection =
    forYouSections[selectedForYouSkinType] ?? (selectedForYouSkinType === "건성" ? forYouSection : null);
  const selectedForYouLoading = forYouLoading[selectedForYouSkinType] ?? homeSectionLoading.forYou;

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
  const hasSearchState = isLoading || Boolean(recommendation) || Boolean(errorMessage);
  const showPagination = mode === "search" && !isLoading && pagination.total_pages > 1;
  const goToPage = (page: number) => {
    const nextPage = Math.min(Math.max(page, 1), pagination.total_pages || 1);
    if (nextPage === pagination.page) return;
    const currentRecommendationId = recommendation?.recommendation_id ?? initialRecommendationId;
    runSearch(
      query || initialQuery,
      initialProfile,
      nextPage,
      currentRecommendationId,
      true,
      agentRefinementFilters ?? undefined,
    );
  };

  return (
    <main
      className={`main-content${mode === "search" ? " search-main-content" : ""}`}
      id="mainContent"
    >
      <div id="searchResultsSection" style={{ display: hasSearchState ? "block" : "none" }}>
        <div
          className={`search-results-shell${isGeneralSearch ? " general-search-results" : " ai-search-results"}`}
          style={isGeneralSearch ? undefined : { gridTemplateColumns: "minmax(0, 1fr)" }}
        >

          <section className="search-results-panel">
            <div
              className="results-header"
              style={
                !isGeneralSearch
                  ? { alignItems: "center", flexDirection: "row", gap: 18, padding: "18px 22px" }
                  : undefined
              }
            >
              <div>
                <div className="results-query">
                  &quot;<strong id="queryDisplay">{query}</strong>&quot; 검색 결과
                </div>
                <div className="section-subtitle" style={{ marginTop: 4 }}>
                  {isLoading
                    ? isGeneralSearch ? "상품 검색 결과를 불러오는 중입니다" : "추천 결과를 불러오는 중입니다"
                    : agentRefinementFilters?.max_price
                      ? `${pagination.total_items}개 제품 · ${Number(agentRefinementFilters.max_price).toLocaleString("ko-KR")}원 이하로 좁혔습니다`
                      : isGeneralSearch ? `${pagination.total_items}개 제품을 찾았습니다` : `${pagination.total_items}개 제품이 피부 고민에 매칭되었습니다`}
                </div>
              </div>
              {!isGeneralSearch ? (
                <div
                  aria-label="AI 추천 결과 정렬"
                  className="general-search-sort-tabs"
                  role="tablist"
                  style={{ marginLeft: "auto", width: "auto" }}
                >
                  {[
                    { value: "score", label: "매칭 점수순" },
                    { value: "price-low", label: "낮은 가격순" },
                    { value: "price-high", label: "높은 가격순" }
                  ].map((option) => (
                    <button
                      aria-selected={sortType === option.value}
                      className={sortType === option.value ? "active" : ""}
                      key={option.value}
                      onClick={() => setSortType(option.value)}
                      role="tab"
                      type="button"
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <div
              className={`api-result-summary${recommendation?.unmatched_terms.length ? " active" : ""}`}
              id="apiResultSummary"
            >
              {recommendation?.unmatched_terms.map((term) => (
                <span className="api-summary-chip warning" key={term}>
                  추가 확인 필요: {term}
                </span>
              ))}
            </div>
            <div className="product-grid" id="searchResultsGrid">
              {isLoading ? <ProductSkeletonList count={10} variant="search" /> : errorMessage ? (
                <div className="search-empty">{errorMessage}</div>
              ) : sortedProducts.length ? (
                sortedProducts.map((product, index) => (
                  <HomeProductCard
                    displayRank={
                      isGeneralSearch
                        ? undefined
                        : agentRefinementFilters
                          ? product.rank
                          : (pagination.page - 1) * pagination.page_size + index + 1
                    }
                    eventContext={{
                      sectionId: "recommendation_results",
                      page: "search",
                      source: "recommendation_result",
                      clickEvent: "search_result_click",
                      impressionEvent: "search_result_impression"
                    }}
                    key={product.product_id}
                    product={product}
                    recommendationId={isGeneralSearch ? undefined : recommendation?.recommendation_id}
                    showScore={!isGeneralSearch}
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
        {hasVisibleHomeSection || Object.values(homeSectionLoading).some(Boolean) ? (
          <div className="home-section-stack">
            {marketPopularSection?.products.length ? (
              <HomeRankingSection
                key={marketPopularSection.section_id}
                products={marketPopularSection.products.map(mapHomeProductToCard)}
                section={marketPopularSection}
                sectionIndex={0}
              />
            ) : homeSectionLoading.marketPopular ? <HomeSectionLoadingSkeleton sectionKey="marketPopular" /> : null}
            {selectedForYouSection?.products.length ? (
              <HomeDealSection
                key={selectedForYouSection.section_id}
                products={selectedForYouSection.products.map(mapHomeProductToCard)}
                section={selectedForYouSection}
                toneMint
                forYouFilters={showForYouSkinTypeFilters ? forYouFilters : undefined}
                onForYouFilterChange={
                  showForYouSkinTypeFilters ? updateForYouFilter : undefined
                }
              />
            ) : selectedForYouLoading ? <HomeSectionLoadingSkeleton sectionKey="forYou" /> : null}
            {evidencePicksSection?.products.length ? (
              <HomeOriginalGridSection
                key={evidencePicksSection.section_id}
                products={evidencePicksSection.products.map(mapHomeProductToCard)}
                section={evidencePicksSection}
              />
            ) : homeSectionLoading.evidencePicks ? <HomeSectionLoadingSkeleton sectionKey="evidencePicks" /> : null}
          </div>
        ) : null}
      </div>
    </main>
  );
}

export default HomeMainContent;
