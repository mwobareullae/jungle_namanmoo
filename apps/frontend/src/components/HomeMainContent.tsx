import { useCallback, useEffect, useMemo, useState } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { createFallbackRecommendation } from "../lib/fallbackProducts";
import type { RecommendationResponse, Sensitivity, SkinType } from "../types/recommendation";
import HomeProductCard from "./HomeProductCard";

const categoryTabs = [
  ["전체", "all"],
  ["토너", "toner"],
  ["세럼/앰플", "serum"],
  ["크림/밤", "cream"],
  ["디바이스", "device"],
  ["파우더", "powder"],
] as const;

const resultTabs = ["전체", "성분 근거", "피부 타입", "가격"];

type HomeSearchEvent = CustomEvent<{
  query: string;
  profile: {
    skin: SkinType;
    sensitivity: Sensitivity;
  };
}>;

type HomeMainContentProps = {
  initialQuery?: string;
  initialProfile?: {
    skin: SkinType;
    sensitivity: Sensitivity;
  };
  mode?: "home" | "search";
  showDefaultSection?: boolean;
};

function HomeMainContent({
  initialQuery = "",
  initialProfile = {
    skin: "수부지",
    sensitivity: "보통",
  },
  mode = "home",
  showDefaultSection = true,
}: HomeMainContentProps) {
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [sortType, setSortType] = useState("score");
  const [errorMessage, setErrorMessage] = useState("");

  const runSearch = useCallback(async (nextQuery: string, profile: { skin: SkinType; sensitivity: Sensitivity }) => {
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
      const response = await api.createRecommendation({
        concern_text: trimmedQuery,
        skin_type: profile.skin,
        sensitivity: profile.sensitivity,
        avoid_ingredients: [],
      });
      setRecommendation(response);
      window.dispatchEvent(new CustomEvent("home-recommendation-state", {
        detail: { status: "success", query: trimmedQuery, recommendation: response },
      }));
    } catch {
      const fallbackResponse = createFallbackRecommendation(trimmedQuery, profile);
      setRecommendation(fallbackResponse);
      setErrorMessage("");
      window.dispatchEvent(new CustomEvent("home-recommendation-state", {
        detail: { status: "success", query: trimmedQuery, recommendation: fallbackResponse },
      }));
    } finally {
      setIsLoading(false);
    }
  }, []);

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
      runSearch(initialQuery, initialProfile);
    }
  }, [initialProfile, initialQuery, runSearch]);

  const sortedProducts = useMemo(() => {
    const products = recommendation?.products ?? [];
    return [...products].sort((a, b) => {
      if (sortType === "price-low") return (a.lowest_price ?? Number.MAX_SAFE_INTEGER) - (b.lowest_price ?? Number.MAX_SAFE_INTEGER);
      if (sortType === "price-high") return (b.lowest_price ?? -1) - (a.lowest_price ?? -1);
      return b.total_score - a.total_score;
    });
  }, [recommendation, sortType]);

  const products = recommendation?.products ?? [];
  const hasSearchState = isLoading || Boolean(recommendation) || Boolean(errorMessage);

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
                <div className="sec-eyebrow">맞춤 매칭 결과</div>
                <div className="results-query">
                  &quot;<strong id="queryDisplay">{query}</strong>
                  &quot; 검색 결과 · <span id="sortDisplay">{sortType === "price-low" ? "가격 낮은순" : sortType === "price-high" ? "가격 높은순" : "매칭 점수순"}</span>
                </div>
                <div className="section-subtitle" style={{ marginTop: 4 }}>
                  {isLoading ? "추천 결과를 불러오는 중입니다" : `${products.length}개 제품이 피부 고민에 매칭되었습니다`}
                </div>
              </div>
              <select aria-label="검색 결과 정렬" className="sort-select" onChange={(event) => setSortType(event.target.value)} value={sortType}>
                <option value="score">매칭 점수순</option>
                <option value="price-low">가격 낮은순</option>
                <option value="price-high">가격 높은순</option>
              </select>
            </div>
            <div className={`api-result-summary${recommendation?.unmatched_terms.length ? " active" : ""}`} id="apiResultSummary">
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
                <div className="search-empty">피부 고민을 분석하고 있어요.</div>
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
            <div className="search-pagination" id="searchPagination" />
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
                  href="#"
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
        <div className="section-header">
          <div>
            <div className="sec-eyebrow">Best Sellers</div>
            <div className="section-title">지금 인기있는 제품</div>
            <div className="section-subtitle">실시간 인기와 성분 근거를 함께 본 베스트셀러</div>
          </div>
          <a className="see-all" href="#">
            전체보기
          </a>
        </div>

        <div className="cat-tabs">
          {categoryTabs.map(([label, category]) => (
            <button
              className={`cat-tab${category === "all" ? " active" : ""}`}
              key={category}
              onClick={(event) => callOriginal("filterCat", event.currentTarget, category)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>

        <div className="product-grid" id="defaultProductGrid">
          <div className="empty-state">추천 검색을 시작하면 상품이 표시됩니다.</div>
        </div>
      </div>
    </main>
  );
}

export default HomeMainContent;
