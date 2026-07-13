type OriginalRuntime = Record<string, (...args: unknown[]) => void>;

const CATEGORY_PANEL_MIN_HEIGHT = 160;
const CATEGORY_PANEL_DEFAULT_HEIGHT = 380;
const CATEGORY_PANEL_MAX_HEIGHT = 520;
let categoryMenuScrollY = 0;

const lockCategoryMenuScroll = () => {
  if (document.body.classList.contains("category-menu-open")) return;
  categoryMenuScrollY = window.scrollY;
};

const unlockCategoryMenuScroll = () => {
  window.scrollTo(0, categoryMenuScrollY);
};

const getHeaderBottom = () => {
  const header = document.querySelector(
    "header.site-header, .home-header, .auth-site-header, header"
  );
  const headerBottom = header?.getBoundingClientRect().bottom;
  return typeof headerBottom === "number" ? Math.max(0, headerBottom - 1) : 64;
};

const updateCategoryPanelLayout = (panel: HTMLElement) => {
  const headerBottom = getHeaderBottom();
  const contentHeight = panel.scrollHeight;
  const availableHeight = Math.min(
    Math.max(CATEGORY_PANEL_DEFAULT_HEIGHT, contentHeight),
    window.innerHeight - headerBottom - 24,
    CATEGORY_PANEL_MAX_HEIGHT
  );

  document.documentElement.style.setProperty("--category-panel-top", `${headerBottom}px`);
  document.documentElement.style.setProperty("--category-panel-left", "0px");
  panel.style.setProperty("--category-panel-width", "100vw");
  panel.style.setProperty(
    "--category-panel-height",
    `${Math.max(CATEGORY_PANEL_MIN_HEIGHT, availableHeight)}px`
  );
  panel.style.setProperty(
    "--category-panel-max-height",
    `${Math.max(CATEGORY_PANEL_MIN_HEIGHT, availableHeight)}px`
  );
};

const openCategoryMenuFallback = () => {
  const panel = document.getElementById("categoryPanel");
  const backdrop = document.getElementById("categoryPanelBackdrop");
  const button = document.querySelector(".category-menu-btn");

  if (panel) updateCategoryPanelLayout(panel);

  panel?.classList.add("active");
  backdrop?.classList.add("active");
  lockCategoryMenuScroll();
  document.body.classList.add("category-menu-open");
  button?.setAttribute("aria-expanded", "true");
};

const closeCategoryMenuFallback = () => {
  const wasOpen = document.body.classList.contains("category-menu-open");
  document.getElementById("categoryPanel")?.classList.remove("active");
  document.getElementById("categoryPanelBackdrop")?.classList.remove("active");
  document.body.classList.remove("category-menu-open");
  if (wasOpen) unlockCategoryMenuScroll();
  document.querySelector(".category-menu-btn")?.setAttribute("aria-expanded", "false");
};

const fallbackHandlers: OriginalRuntime = {
  closeCategoryMenu: closeCategoryMenuFallback,
  openCategoryMenu: openCategoryMenuFallback,
  toggleCategoryMenu: () => {
    const panel = document.getElementById("categoryPanel");

    if (panel?.classList.contains("active")) {
      closeCategoryMenuFallback();
      return;
    }

    openCategoryMenuFallback();
  }
};

export const callOriginal = (name: string, ...args: unknown[]) => {
  const handler = (window as unknown as OriginalRuntime)[name] ?? fallbackHandlers[name];
  handler?.(...args);
};
