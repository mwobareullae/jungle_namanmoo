import type { RecommendationProfile, SearchMode, Sensitivity, SkinType } from "../types/recommendation";

const LEGACY_RECENT_CONCERNS_KEY = "mwobareullae_recent_concerns";
const RECENT_QUERY_KEYS: Record<SearchMode, string> = {
  ai: "mwobareullae_recent_ai_queries",
  general: "mwobareullae_recent_general_queries"
};
const MAX_RECENT_CONCERNS = 3;
let currentSearchMode: SearchMode = "ai";

const fallbackRecentConcerns = [
  "수부지인데 모공과 좁쌀이 고민이에요",
  "민감하고 자주 붉어져요",
  "건조하고 화장이 들떠요"
];

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

const searchProfile = {
  skin: "수부지" as SkinType,
  sensitivity: "보통" as Sensitivity,
  avoidIngredients: [] as string[]
};

type HomeRuntime = Record<string, (...args: unknown[]) => void>;

const getRuntime = () => window as unknown as HomeRuntime;

const escapeHtml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[char] ?? char
  );

const getRecentConcerns = (searchMode: SearchMode = currentSearchMode) => {
  try {
    const raw = localStorage.getItem(RECENT_QUERY_KEYS[searchMode]);
    if (raw === null && searchMode === "ai") {
      const legacyRaw = localStorage.getItem(LEGACY_RECENT_CONCERNS_KEY);
      if (legacyRaw !== null) {
        localStorage.setItem(RECENT_QUERY_KEYS.ai, legacyRaw);
        localStorage.removeItem(LEGACY_RECENT_CONCERNS_KEY);
        return JSON.parse(legacyRaw) as string[];
      }
    }
    if (raw === null) return [];
    const saved = JSON.parse(raw) as unknown;
    return Array.isArray(saved)
      ? saved
          .filter((item): item is string => typeof item === "string")
          .slice(0, MAX_RECENT_CONCERNS)
      : [];
  } catch {
    return [];
  }
};

const saveRecentConcern = (text: string, searchMode: SearchMode = currentSearchMode) => {
  const clean = text.trim();
  if (!clean) return;

  const current = getRecentConcerns(searchMode).filter((item) => item !== clean);
  localStorage.setItem(
    RECENT_QUERY_KEYS[searchMode],
    JSON.stringify([clean, ...current].slice(0, MAX_RECENT_CONCERNS))
  );
};

const buildSearchResultsUrl = (query: string, searchMode = "ai") => {
  const params = new URLSearchParams({
    keyword: query,
    search_mode: searchMode,
    page_size: "10"
  });
  if (searchMode === "ai") {
    params.set("skin_type", searchProfile.skin);
    params.set("sensitivity", searchProfile.sensitivity);
  }

  return `/search?${params.toString()}`;
};

const renderRecentConcerns = (searchMode: SearchMode = currentSearchMode) => {
  const list = document.getElementById("recentConcernList");
  const clearButton = document.getElementById("recentClearButton");
  if (!list) return;

  const concerns = getRecentConcerns(searchMode);
  if (clearButton) clearButton.style.display = concerns.length > 0 ? "inline-flex" : "none";

  if (concerns.length === 0) {
    list.innerHTML = `<div class="recent-empty">${searchMode === "ai" ? "최근 AI 추천이 없습니다" : "최근 검색어가 없습니다"}</div>`;
    return;
  }

  list.innerHTML = concerns
    .map(
      (text) => `
    <div class="recent-item">
      <button class="recent-query" type="button" data-query="${escapeHtml(text)}">
        <svg class="recent-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 3-6.7"/>
          <path d="M3 4v6h6"/>
          <path d="M12 7v5l3 2"/>
        </svg>
        <span class="recent-text">${escapeHtml(text)}</span>
      </button>
      <button class="recent-delete" type="button" data-query="${escapeHtml(text)}" aria-label="최근 고민 삭제">×</button>
    </div>
  `
    )
    .join("");
};

