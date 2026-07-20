import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { callOriginal } from "../lib/originalRuntime";
import { api } from "../lib/api";
import { buildAgentPendingSearchUrl, runAgentEntryMessage } from "../lib/agentRecommendationSearch";
import type { RecommendationProfile, SearchMode } from "../types/recommendation";
import type { CatalogSuggestionItem } from "../types/product";

const exampleChipCandidates = [
  { category: "모공·피지", text: "모공이 넓고 피지가 많아요" },
  { category: "모공·피지", text: "티존만 유독 번들거려요" },
  { category: "속건조", text: "속은 당기는데 겉은 번들거려요" },
  { category: "속건조", text: "세안 후 바로 당기고 각질이 일어나요" },
  { category: "여드름·트러블", text: "턱에 여드름이 자꾸 올라와요" },
  { category: "여드름·트러블", text: "스트레스 받으면 트러블이 심해져요" },
  { category: "홍조", text: "얼굴이 쉽게 붉어지고 열감이 있어요" },
  { category: "홍조", text: "볼에 홍조가 계속 남아있어요" },
  { category: "잡티·색소침착", text: "색소침착과 잡티가 있어요" },
  { category: "잡티·색소침착", text: "여드름 자국이 잘 안 없어져요" },
  { category: "피부결", text: "피부결이 울퉁불퉁하고 칙칙해요" },
  { category: "피부결", text: "화장이 자꾸 뜨고 결이 거칠어요" },
  { category: "복합", text: "예민한데 건조하고 트러블도 있어요" }
] as const;

// 자동완성도 단어만 노출하지 않고, 사용자가 실제로 입력할 수 있는
// 자연어 고민 문장으로 순환시킨다.
const placeholderExamples = exampleChipCandidates.map((candidate) => candidate.text);

const shouldFastRouteDemoConcern = (value: string) => {
  const normalized = value.replace(/[\s,，.。!?！？·ㆍ/|]+/g, "");
  const poreSebumDemo = /피지/.test(normalized) && /모공/.test(normalized) && /고민/.test(normalized);
  const oilyBlemishDemo = /지성/.test(normalized) && /뾰루지/.test(normalized);
  return poreSebumDemo || oilyBlemishDemo;
};

