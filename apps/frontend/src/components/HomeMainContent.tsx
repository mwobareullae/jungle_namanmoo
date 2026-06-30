import { callOriginal } from "../lib/originalRuntime";

const categoryTabs = [
  ["전체", "all"],
  ["토너", "toner"],
  ["세럼/앰플", "serum"],
  ["크림/밤", "cream"],
  ["디바이스", "device"],
  ["파우더", "powder"],
] as const;

const resultTabs = ["전체", "성분 근거", "피부 타입", "가격"];

function HomeMainContent() {
  return (
    <main className="main-content" id="mainContent">
      <div id="searchResultsSection" style={{ display: "none" }}>
        <div className="search-results-shell">
          <aside aria-label="검색 조건" className="search-filter-sidebar" data-commerce-only>
            <div className="filter-card">
              <div className="filter-card-title">추천 기준</div>
              <div className="filter-options">
                <div className="filter-option">
                  <span className="filter-dot" />
                  <span id="filterConcern">피부 고민 분석</span>
                </div>
                <div className="filter-option">
                  <span className="filter-dot" />
                  <span id="filterProfile">수부지 · 민감도 보통</span>
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
                  &quot;<strong id="queryDisplay" />
                  &quot; 검색 결과 · <span id="sortDisplay">매칭 점수순</span>
                </div>
                <div className="section-subtitle" style={{ marginTop: 4 }}>
                  4개 제품이 피부 고민에 매칭되었습니다
                </div>
              </div>
              <select aria-label="검색 결과 정렬" className="sort-select">
                <option value="score">매칭 점수순</option>
                <option value="price-low">가격 낮은순</option>
                <option value="price-high">가격 높은순</option>
              </select>
            </div>
            <div className="api-result-summary" id="apiResultSummary" />
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
            <div className="product-grid" id="searchResultsGrid" />
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

      <div id="defaultSection">
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

        <div className="product-grid" id="defaultProductGrid" />
      </div>
    </main>
  );
}

export default HomeMainContent;