const updateProfileSummary = () => {
  const summary = document.getElementById("profileSummary");
  const chip = document.getElementById("searchProfileChip");
  const label = `${searchProfile.skin} · ${searchProfile.sensitivity}`;

  if (summary)
    summary.textContent = `${searchProfile.skin} · 민감도 ${searchProfile.sensitivity} 기준으로 추천`;
  if (chip) chip.textContent = label;
};

const openSearchSuggestions = () => {
  const panel = document.getElementById("searchSuggestPanel");
  const container = document.querySelector(".search-container");
  if (!panel || !container) return;

  renderRecentConcerns();
  panel.classList.add("active");
  container.classList.add("suggestions-open");
};

const closeSearchSuggestions = () => {
  document.getElementById("searchSuggestPanel")?.classList.remove("active");
  document.querySelector(".search-container")?.classList.remove("suggestions-open");
};

const goToSearchResultsPage = (query: string, searchMode: SearchMode = "ai") => {
  saveRecentConcern(query, searchMode);
  closeSearchSuggestions();
  window.location.href = buildSearchResultsUrl(query, searchMode);
};

const updateSearchInput = (query: string) => {
  const inputElement = document.getElementById("searchInput") as HTMLInputElement | null;
  if (inputElement) inputElement.value = query;
  window.dispatchEvent(
    new CustomEvent("home-search-input-change", {
      detail: { query }
    })
  );
};

const showToast = (message: string) => {
  const toast = document.getElementById("toast");
  const toastMessage = document.getElementById("toastMsg");
  if (!toast || !toastMessage) return;

  toastMessage.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2500);
};

const renderDefaultEmptyState = () => {
  const grid = document.getElementById("defaultProductGrid");
  if (!grid || grid.children.length > 0) return;
  grid.innerHTML = '<div class="empty-state">추천 검색을 시작하면 상품이 표시됩니다.</div>';
};

const getHeaderBottom = () => {
  const header = document.querySelector(".home-header, .site-header, .auth-site-header, header");
  const headerBottom = header?.getBoundingClientRect().bottom;
  return typeof headerBottom === "number" ? Math.max(0, headerBottom - 1) : 64;
};

const CATEGORY_PANEL_MIN_HEIGHT = 160;
const CATEGORY_PANEL_MAX_HEIGHT = 520;
let categoryMenuScrollY = 0;

const lockCategoryMenuScroll = () => {
  if (document.body.classList.contains("category-menu-open")) return;
  categoryMenuScrollY = window.scrollY;
};

const unlockCategoryMenuScroll = () => {
  window.scrollTo(0, categoryMenuScrollY);
};

const updateCategoryPanelLayout = (panel: HTMLElement) => {
  const headerBottom = getHeaderBottom();
  const availableHeight = Math.min(
    window.innerHeight - headerBottom - 24,
    CATEGORY_PANEL_MAX_HEIGHT
  );

  document.documentElement.style.setProperty("--category-panel-top", `${headerBottom}px`);
  document.documentElement.style.setProperty("--category-panel-left", "0px");
  panel.style.setProperty("--category-panel-width", "100vw");
  panel.style.removeProperty("--category-panel-height");
  panel.style.setProperty(
    "--category-panel-max-height",
    `${Math.max(CATEGORY_PANEL_MIN_HEIGHT, availableHeight)}px`
  );
};

const isCategoryMenuArea = (target: EventTarget | null) => {
  if (!(target instanceof Node)) return false;

  const header = document.querySelector("header.site-header");
  const panel = document.getElementById("categoryPanel");

  return Boolean(header?.contains(target) || panel?.contains(target));
};

