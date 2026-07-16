import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { runAgentEntryMessage } from "../lib/agentRecommendationSearch";
import type { RecommendationProfile, SearchMode } from "../types/recommendation";
import type { CatalogSearchItem, CatalogSuggestionItem } from "../types/product";

type HeaderSearchPanelProps = {
  onClose: () => void;
  profile: RecommendationProfile;
};

const getSuggestionLabel = (suggestion: CatalogSuggestionItem) => {
  if (suggestion.type === "PRODUCT") return "상품";
  if (suggestion.type === "BRAND") return "브랜드";
  if (suggestion.type === "CATEGORY") return "카테고리";
  return "추천 검색어";
};

function HeaderSearchPanel({ onClose, profile }: HeaderSearchPanelProps) {
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("general");
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<CatalogSuggestionItem[]>([]);
  const [results, setResults] = useState<CatalogSearchItem[]>([]);
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  const [isResultsLoading, setIsResultsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isAgentSubmitting, setIsAgentSubmitting] = useState(false);
  const [hasSubmitted, setHasSubmitted] = useState(false);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

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
    const handlePointerDown = (event: PointerEvent) => {
      if (event.target instanceof Element && event.target.closest("[data-header-search-toggle]")) return;
      if (!panelRef.current?.contains(event.target as Node)) onClose();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const selectMode = (nextMode: SearchMode) => {
    setSearchMode(nextMode);
    setIsModeMenuOpen(false);
    setSuggestions([]);
    setResults([]);
    setErrorMessage("");
    setHasSubmitted(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const runGeneralSearch = async (nextQuery = query) => {
    const normalized = nextQuery.trim();
    if (!normalized || isResultsLoading) return;

    setIsResultsLoading(true);
    setErrorMessage("");
    setSuggestions([]);
    setHasSubmitted(true);
    try {
      const response = await api.searchCatalog({
        query: normalized,
        page: 1,
        pageSize: 8,
        sort: "relevance"
      });
      setResults(response.items);
    } catch {
      setResults([]);
      setErrorMessage("검색 결과를 불러오지 못했습니다.");
    } finally {
      setIsResultsLoading(false);
    }
  };

  const runAiSearch = async () => {
    const normalized = query.trim();
    if (!normalized || isAgentSubmitting) return;

    setIsAgentSubmitting(true);
    try {
      await runAgentEntryMessage(normalized, profile);
      onClose();
    } catch {
      setErrorMessage("AI 추천을 준비하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsAgentSubmitting(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (searchMode === "general") {
      void runGeneralSearch();
      return;
    }
    void runAiSearch();
  };

  const selectSuggestion = (suggestion: CatalogSuggestionItem) => {
    if (suggestion.type === "PRODUCT" && suggestion.product_id) {
      onClose();
      navigate(`/product-detail?id=${encodeURIComponent(suggestion.product_id)}`);
      return;
    }
    setQuery(suggestion.text);
    void runGeneralSearch(suggestion.text);
  };

  const openProductDetail = (productId: string) => {
    onClose();
    navigate(`/product-detail?id=${encodeURIComponent(productId)}`);
  };

  const shouldShowSuggestions = searchMode === "general" && query.trim() && !results.length && !hasSubmitted;
  const shouldShowPanel = shouldShowSuggestions || results.length > 0 || isResultsLoading || Boolean(errorMessage);

  return (
    <div className="header-search-panel" id="header-search-panel" ref={panelRef}>
      <form className="header-search-panel__form" onSubmit={handleSubmit}>
        <div className="header-search-panel__mode">
          <button
            aria-expanded={isModeMenuOpen}
            aria-haspopup="listbox"
            className="header-search-panel__mode-trigger"
            onClick={() => setIsModeMenuOpen((isOpen) => !isOpen)}
            type="button"
          >
            {searchMode === "general" ? "일반 검색" : "AI 추천"}
            <svg aria-hidden="true" fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 12 8" width="12">
              <path d="m1 1 5 5 5-5" />
            </svg>
          </button>
          {isModeMenuOpen ? (
            <div aria-label="검색 방식" className="header-search-panel__mode-menu" role="listbox">
              <button aria-selected={searchMode === "general"} className={searchMode === "general" ? "is-selected" : ""} onClick={() => selectMode("general")} role="option" type="button">일반 검색</button>
              <button aria-selected={searchMode === "ai"} className={searchMode === "ai" ? "is-selected" : ""} onClick={() => selectMode("ai")} role="option" type="button">AI 추천</button>
            </div>
          ) : null}
        </div>
        <input
          aria-label={searchMode === "general" ? "일반 상품 검색" : "AI 추천 검색"}
          autoComplete="off"
          onChange={(event) => {
            setQuery(event.target.value);
            setResults([]);
            setErrorMessage("");
            setHasSubmitted(false);
          }}
          placeholder={searchMode === "general" ? "상품명, 브랜드, 성분을 검색하세요" : "민감하고 붉은기가 자주 올라와요"}
          ref={inputRef}
          type="search"
          value={query}
        />
      </form>

      {shouldShowPanel ? (
        <div className="header-search-panel__results">
          {isSuggestionsLoading && shouldShowSuggestions ? <div className="header-search-panel__state">검색어를 찾고 있어요…</div> : null}
          {!isSuggestionsLoading && shouldShowSuggestions && suggestions.map((suggestion) => (
            <button className="header-search-panel__suggestion" key={`${suggestion.type}-${suggestion.product_id ?? suggestion.text}`} onClick={() => selectSuggestion(suggestion)} type="button">
              <span>{suggestion.text}</span>
              <small>{getSuggestionLabel(suggestion)}</small>
            </button>
          ))}
          {!isSuggestionsLoading && shouldShowSuggestions && suggestions.length === 0 ? <div className="header-search-panel__state">일치하는 검색어가 없습니다.</div> : null}
          {isResultsLoading ? <div className="header-search-panel__state">상품을 찾고 있어요…</div> : null}
          {!isResultsLoading && results.map((item) => (
            <button className="header-search-panel__product" key={item.product_id} onClick={() => openProductDetail(item.product_id)} type="button">
              <span className="header-search-panel__product-copy"><small>{item.brand}</small><strong>{item.name}</strong></span>
              <b>{item.lowest_price === null ? "가격 정보 없음" : `${item.lowest_price.toLocaleString("ko-KR")}원`}</b>
            </button>
          ))}
          {!isResultsLoading && results.length === 0 && errorMessage ? <div className="header-search-panel__state is-error">{errorMessage}</div> : null}
          {!isResultsLoading && results.length === 0 && !errorMessage && !shouldShowSuggestions && searchMode === "general" && query.trim() ? <div className="header-search-panel__state">검색 결과가 없습니다.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

export default HeaderSearchPanel;
