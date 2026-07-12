import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import type { RecommendationProfile, SearchMode } from "../types/recommendation";
import type { CatalogSuggestionItem } from "../types/product";

const setSearch = (text: string) => callOriginal("setSearch", text);

const placeholderExamples = [
  "모공이 넓고 번들거려요",
  "건조하고 주름이 걱정돼요",
  "색소침착과 잡티가 있어요",
  "민감하고 자주 붉어져요"
];

type HomeHeroProps = {
  initialQuery?: string;
  initialProfile?: RecommendationProfile;
  hasSavedProfile?: boolean;
};

type HomeSearchInputChangeEvent = CustomEvent<{
  query: string;
}>;

function HomeHero({
  initialQuery = "",
  hasSavedProfile = false,
  initialProfile = {
    skin: "수부지",
    sensitivity: "보통",
    avoidIngredients: []
  }
}: HomeHeroProps) {
  const searchContainerRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState(initialQuery);
  const [placeholder, setPlaceholder] = useState(placeholderExamples[0]);
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState(false);
  const [searchMode, setSearchMode] = useState<SearchMode>("ai");
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);

  useEffect(() => {
    const normalized = query.trim();
    if (searchMode !== "general" || !normalized) {
      setSuggestions([]);
      return;
    }

    let isMounted = true;
    const timer = window.setTimeout(() => {
      api.getCatalogSuggestions(normalized)
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
  }, [query, searchMode]);

  useEffect(() => {
    if (query.trim()) return;

    let timeoutId = 0;
    let phraseIndex = 0;
    let charIndex = 0;
    let isDeleting = false;
    let isActive = true;

    const tick = () => {
      if (!isActive) return;

      const phrase = placeholderExamples[phraseIndex];
      setPlaceholder(phrase.slice(0, charIndex));

      if (!isDeleting && charIndex < phrase.length) {
        charIndex += 1;
        timeoutId = window.setTimeout(tick, 70);
        return;
      }

      if (!isDeleting && charIndex === phrase.length) {
        isDeleting = true;
        timeoutId = window.setTimeout(tick, 1500);
        return;
      }

      if (isDeleting && charIndex > 0) {
        charIndex -= 1;
        timeoutId = window.setTimeout(tick, 32);
        return;
      }

      isDeleting = false;
      phraseIndex = (phraseIndex + 1) % placeholderExamples.length;
      timeoutId = window.setTimeout(tick, 240);
    };

    tick();

    return () => {
      isActive = false;
      window.clearTimeout(timeoutId);
    };
  }, [query]);

  useEffect(() => {
    const handleSearchInputChange = (event: Event) => {
      setQuery((event as HomeSearchInputChangeEvent).detail.query);
      setIsSuggestionsOpen(true);
    };

    window.addEventListener("home-search-input-change", handleSearchInputChange);
    return () => window.removeEventListener("home-search-input-change", handleSearchInputChange);
  }, []);

  useEffect(() => {
    const handleDocumentPointerDown = (event: PointerEvent) => {
      if (!searchContainerRef.current?.contains(event.target as Node)) {
        setIsSuggestionsOpen(false);
      }
    };

    const handleDocumentKeydown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsSuggestionsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handleDocumentPointerDown);
    document.addEventListener("keydown", handleDocumentKeydown);
    return () => {
      document.removeEventListener("pointerdown", handleDocumentPointerDown);
      document.removeEventListener("keydown", handleDocumentKeydown);
    };
  }, []);

  const openSuggestions = () => {
    setIsSuggestionsOpen(true);
    callOriginal("openSearchSuggestions");
  };

  const handleSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") handleSearch();
  };

  const handleSearch = () => {
    const normalized = query.trim();
    if (!normalized) return;
    if (searchMode === "general") {
      window.location.href = `/catalog-search?q=${encodeURIComponent(normalized)}`;
      return;
    }
    callOriginal("doSearch", searchMode);
  };

  const selectSuggestion = (suggestion: CatalogSuggestionItem) => {
    setSuggestions([]);
    if (suggestion.type === "PRODUCT" && suggestion.product_id) {
      window.location.href = `/product-detail?id=${encodeURIComponent(suggestion.product_id)}`;
      return;
    }
    setQuery(suggestion.text);
  };

  const handleExampleClick = (text: string) => {
    setQuery(text);
    setSearch(text);
  };

  const selectSearchMode = (mode: SearchMode) => {
    setSearchMode(mode);
    callOriginal("setSearchMode", mode);
  };

  return (
    <section className="hero">
      <div className="hero-inner">
        <h1>
          내 피부 고민에 맞는
          <br />
          <em>최적의 화장품 추천</em>
        </h1>
        <p>
          피부 고민을 입력하면 성분 효능 근거를 바탕으로
          <br />
          지금 필요한 제품을 찾아드려요
        </p>

        <div
          className={`search-container${isSuggestionsOpen ? " suggestions-open" : ""}`}
          ref={searchContainerRef}
        >
          <div aria-label="검색 방식" className="search-mode-tabs" role="tablist">
            <button aria-selected={searchMode === "general"} className={searchMode === "general" ? "active" : ""} onClick={() => selectSearchMode("general")} role="tab" type="button">일반 검색</button>
            <button aria-selected={searchMode === "ai"} className={searchMode === "ai" ? "active" : ""} onClick={() => selectSearchMode("ai")} role="tab" type="button">AI 추천</button>
          </div>
          <div className="search-combo">
            <div className="search-box" id="searchBox">
              <div className="search-icon">
                <svg
                  fill="none"
                  height="18"
                  stroke="#94e0f8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                  width="18"
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
              </div>
              {searchMode === "ai" && !hasSavedProfile ? (
                <button
                  className="search-profile-chip"
                  id="searchProfileChip"
                  onClick={openSuggestions}
                  type="button"
                >
                  {initialProfile.skin} · {initialProfile.sensitivity}
                </button>
              ) : null}
              <input
                id="searchInput"
                onChange={(event) => setQuery(event.target.value)}
                onClick={openSuggestions}
                onFocus={openSuggestions}
                onKeyDown={handleSearchKey}
                placeholder={searchMode === "ai" ? placeholder : "상품명, 브랜드, 성분을 검색하세요"}
                type="text"
                value={query}
              />
              <button className="search-btn" onClick={handleSearch} type="button">
                <svg
                  fill="none"
                  height="14"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2.5"
                  viewBox="0 0 24 24"
                  width="14"
                >
                  <path d="m22 2-7 20-4-9-9-4z" />
                </svg>
                {searchMode === "ai" ? "AI 추천 받기" : "검색"}
              </button>
            </div>

            {searchMode === "general" && isSuggestionsOpen && suggestions.length > 0 ? (
              <div className="search-mode-suggestions" role="listbox">
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

            <div
              aria-label="최근 고민과 피부 조건"
              className={`search-suggest-panel${isSuggestionsOpen ? " active" : ""}${searchMode === "general" && query.trim() ? " search-suggest-panel--hidden" : ""}`}
              id="searchSuggestPanel"
            >
              <div className="suggest-section">
                <div className="suggest-header">
                  <span>{searchMode === "ai" ? "최근 AI 추천" : "최근 검색어"}</span>
                  <button
                    className="recent-clear"
                    id="recentClearButton"
                    onClick={(event) => callOriginal("clearRecentConcerns", event)}
                    type="button"
                  >
                    전체 삭제
                  </button>
                </div>
                <div className="recent-list" id="recentConcernList" />
              </div>

              {searchMode === "ai" && !hasSavedProfile ? (
                <div className="suggest-section">
                  <div className="profile-picker-grid">
                    <div className="profile-picker-group">
                      <span className="profile-picker-label">피부 타입</span>
                      <div aria-label="피부 타입" className="profile-segments skin" role="radiogroup">
                        {["건성", "지성", "복합성", "수부지", "중성"].map((skinType) => (
                          <button
                            className={`profile-option${skinType === initialProfile.skin ? " active" : ""}`}
                            data-profile="skin"
                            data-value={skinType}
                            key={skinType}
                            onClick={() => callOriginal("selectProfileOption", "skin", skinType)}
                            type="button"
                          >
                            {skinType}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="profile-picker-group">
                      <span className="profile-picker-label">민감도</span>
                      <div
                        aria-label="민감도"
                        className="profile-segments sensitivity"
                        role="radiogroup"
                      >
                        {["낮음", "보통", "높음"].map((sensitivity) => (
                          <button
                            className={`profile-option${sensitivity === initialProfile.sensitivity ? " active" : ""}`}
                            data-profile="sensitivity"
                            data-value={sensitivity}
                            key={sensitivity}
                            onClick={() =>
                              callOriginal("selectProfileOption", "sensitivity", sensitivity)
                            }
                            type="button"
                          >
                            {sensitivity}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="suggest-actions">
                    <span className="profile-summary" id="profileSummary">
                      {initialProfile.skin} · 민감도 {initialProfile.sensitivity} 기준으로 추천
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="search-examples search-examples--with-guide">
            <span
              className="example-chip"
              onClick={() => handleExampleClick("모공이 넓고 피지가 많아요")}
            >
              모공이 넓고 피지가 많아요
            </span>
            <span
              className="example-chip"
              onClick={() => handleExampleClick("건조하고 주름이 걱정돼요")}
            >
              건조하고 주름이 걱정돼요
            </span>
            <span
              className="example-chip"
              onClick={() => handleExampleClick("색소침착과 잡티가 있어요")}
            >
              색소침착과 잡티가 있어요
            </span>
            <a className="recommendation-guide-link" href="/recommendation-guide">
              추천 기준 알아보기 ›
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

export default HomeHero;