const installFunctions = () => {
  const runtime = getRuntime();

  runtime.saveRecentConcern = (text) => {
    saveRecentConcern(String(text), "ai");
    renderRecentConcerns("ai");
  };

  runtime.toggleCart = () => {
    document.getElementById("cartSidebar")?.classList.toggle("active");
    document.getElementById("cartOverlay")?.classList.toggle("active");
  };
  runtime.closeCategoryMenu = () => {
    const wasOpen = document.body.classList.contains("category-menu-open");
    document.getElementById("categoryPanel")?.classList.remove("active");
    document.getElementById("categoryPanelBackdrop")?.classList.remove("active");
    document.body.classList.remove("category-menu-open");
    if (wasOpen) unlockCategoryMenuScroll();
    document.querySelector(".category-menu-btn")?.setAttribute("aria-expanded", "false");
  };
  runtime.openCategoryMenu = () => {
    const panel = document.getElementById("categoryPanel");
    const backdrop = document.getElementById("categoryPanelBackdrop");
    const button = document.querySelector(".category-menu-btn");

    if (panel) updateCategoryPanelLayout(panel);
    lockCategoryMenuScroll();

    panel?.classList.add("active");
    backdrop?.classList.add("active");
    document.body.classList.add("category-menu-open");
    button?.setAttribute("aria-expanded", "true");
  };
  runtime.toggleCategoryMenu = () => {
    const panel = document.getElementById("categoryPanel");
    const backdrop = document.getElementById("categoryPanelBackdrop");
    const button = document.querySelector(".category-menu-btn");
    const willOpen = !panel?.classList.contains("active");

    if (willOpen) {
      runtime.openCategoryMenu();
      return;
    }

    const wasOpen = document.body.classList.contains("category-menu-open");
    panel?.classList.remove("active");
    backdrop?.classList.remove("active");
    document.body.classList.remove("category-menu-open");
    if (wasOpen) unlockCategoryMenuScroll();
    button?.setAttribute("aria-expanded", "false");
  };
  runtime.showToast = (message) => showToast(String(message));
  runtime.openSearchSuggestions = openSearchSuggestions;
  runtime.setSearchMode = (mode) => {
    currentSearchMode = mode === "general" ? "general" : "ai";
    renderRecentConcerns(currentSearchMode);
  };
  runtime.closeSearchSuggestions = closeSearchSuggestions;
  runtime.focusSearch = () => {
    const input = document.getElementById("searchInput");
    if (!input) {
      window.location.href = "/";
      return;
    }

    input.focus();
    openSearchSuggestions();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  runtime.clearRecentConcerns = (event) => {
    (event as Event | undefined)?.stopPropagation();
    localStorage.setItem(RECENT_QUERY_KEYS[currentSearchMode], JSON.stringify([]));
    renderRecentConcerns();
  };
  runtime.selectProfileOption = (profile, value) => {
    const profileKey = String(profile) as "skin" | "sensitivity";
    const nextValue = String(value);
    if (profileKey === "skin" && skinTypes.includes(nextValue as SkinType)) {
      searchProfile.skin = nextValue as SkinType;
    }
    if (profileKey === "sensitivity" && sensitivities.includes(nextValue as Sensitivity)) {
      searchProfile.sensitivity = nextValue as Sensitivity;
    }
    document.querySelectorAll(`.profile-option[data-profile="${profileKey}"]`).forEach((button) => {
      button.classList.toggle("active", (button as HTMLElement).dataset.value === value);
    });
    updateProfileSummary();
  };
  runtime.setSearch = (text) => {
    const query = String(text);
    const input = document.getElementById("searchInput") as HTMLInputElement | null;
    if (input) input.value = query;
    goToSearchResultsPage(query, "ai");
  };
  runtime.doSearch = (mode) => {
    const input = document.getElementById("searchInput") as HTMLInputElement | null;
    const query = input?.value.trim() || fallbackRecentConcerns[0];
    goToSearchResultsPage(query, mode === "general" ? "general" : "ai");
  };
  runtime.handleSearch = (event) => {
    if ((event as KeyboardEvent).key === "Enter") runtime.doSearch();
  };
  runtime.filterCat = (element) => {
    document.querySelectorAll(".cat-tab").forEach((tab) => tab.classList.remove("active"));
    (element as HTMLElement | undefined)?.classList.add("active");
    renderDefaultEmptyState();
  };
};

export const installHomeRuntime = (initialProfile?: RecommendationProfile) => {
  if (initialProfile) {
    searchProfile.skin = initialProfile.skin;
    searchProfile.sensitivity = initialProfile.sensitivity;
    searchProfile.avoidIngredients = initialProfile.avoidIngredients;
  }

  installFunctions();
  renderRecentConcerns(currentSearchMode);
  updateProfileSummary();
  renderDefaultEmptyState();

  const input = document.getElementById("searchInput");
  const searchContainer = document.querySelector(".search-container");
  const categoryMenuTrigger = document.querySelector(".category-menu-btn");
  const categoryMenuHoverArea = document.querySelector("header.site-header");
  const categoryPanel = document.getElementById("categoryPanel");

  const handleInputFocus = () => openSearchSuggestions();
  const handleDocumentClick = (event: Event) => {
    if (searchContainer && !searchContainer.contains(event.target as Node))
      closeSearchSuggestions();
  };
  const handleCategoryMenuEnter = () => getRuntime().openCategoryMenu();
  const handleCategoryMenuLeave = (event: Event) => {
    if (!isCategoryMenuArea((event as MouseEvent).relatedTarget)) {
      getRuntime().closeCategoryMenu();
    }
  };
  const handleDocumentKeydown = (event: Event) => {
    if ((event as KeyboardEvent).key === "Escape") {
      getRuntime().closeCategoryMenu();
      closeSearchSuggestions();
    }
  };
  const handleRecentClick = (event: Event) => {
    const target = event.target as HTMLElement;
    const queryButton = target.closest<HTMLButtonElement>(".recent-query");
    const deleteButton = target.closest<HTMLButtonElement>(".recent-delete");

    if (deleteButton?.dataset.query) {
      event.stopPropagation();
      localStorage.setItem(
        RECENT_QUERY_KEYS[currentSearchMode],
        JSON.stringify(getRecentConcerns(currentSearchMode).filter((item) => item !== deleteButton.dataset.query))
      );
      renderRecentConcerns();
      return;
    }

    if (queryButton?.dataset.query) {
      updateSearchInput(queryButton.dataset.query);
      openSearchSuggestions();
    }
  };
  const handleCategoryPanelViewportChange = () => {
    if (categoryPanel?.classList.contains("active")) updateCategoryPanelLayout(categoryPanel);
  };

  input?.addEventListener("focus", handleInputFocus);
  input?.addEventListener("click", handleInputFocus);
  categoryMenuTrigger?.addEventListener("mouseenter", handleCategoryMenuEnter);
  categoryMenuHoverArea?.addEventListener("mouseleave", handleCategoryMenuLeave);
  categoryPanel?.addEventListener("mouseleave", handleCategoryMenuLeave);
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleDocumentKeydown);
  window.addEventListener("resize", handleCategoryPanelViewportChange);
  window.addEventListener("scroll", handleCategoryPanelViewportChange, { passive: true });
  document.getElementById("recentConcernList")?.addEventListener("click", handleRecentClick);
  categoryPanel
    ?.querySelectorAll("a")
    .forEach((link) => link.addEventListener("click", getRuntime().closeCategoryMenu));

  return () => {
    input?.removeEventListener("focus", handleInputFocus);
    input?.removeEventListener("click", handleInputFocus);
    categoryMenuTrigger?.removeEventListener("mouseenter", handleCategoryMenuEnter);
    categoryMenuHoverArea?.removeEventListener("mouseleave", handleCategoryMenuLeave);
    categoryPanel?.removeEventListener("mouseleave", handleCategoryMenuLeave);
    document.removeEventListener("click", handleDocumentClick);
    document.removeEventListener("keydown", handleDocumentKeydown);
    window.removeEventListener("resize", handleCategoryPanelViewportChange);
    window.removeEventListener("scroll", handleCategoryPanelViewportChange);
    document.getElementById("recentConcernList")?.removeEventListener("click", handleRecentClick);
    document.body.classList.remove("category-menu-open");
    unlockCategoryMenuScroll();
    categoryPanel
      ?.querySelectorAll("a")
      .forEach((link) => link.removeEventListener("click", getRuntime().closeCategoryMenu));
  };
};
