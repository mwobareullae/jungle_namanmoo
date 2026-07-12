import { useEffect, useState, type KeyboardEvent } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { RadioGroup, RadioGroupItem } from "./ui/radio-group";
import type { RecommendationProfile, SearchMode, Sensitivity, SkinType } from "../types/recommendation";
import type { CatalogSuggestionItem } from "../types/product";

type SearchBarPanelProps = {
  initialQuery?: string;
  initialSearchMode?: SearchMode;
  initialProfile: RecommendationProfile;
  hasSavedProfile?: boolean;
};

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

function SearchBarPanel({ initialQuery = "", initialSearchMode = "ai", initialProfile, hasSavedProfile = false }: SearchBarPanelProps) {
  const [query, setQuery] = useState(initialQuery);
  const [profile, setProfile] = useState(initialProfile);
  const [searchMode, setSearchMode] = useState<SearchMode>(initialSearchMode);
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);

  useEffect(() => {
    callOriginal("setSearchMode", searchMode);
  }, [searchMode]);

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

  const goToSearch = (nextQuery = query) => {
    const trimmedQuery = nextQuery.trim();
    if (!trimmedQuery) return;

    if (searchMode === "general") {
      window.location.href = `/catalog-search?q=${encodeURIComponent(trimmedQuery)}`;
      return;
    }

    const params = new URLSearchParams({
      keyword: trimmedQuery,
      search_mode: searchMode,
      page_size: "10"
    });
    if (searchMode === "ai") {
      params.set("skin_type", profile.skin);
      params.set("sensitivity", profile.sensitivity);
    }
    window.location.href = `/search?${params.toString()}`;
  };

  const handleSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") goToSearch();
  };

  const selectSuggestion = (suggestion: CatalogSuggestionItem) => {
    setSuggestions([]);
    if (suggestion.type === "PRODUCT" && suggestion.product_id) {
      window.location.href = `/product-detail?id=${encodeURIComponent(suggestion.product_id)}`;
      return;
    }
    setQuery(suggestion.text);
  };

  return (
    <section className="search-page-top">
      <div className="search-page-top-inner">
        <div className="search-container search-mode-container">
          <div aria-label="검색 방식" className="search-mode-tabs" role="tablist">
            <button aria-selected={searchMode === "general"} className={searchMode === "general" ? "active" : ""} onClick={() => setSearchMode("general")} role="tab" type="button">일반 검색</button>
            <button aria-selected={searchMode === "ai"} className={searchMode === "ai" ? "active" : ""} onClick={() => setSearchMode("ai")} role="tab" type="button">AI 추천</button>
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
                  onClick={() => callOriginal("openSearchSuggestions")}
                  type="button"
                >
                  {profile.skin} · {profile.sensitivity}
                </button>
              ) : null}
              <input
                id="searchInput"
                onKeyDown={handleSearchKey}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={searchMode === "ai" ? "예: 민감하고 자주 붉어져요" : "상품명, 브랜드, 성분을 검색하세요"}
                type="text"
                value={query}
              />
              <button className="search-btn" onClick={() => goToSearch()} type="button">
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

            {searchMode === "general" && suggestions.length > 0 ? (
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
              className={`search-suggest-panel${searchMode === "general" && query.trim() ? " search-suggest-panel--hidden" : ""}`}
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

              {!hasSavedProfile ? (
                <div className="suggest-section">
                  <div className="profile-picker-grid">
                    <div className="profile-picker-group">
                      <span className="profile-picker-label">피부 타입</span>
                      <RadioGroup
                        aria-label="피부 타입"
                        className="profile-segments skin"
                        onValueChange={(value) => {
                          const skinType = value as SkinType;
                          setProfile((current) => ({ ...current, skin: skinType }));
                          callOriginal("selectProfileOption", "skin", skinType);
                        }}
                        value={profile.skin}
                      >
                        {skinTypes.map((skinType) => (
                          <RadioGroupItem
                            className={`profile-option${skinType === profile.skin ? " active" : ""}`}
                            data-profile="skin"
                            data-value={skinType}
                            key={skinType}
                            value={skinType}
                          >
                            {skinType}
                          </RadioGroupItem>
                        ))}
                      </RadioGroup>
                    </div>

                    <div className="profile-picker-group">
                      <span className="profile-picker-label">민감도</span>
                      <RadioGroup
                        aria-label="민감도"
                        className="profile-segments sensitivity"
                        onValueChange={(value) => {
                          const sensitivity = value as Sensitivity;
                          setProfile((current) => ({ ...current, sensitivity }));
                          callOriginal("selectProfileOption", "sensitivity", sensitivity);
                        }}
                        value={profile.sensitivity}
                      >
                        {sensitivities.map((sensitivity) => (
                          <RadioGroupItem
                            className={`profile-option${sensitivity === profile.sensitivity ? " active" : ""}`}
                            data-profile="sensitivity"
                            data-value={sensitivity}
                            key={sensitivity}
                            value={sensitivity}
                          >
                            {sensitivity}
                          </RadioGroupItem>
                        ))}
                      </RadioGroup>
                    </div>
                  </div>

                  <div className="suggest-actions">
                    <span className="profile-summary" id="profileSummary">
                      {profile.skin} · 민감도 {profile.sensitivity} 기준으로 추천
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default SearchBarPanel;
