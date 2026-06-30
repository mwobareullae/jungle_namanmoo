import type { Sensitivity, SkinType } from "../types/recommendation";

const RECENT_CONCERNS_KEY = "mwobareullae_recent_concerns";
const MAX_RECENT_CONCERNS = 3;

const fallbackRecentConcerns = [
  "수부지인데 모공과 좁쌀이 고민이에요",
  "민감하고 자주 붉어져요",
  "건조하고 화장이 들떠요",
];

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

const searchProfile = {
  skin: "수부지" as SkinType,
  sensitivity: "보통" as Sensitivity,
};

type SearchProfile = {
  skin: SkinType;
  sensitivity: Sensitivity;
};

type HomeRuntime = Record<string, (...args: unknown[]) => void>;

const getRuntime = () => window as unknown as HomeRuntime;

const escapeHtml = (value: string) =>
  value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[char] ?? char);

const getRecentConcerns = () => {
  try {
    const raw = localStorage.getItem(RECENT_CONCERNS_KEY);
    if (raw === null) return [];
    const saved = JSON.parse(raw) as unknown;
    return Array.isArray(saved) ? saved.filter((item): item is string => typeof item === "string").slice(0, MAX_RECENT_CONCERNS) : [];
  } catch {
    return [];
  }
};

const saveRecentConcern = (text: string) => {
  const clean = text.trim();
  if (!clean) return;

  const current = getRecentConcerns().filter((item) => item !== clean);
  localStorage.setItem(RECENT_CONCERNS_KEY, JSON.stringify([clean, ...current].slice(0, MAX_RECENT_CONCERNS)));
};

const buildSearchResultsUrl = (query: string) => {
  const params = new URLSearchParams({
    keyword: query,
    skin_type: searchProfile.skin,
    sensitivity: searchProfile.sensitivity,
    page_size: "10",
  });

  return `/search?${params.toString()}`;
};

const renderRecentConcerns = () => {
  const list = document.getElementById("recentConcernList");
  const clearButton = document.getElementById("recentClearButton");
  if (!list) return;

  const concerns = getRecentConcerns();
  if (clearButton) clearButton.style.display = concerns.length > 0 ? "inline-flex" : "none";

  if (concerns.length === 0) {
    list.innerHTML = '<div class="recent-empty">최근 고민이 없습니다</div>';
    return;
  }

  list.innerHTML = concerns.map((text) => `
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
  `).join("");
};

const updateProfileSummary = () => {
  const summary = document.getElementById("profileSummary");
  const chip = document.getElementById("searchProfileChip");
  const label = `${searchProfile.skin} · ${searchProfile.sensitivity}`;

  if (summary) summary.textContent = `${searchProfile.skin} · 민감도 ${searchProfile.sensitivity} 기준으로 추천`;
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

const goToSearchResultsPage = (query: string) => {
  saveRecentConcern(query);
  closeSearchSuggestions();
  window.location.href = buildSearchResultsUrl(query);
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

const installFunctions = () => {
  const runtime = getRuntime();

  runtime.toggleCart = () => {
    document.getElementById("cartSidebar")?.classList.toggle("active");
    document.getElementById("cartOverlay")?.classList.toggle("active");
  };
  runtime.closeCategoryMenu = () => {
    document.getElementById("categoryPanel")?.classList.remove("active");
    document.getElementById("categoryPanelBackdrop")?.classList.remove("active");
    document.querySelector(".category-menu-btn")?.setAttribute("aria-expanded", "false");
  };
  runtime.toggleCategoryMenu = () => {
    const panel = document.getElementById("categoryPanel");
    const backdrop = document.getElementById("categoryPanelBackdrop");
    const button = document.querySelector(".category-menu-btn");
    const willOpen = !panel?.classList.contains("active");

    panel?.classList.toggle("active", willOpen);
    backdrop?.classList.toggle("active", willOpen);
    button?.setAttribute("aria-expanded", willOpen ? "true" : "false");
  };
  runtime.showToast = (message) => showToast(String(message));
  runtime.openSearchSuggestions = openSearchSuggestions;
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
    localStorage.setItem(RECENT_CONCERNS_KEY, JSON.stringify([]));
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
    goToSearchResultsPage(query);
  };
  runtime.doSearch = () => {
    const input = document.getElementById("searchInput") as HTMLInputElement | null;
    const query = input?.value.trim() || fallbackRecentConcerns[0];
    goToSearchResultsPage(query);
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

export const installHomeRuntime = (initialProfile?: SearchProfile) => {
  if (initialProfile) {
    searchProfile.skin = initialProfile.skin;
    searchProfile.sensitivity = initialProfile.sensitivity;
  }

  installFunctions();
  renderRecentConcerns();
  updateProfileSummary();
  renderDefaultEmptyState();

  const input = document.getElementById("searchInput");
  const searchContainer = document.querySelector(".search-container");
  const categoryPanel = document.getElementById("categoryPanel");

  const handleInputFocus = () => openSearchSuggestions();
  const handleDocumentClick = (event: Event) => {
    if (searchContainer && !searchContainer.contains(event.target as Node)) closeSearchSuggestions();
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
      localStorage.setItem(RECENT_CONCERNS_KEY, JSON.stringify(getRecentConcerns().filter((item) => item !== deleteButton.dataset.query)));
      renderRecentConcerns();
      return;
    }

    if (queryButton?.dataset.query) {
      const inputElement = document.getElementById("searchInput") as HTMLInputElement | null;
      if (inputElement) inputElement.value = queryButton.dataset.query;
      openSearchSuggestions();
    }
  };

  input?.addEventListener("focus", handleInputFocus);
  input?.addEventListener("click", handleInputFocus);
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleDocumentKeydown);
  document.getElementById("recentConcernList")?.addEventListener("click", handleRecentClick);
  categoryPanel?.querySelectorAll("a").forEach((link) => link.addEventListener("click", getRuntime().closeCategoryMenu));

  return () => {
    input?.removeEventListener("focus", handleInputFocus);
    input?.removeEventListener("click", handleInputFocus);
    document.removeEventListener("click", handleDocumentClick);
    document.removeEventListener("keydown", handleDocumentKeydown);
    document.getElementById("recentConcernList")?.removeEventListener("click", handleRecentClick);
    categoryPanel?.querySelectorAll("a").forEach((link) => link.removeEventListener("click", getRuntime().closeCategoryMenu));
  };
};
