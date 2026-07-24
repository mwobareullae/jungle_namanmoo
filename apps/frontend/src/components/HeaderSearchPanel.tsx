import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { runAgentEntryMessage } from "../lib/agentRecommendationSearch";
import type { RecommendationProfile, SearchMode } from "../types/recommendation";

type HeaderSearchPanelProps = {
  onClose: () => void;
  profile: RecommendationProfile;
};

function HeaderSearchPanel({ onClose, profile }: HeaderSearchPanelProps) {
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("general");
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isAgentSubmitting, setIsAgentSubmitting] = useState(false);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

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
    setErrorMessage("");
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const runGeneralSearch = () => {
    const normalized = query.trim();
    if (!normalized) return;

    onClose();
    navigate(`/catalog-search?q=${encodeURIComponent(normalized)}`);
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

  const submitActiveMode = () => {
    if (searchMode === "general") {
      runGeneralSearch();
      return;
    }
    void runAiSearch();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitActiveMode();
  };

  const handleInputKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    submitActiveMode();
  };

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
            setErrorMessage("");
          }}
          onKeyDown={handleInputKeyDown}
          placeholder={searchMode === "general" ? "상품명, 브랜드, 성분을 검색하세요" : "민감하고 붉은기가 자주 올라와요"}
          ref={inputRef}
          type="search"
          value={query}
        />
      </form>

      {errorMessage ? (
        <div className="header-search-panel__results">
          <div className="header-search-panel__state is-error">{errorMessage}</div>
        </div>
      ) : null}
    </div>
  );
}

export default HeaderSearchPanel;