const pickExampleChips = () => {
  const categories = [...new Set(exampleChipCandidates.map((candidate) => candidate.category))]
    .sort(() => Math.random() - 0.5)
    .slice(0, 3);
  return categories.map((category) => {
    const candidates = exampleChipCandidates.filter((candidate) => candidate.category === category);
    return candidates[Math.floor(Math.random() * candidates.length)].text;
  });
};

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
  const [profile, setProfile] = useState(initialProfile);
  const [placeholder, setPlaceholder] = useState<string>(placeholderExamples[0]);
  const [exampleChips] = useState<string[]>(pickExampleChips);
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState(false);
  const [searchMode, setSearchMode] = useState<SearchMode>("ai");
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  const [isAgentSubmitting, setIsAgentSubmitting] = useState(false);

  useEffect(() => {
    const normalized = query.trim();
    let isMounted = true;
    if (searchMode !== "general" || !normalized) {
      queueMicrotask(() => {
        if (!isMounted) return;
        setSuggestions([]);
        setIsSuggestionsLoading(false);
      });
      return () => {
        isMounted = false;
      };
    }

    const timer = window.setTimeout(() => {
      if (!isMounted) return;
      setIsSuggestionsLoading(true);
      api.getCatalogSuggestions(normalized)
        .then((response) => {
          if (isMounted) setSuggestions(response.items);
        })
        .catch(() => {
          if (isMounted) setSuggestions([]);
        })
        .finally(() => {
          if (isMounted) setIsSuggestionsLoading(false);
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
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    setIsSuggestionsOpen(true);
    callOriginal("openSearchSuggestions");
    requestAnimationFrame(() => {
      window.scrollTo({ left: scrollX, top: scrollY, behavior: "auto" });
    });
  };

  const handleSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") void handleSearch();
  };

  const routeDemoConcernIfNeeded = (text: string) => {
    if (!shouldFastRouteDemoConcern(text)) return false;
    window.location.assign(buildAgentPendingSearchUrl(text.trim(), profile));
    return true;
  };

  const handleSearch = async () => {
    const normalized = query.trim();
    if (!normalized || isAgentSubmitting) return;
    if (searchMode === "general") {
      window.location.assign(`/catalog-search?q=${encodeURIComponent(normalized)}`);
      return;
    }

    if (routeDemoConcernIfNeeded(normalized)) return;

    setIsAgentSubmitting(true);
    setIsSuggestionsOpen(false);
    try {
      const response = await runAgentEntryMessage(normalized, profile);
      if (!response) {
        throw new Error("추천 결과가 준비되지 않았습니다.");
      }
    } catch {
      window.dispatchEvent(new CustomEvent("home-search-failed", {
        detail: { query: normalized },
      }));
      callOriginal("showToast", "추천을 준비하지 못했어요. 잠시 후 다시 시도해주세요");
    } finally {
      setIsAgentSubmitting(false);
    }
  };

  const selectSuggestion = (suggestion: CatalogSuggestionItem) => {
    setSuggestions([]);
    if (suggestion.type === "PRODUCT" && suggestion.product_id) {
      window.location.assign(`/product-detail?id=${encodeURIComponent(suggestion.product_id)}`);
      return;
    }
    setQuery(suggestion.text);
  };

  const handleExampleClick = async (text: string) => {
    if (isAgentSubmitting) return;
    setQuery(text);
    setIsSuggestionsOpen(false);
    if (routeDemoConcernIfNeeded(text)) return;
    setIsAgentSubmitting(true);
    try {
      const response = await runAgentEntryMessage(text, profile);
      if (!response) {
        throw new Error("추천 결과가 준비되지 않았습니다.");
      }
    } catch {
      window.dispatchEvent(new CustomEvent("home-search-failed", {
        detail: { query: text },
      }));
      callOriginal("showToast", "추천을 준비하지 못했어요. 잠시 후 다시 시도해주세요");
    } finally {
      setIsAgentSubmitting(false);
    }
  };

  const selectSearchMode = (mode: SearchMode) => {
    setSearchMode(mode);
    setIsSuggestionsOpen(true);
    callOriginal("setSearchMode", mode);
  };

  const handleQueryChange = (nextQuery: string) => {
    setQuery(nextQuery);
    setIsSuggestionsOpen(true);
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
                  {profile.skin} · {profile.sensitivity}
                </button>
              ) : null}
              <input
                autoComplete="off"
                id="searchInput"
                onChange={(event) => handleQueryChange(event.target.value)}
                onClick={openSuggestions}
                onFocus={openSuggestions}
                onKeyDown={handleSearchKey}
                placeholder={searchMode === "ai" ? placeholder : "상품명, 브랜드, 성분을 검색하세요"}
                type="text"
                value={query}
              />
              <button className="search-btn" disabled={isAgentSubmitting} onClick={() => void handleSearch()} type="button">
                {!isAgentSubmitting ? (
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
                ) : null}
                {isAgentSubmitting ? "추천 준비 중" : searchMode === "ai" ? "AI 추천 받기" : "검색"}
                {isAgentSubmitting ? <span aria-hidden="true" className="search-btn-spinner" /> : null}
              </button>
            </div>

            {searchMode === "general" && isSuggestionsOpen && query.trim() ? (
              <div className="search-mode-suggestions" role="listbox">
                {isSuggestionsLoading ? <div className="search-mode-suggestions__state">검색어를 찾고 있어요…</div> : null}
                {!isSuggestionsLoading && suggestions.map((suggestion) => (
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
                {!isSuggestionsLoading && suggestions.length === 0 ? <div className="search-mode-suggestions__state">일치하는 검색어가 없습니다.</div> : null}
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
                            className={`profile-option${skinType === profile.skin ? " active" : ""}`}
                            data-profile="skin"
                            data-value={skinType}
                            key={skinType}
                            onClick={() => {
                              setProfile((current) => ({ ...current, skin: skinType as RecommendationProfile["skin"] }));
                              callOriginal("selectProfileOption", "skin", skinType);
                            }}
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
                            className={`profile-option${sensitivity === profile.sensitivity ? " active" : ""}`}
                            data-profile="sensitivity"
                            data-value={sensitivity}
                            key={sensitivity}
                            onClick={() => {
                              setProfile((current) => ({ ...current, sensitivity: sensitivity as RecommendationProfile["sensitivity"] }));
                              callOriginal("selectProfileOption", "sensitivity", sensitivity);
                            }}
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
                      {profile.skin} · 민감도 {profile.sensitivity} 기준으로 추천
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {searchMode === "ai" ? (
            <div className="search-examples search-examples--with-guide">
              {exampleChips.map((text) => (
                <span className="example-chip" key={text} onClick={() => void handleExampleClick(text)}>
                  {text}
                </span>
              ))}
              <a className="recommendation-guide-link" href="/recommendation-guide">
                추천 기준 알아보기 ›
              </a>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export default HomeHero;
