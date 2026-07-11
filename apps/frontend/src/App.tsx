import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import AgentFloatingButton from "./components/AgentFloatingButton";
import AppFooter from "./components/AppFooter";
import HomeHeader from "./components/HomeHeader";
import PopularProductsHeader from "./components/PopularProductsHeader";
import Skeleton from "./components/ui/Skeleton";
import { getSavedSkinProfile } from "./lib/profileApi";
import type { OriginalPageKey } from "./originalPages";

const AdminDashboardPage = lazy(() => import("./pages/AdminDashboardPage"));
const BrandPage = lazy(() => import("./pages/BrandPage"));
const CartPage = lazy(() => import("./pages/CartPage"));
const CategoryPage = lazy(() => import("./pages/CategoryPage"));
const CheckoutPage = lazy(() => import("./pages/CheckoutPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const MyPageShell = lazy(() => import("./pages/mypage/MyPageShell"));
const MyPageSettings = lazy(() => import("./pages/mypage/MyPageSettings"));
const OrderDetail = lazy(() => import("./pages/mypage/OrderDetail"));
const OrderList = lazy(() => import("./pages/mypage/OrderList"));
const PaymentCompletePage = lazy(() => import("./pages/PaymentCompletePage"));
const PopularProductsPage = lazy(() => import("./pages/PopularProductsPage"));
const PasswordResetPage = lazy(() => import("./pages/PasswordResetPage"));
const ProductDetailSpaPage = lazy(() => import("./pages/ProductDetailSpaPage"));
const RecommendationGuidePage = lazy(() => import("./pages/RecommendationGuidePage"));
const SearchPage = lazy(() => import("./pages/SearchPage"));
const SkinProfile = lazy(() => import("./pages/mypage/SkinProfile"));
const SkinTestPage = lazy(() => import("./pages/SkinTestPage"));
const SkinTestRecommendationsPage = lazy(() => import("./pages/SkinTestRecommendationsPage"));
const SkinTestResultPage = lazy(() => import("./pages/SkinTestResultPage"));
const SignupInfoPage = lazy(() => import("./pages/SignupInfoPage"));
const SignupSkinProfilePage = lazy(() => import("./pages/SignupSkinProfilePage"));
const SignupTermsPage = lazy(() => import("./pages/SignupTermsPage"));
const WishList = lazy(() => import("./pages/mypage/WishList"));
const RecentProducts = lazy(() =>
  import("./pages/mypage/WishList").then((module) => ({ default: module.RecentProducts })),
);

const appMode = import.meta.env.VITE_APP_MODE === "community" ? "community" : "commerce";
const gaMeasurementId = import.meta.env.VITE_GA_MEASUREMENT_ID;

document.documentElement.dataset.appMode = appMode;

const gatedStylePageKeys: OriginalPageKey[] = ["checkout", "paymentComplete"];

const needsStyleGate = (pageKey: OriginalPageKey) => gatedStylePageKeys.includes(pageKey);

const getCurrentPageKey = (): OriginalPageKey => { // 주소 보고 이름표 붙이기
  const { pathname } = window.location;

  if (pathname.startsWith("/search")) {
    return "search";
  }

  if (pathname.startsWith("/product-detail")) {
    return "productDetail";
  }

  if (pathname.startsWith("/checkout")) {
    return "checkout";
  }

  if (pathname.startsWith("/payment-complete")) {
    return "paymentComplete";
  }

  return "home";
};

// /login이 아닌 모든 경로를 처리하는 기존 로직. 별도 컴포넌트로 분리해서
// 아래 훅들이 /login에서는 아예 실행되지 않게 함(불필요한 스타일/스크립트 주입 방지).
function LegacyApp() {
  const [originalPagesMap, setOriginalPagesMap] = useState<
    typeof import("./originalPages").originalPages | null
  >(null);
  const [pageKey, setPageKey] = useState<OriginalPageKey>(() => getCurrentPageKey());
  const visiblePageKey = appMode === "community" && ["checkout", "paymentComplete"].includes(pageKey)
    ? "home"
    : pageKey;
  const [styleReadyKey, setStyleReadyKey] = useState<OriginalPageKey | null>(() => {
    const initialPageKey = getCurrentPageKey();
    const initialVisiblePageKey = appMode === "community" && ["checkout", "paymentComplete"].includes(initialPageKey)
      ? "home"
      : initialPageKey;
    return needsStyleGate(initialVisiblePageKey) ? null : initialVisiblePageKey;
  });
  const page = useMemo(() => originalPagesMap?.[visiblePageKey] ?? null, [originalPagesMap, visiblePageKey]);
  const isPageStyleReady = !needsStyleGate(visiblePageKey) || styleReadyKey === visiblePageKey;

  useEffect(() => {
    let isMounted = true;

    import("./originalPages").then((module) => {
      if (isMounted) {
        setOriginalPagesMap(module.originalPages);
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (appMode === "community" && visiblePageKey !== pageKey) {
      window.history.replaceState(null, "", "/");
    }
  }, [pageKey, visiblePageKey]);

  useEffect(() => {
    const handleNavigation = () => setPageKey(getCurrentPageKey());

    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, []);

  useLayoutEffect(() => {
    if (!page) {
      return;
    }

    const injectedNodes: HTMLElement[] = [];
    const styleLoadPromises: Promise<void>[] = [];
    let isActive = true;
    document.documentElement.dataset.appMode = appMode;

    document.body.classList.toggle("search-results-page", visiblePageKey === "search");

    const headContainer = document.createElement("div");
    headContainer.innerHTML = page.headHtml;
    Array.from(headContainer.children).forEach((node) => {
      if (node instanceof HTMLLinkElement && node.rel === "stylesheet") {
        const href = new URL(node.getAttribute("href") ?? "", window.location.origin).href;
        const existingLink = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')).find(
          (link) => link.href === href && link.sheet,
        );

        if (existingLink) {
          return;
        }

        styleLoadPromises.push(new Promise((resolve) => {
          node.addEventListener("load", () => resolve(), { once: true });
          node.addEventListener("error", () => resolve(), { once: true });
        }));
      }

      document.head.appendChild(node);
      injectedNodes.push(node as HTMLElement);
    });

    const backgroundReset = document.createElement("style");
    backgroundReset.textContent = `
      html,
      body,
      #root,
      .spa-origin-shell {
        background: #ffffff !important;
      }

      .ingredient-stat-grid,
      .ingredient-stat {
        display: none !important;
      }

      .hero {
        position: relative !important;
        z-index: 20 !important;
      }

      .main-content {
        position: relative !important;
        z-index: 1 !important;
      }

      .search-container,
      .search-container.suggestions-open {
        position: relative !important;
        z-index: 40 !important;
      }

      .search-suggest-panel {
        z-index: 90 !important;
      }

      header.site-header {
        z-index: 1200 !important;
      }

      body .category-panel-backdrop {
        inset: var(--category-panel-top, 64px) 0 0 !important;
        z-index: 900 !important;
        display: block !important;
        background: transparent !important;
        opacity: 0 !important;
        pointer-events: none !important;
      }

      body .category-panel-backdrop.active {
        opacity: 1 !important;
        pointer-events: auto !important;
      }

      body .category-panel {
        position: fixed !important;
        top: var(--category-panel-top, 65px) !important;
        left: 0 !important;
        z-index: 910 !important;
        display: block !important;
        width: 100vw !important;
        height: var(--category-panel-height, 380px) !important;
        box-sizing: border-box !important;
        max-height: var(--category-panel-max-height, 520px) !important;
        overflow-y: auto !important;
        padding: 34px clamp(28px, 5vw, 72px) 38px !important;
        border: 1px solid rgba(11, 42, 58, 0.08) !important;
        border-right: 0 !important;
        border-left: 0 !important;
        border-top: 0 !important;
        border-radius: 0 !important;
        background: #ffffff !important;
        box-shadow: 0 18px 38px rgba(11, 42, 58, 0.12) !important;
        color: var(--ink) !important;
        opacity: 0 !important;
        pointer-events: none !important;
        transform: translateY(-8px) !important;
        transform-origin: top left !important;
        transition: opacity 160ms ease, transform 160ms ease !important;
      }

      body .category-panel.active {
        opacity: 1 !important;
        pointer-events: auto !important;
        transform: translateY(0) !important;
      }

      body:has(header.site-header .category-menu-btn:hover) .category-panel,
      body:has(.category-panel:hover) .category-panel {
        opacity: 1 !important;
        pointer-events: auto !important;
        transform: translateY(0) !important;
      }

      body .category-panel__inner {
        display: grid !important;
        grid-template-columns: repeat(5, minmax(180px, 1fr)) !important;
        gap: 26px clamp(32px, 4vw, 72px) !important;
        align-items: start !important;
        align-content: start !important;
        justify-items: stretch !important;
        width: min(1680px, calc(100vw - clamp(72px, 10vw, 168px))) !important;
        min-height: 100% !important;
        margin: 0 auto !important;
      }

      body .category-panel__column {
        display: grid !important;
        grid-template-rows: 164px auto !important;
        gap: 18px !important;
        align-content: start !important;
        justify-items: stretch !important;
        min-width: 0 !important;
      }

      body .category-panel__section {
        display: grid !important;
        justify-items: start !important;
        gap: 10px !important;
        min-width: 0 !important;
      }

      body .category-panel__column .category-panel__section:first-child {
        min-height: 0 !important;
      }

      body .category-panel__title,
      body .category-panel__title:hover,
      body .category-panel__title:focus-visible {
        display: inline-flex !important;
        width: auto !important;
        justify-self: start !important;
        min-height: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        color: var(--ink) !important;
        font-size: 18px !important;
        font-weight: 600 !important;
        line-height: 1.28 !important;
        text-align: left !important;
        text-decoration: none !important;
        white-space: nowrap !important;
      }

      body .category-panel__links {
        display: grid !important;
        grid-template-columns: repeat(2, max-content) !important;
        gap: 8px 24px !important;
        width: max-content !important;
        min-width: 0 !important;
        justify-content: start !important;
        padding-left: 0 !important;
      }

      body .category-panel__links a,
      body .category-panel__links a:hover,
      body .category-panel__links a:focus-visible {
        display: inline-flex !important;
        width: auto !important;
        justify-self: start !important;
        min-height: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        color: var(--ink2) !important;
        font-size: 16px !important;
        font-weight: 400 !important;
        line-height: 1.42 !important;
        text-align: left !important;
        text-decoration: none !important;
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
      }

      @media (max-width: 1180px) {
        body .category-panel__inner {
          grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
          gap: 22px 28px !important;
        }

        body .category-panel__column .category-panel__section:first-child {
          min-height: 0 !important;
        }
      }

      @media (max-width: 960px) {
        body .category-panel {
          padding: 32px 32px 36px !important;
        }

        body .category-panel__inner {
          grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
          gap: 22px 26px !important;
          width: 100% !important;
        }

        body .category-panel__column {
          grid-template-rows: auto auto !important;
          gap: 22px !important;
        }

        body .category-panel__links {
          grid-template-columns: 1fr !important;
          gap: 6px !important;
          width: 100% !important;
          padding-left: 0 !important;
        }

        body .category-panel__title {
          font-size: 14px !important;
          white-space: normal !important;
        }

        body .category-panel__links a,
        body .category-panel__links a:hover,
        body .category-panel__links a:focus-visible {
          font-size: 13px !important;
          white-space: normal !important;
          word-break: keep-all !important;
          overflow-wrap: anywhere !important;
        }
      }

      @media (max-width: 700px) {
        body .category-panel {
          left: 0 !important;
          width: 100vw !important;
          height: auto !important;
          max-height: calc(100vh - var(--category-panel-top, 64px)) !important;
          padding: 28px 24px 32px !important;
        }

        body .category-panel__inner {
          grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
          gap: 22px 18px !important;
          width: 100% !important;
        }

        body .category-panel__column {
          grid-template-rows: auto auto !important;
          gap: 18px !important;
        }

        body .category-panel__links {
          grid-template-columns: 1fr !important;
          width: 100% !important;
        }
      }

      @media (max-width: 560px) {
        body .category-panel {
          left: 0 !important;
          width: 100vw !important;
          padding: 26px 20px 30px !important;
        }

        body .category-panel__inner {
          grid-template-columns: 1fr !important;
          gap: 18px !important;
        }

        body .category-panel__links {
          grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
          column-gap: 16px !important;
        }
      }

      .search-results-panel .sort-select {
        flex: 0 0 auto !important;
        min-width: 188px !important;
        min-height: 46px !important;
        padding: 0 46px 0 18px !important;
        border: 1.5px solid #dfe6ea !important;
        border-radius: 12px !important;
        background-color: #ffffff !important;
        background-image: linear-gradient(45deg, transparent 50%, #3d3d3d 50%),
          linear-gradient(135deg, #3d3d3d 50%, transparent 50%) !important;
        background-position: calc(100% - 22px) 50%, calc(100% - 16px) 50% !important;
        background-repeat: no-repeat !important;
        background-size: 7px 7px, 7px 7px !important;
        color: var(--ink2) !important;
        font-family: inherit !important;
        font-size: 14px !important;
        font-weight: 700 !important;
        line-height: 1 !important;
        appearance: none !important;
      }

      #searchResultsGrid > .search-loading-state {
        grid-column: 1 / -1 !important;
        width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
      }

      #searchResultsGrid .search-loading-state .product-skeleton.search {
        display: grid !important;
        grid-template-columns: 168px minmax(0, 1fr) 168px !important;
        gap: 24px !important;
        align-items: center !important;
        width: 100% !important;
        min-width: 0 !important;
        min-height: 214px !important;
        overflow: hidden !important;
        padding: 22px !important;
        border-bottom: 1px solid #e8eef1 !important;
        background: #ffffff !important;
      }

      #searchResultsGrid .search-loading-state .product-skeleton-media {
        width: 168px !important;
        aspect-ratio: 1 !important;
        background: #edf3f5 !important;
        animation: none !important;
        transform: none !important;
      }

      #searchResultsGrid .search-loading-state .product-skeleton-media::before,
      #searchResultsGrid .search-loading-state .product-skeleton-media::after {
        content: none !important;
        display: none !important;
      }

      #searchResultsGrid .search-loading-state .product-skeleton-body,
      #searchResultsGrid .search-loading-state .product-skeleton-side {
        min-width: 0 !important;
      }

      @media (max-width: 760px) {
        #searchResultsGrid .search-loading-state .product-skeleton.search {
          grid-template-columns: 96px minmax(0, 1fr) !important;
          gap: 16px !important;
          min-height: 180px !important;
          padding: 18px !important;
        }

        #searchResultsGrid .search-loading-state .product-skeleton-media {
          width: 96px !important;
        }
      }

      body.search-results-page #searchResultsGrid .search-skeleton {
        display: grid !important;
        width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        background: #ffffff !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-card {
        display: grid !important;
        grid-template-columns: 168px minmax(0, 1fr) 168px !important;
        gap: 24px !important;
        align-items: center !important;
        min-width: 0 !important;
        min-height: 214px !important;
        padding: 22px !important;
        border-bottom: 1px solid #e8eef1 !important;
        background: #ffffff !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-card:last-child {
        border-bottom: 0 !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-media {
        width: 168px !important;
        aspect-ratio: 1 !important;
        border-radius: var(--rs) !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-body,
      body.search-results-page #searchResultsGrid .skeleton-side {
        display: grid !important;
        align-content: center !important;
        gap: 12px !important;
        min-width: 0 !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-side {
        min-height: 150px !important;
        justify-items: end !important;
        border-left: 1px solid #eef2f4 !important;
        padding-left: 20px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-media,
      body.search-results-page #searchResultsGrid .skeleton-line,
      body.search-results-page #searchResultsGrid .skeleton-pill,
      body.search-results-page #searchResultsGrid .skeleton-price {
        position: static !important;
        overflow: hidden !important;
        background: #edf3f5 !important;
        animation: skeleton-soft-pulse 1.25s ease-in-out infinite !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-media {
        animation: none !important;
        transform: none !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-media::after,
      body.search-results-page #searchResultsGrid .skeleton-line::after,
      body.search-results-page #searchResultsGrid .skeleton-pill::after,
      body.search-results-page #searchResultsGrid .skeleton-price::after {
        content: none !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-line.brand {
        width: 72px !important;
        height: 12px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-line.title {
        width: min(420px, 82%) !important;
        height: 18px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-line.reason {
        width: min(560px, 96%) !important;
        height: 14px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-tags {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 8px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-pill {
        width: 74px !important;
        height: 28px !important;
      }

      body.search-results-page #searchResultsGrid .skeleton-price {
        width: 96px !important;
        height: 22px !important;
      }

      @keyframes skeleton-soft-pulse {
        0%, 100% { opacity: 0.72; }
        50% { opacity: 1; }
      }

      @media (max-width: 760px) {
        body.search-results-page #searchResultsGrid .skeleton-card {
          grid-template-columns: 96px minmax(0, 1fr) !important;
          min-height: 180px !important;
          gap: 16px !important;
          padding: 18px !important;
        }

        body.search-results-page #searchResultsGrid .skeleton-media {
          width: 96px !important;
        }

        body.search-results-page #searchResultsGrid .skeleton-side {
          grid-column: 1 / -1 !important;
          min-height: auto !important;
          justify-items: start !important;
          border-left: 0 !important;
          border-top: 1px solid #eef2f4 !important;
          padding-top: 14px !important;
          padding-left: 0 !important;
        }
      }

      #searchResultsGrid .search-skeleton {
        display: grid !important;
        width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        background: #ffffff !important;
      }

      #searchResultsGrid .skeleton-card {
        display: grid !important;
        grid-template-columns: 168px minmax(0, 1fr) 168px !important;
        gap: 24px !important;
        align-items: center !important;
        min-width: 0 !important;
        min-height: 214px !important;
        padding: 22px !important;
        border-bottom: 1px solid #e8eef1 !important;
        background: #ffffff !important;
      }

      #searchResultsGrid .skeleton-media {
        width: 168px !important;
        aspect-ratio: 1 !important;
        border-radius: var(--rs) !important;
        background: #edf3f5 !important;
        animation: none !important;
        transform: none !important;
      }

      #searchResultsGrid .skeleton-media::before,
      #searchResultsGrid .skeleton-media::after {
        content: none !important;
        display: none !important;
        animation: none !important;
        transform: none !important;
      }

      #searchResultsGrid .skeleton-body,
      #searchResultsGrid .skeleton-side {
        display: grid !important;
        align-content: center !important;
        gap: 12px !important;
        min-width: 0 !important;
      }

      #searchResultsGrid .skeleton-side {
        min-height: 150px !important;
        justify-items: end !important;
        border-left: 1px solid #eef2f4 !important;
        padding-left: 20px !important;
      }

      #searchResultsGrid .skeleton-line,
      #searchResultsGrid .skeleton-pill,
      #searchResultsGrid .skeleton-price {
        position: static !important;
        overflow: hidden !important;
        background: #edf3f5 !important;
        animation: skeleton-soft-pulse 1.25s ease-in-out infinite !important;
      }

      #searchResultsGrid .skeleton-line::after,
      #searchResultsGrid .skeleton-pill::after,
      #searchResultsGrid .skeleton-price::after {
        content: none !important;
        display: none !important;
      }

      #searchResultsGrid .skeleton-line.brand {
        width: 72px !important;
        height: 12px !important;
      }

      #searchResultsGrid .skeleton-line.title {
        width: min(420px, 82%) !important;
        height: 18px !important;
      }

      #searchResultsGrid .skeleton-line.reason {
        width: min(560px, 96%) !important;
        height: 14px !important;
      }

      #searchResultsGrid .skeleton-tags {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 8px !important;
      }

      #searchResultsGrid .skeleton-pill {
        width: 74px !important;
        height: 28px !important;
      }

      #searchResultsGrid .skeleton-price {
        width: 96px !important;
        height: 22px !important;
      }

      @media (max-width: 760px) {
        #searchResultsGrid .skeleton-card {
          grid-template-columns: 96px minmax(0, 1fr) !important;
          min-height: 180px !important;
          gap: 16px !important;
          padding: 18px !important;
        }

        #searchResultsGrid .skeleton-media {
          width: 96px !important;
        }

        #searchResultsGrid .skeleton-side {
          grid-column: 1 / -1 !important;
          min-height: auto !important;
          justify-items: start !important;
          border-left: 0 !important;
          border-top: 1px solid #eef2f4 !important;
          padding-top: 14px !important;
          padding-left: 0 !important;
        }
      }
    `;
    document.head.appendChild(backgroundReset);
    injectedNodes.push(backgroundReset);

    if (gaMeasurementId) {
      const gaScript = document.createElement("script");
      gaScript.async = true;
      gaScript.src = `https://www.googletagmanager.com/gtag/js?id=${gaMeasurementId}`;
      document.head.appendChild(gaScript);
      injectedNodes.push(gaScript);

      const gaInlineScript = document.createElement("script");
      gaInlineScript.textContent = `
        window.dataLayer = window.dataLayer || [];
        function gtag(){dataLayer.push(arguments);}
        gtag('js', new Date());
        gtag('config', '${gaMeasurementId}', { page_path: window.location.pathname + window.location.search });
      `;
      document.head.appendChild(gaInlineScript);
      injectedNodes.push(gaInlineScript);
    }

    if (!["home", "search", "productDetail", "checkout", "paymentComplete"].includes(visiblePageKey)) {
      window.setTimeout(() => {
        page.scripts.forEach((scriptText) => {
          const script = document.createElement("script");
          script.textContent = scriptText;
          document.body.appendChild(script);
          injectedNodes.push(script);
        });
      }, 0);
    }

    if (needsStyleGate(visiblePageKey)) {
      Promise.all(styleLoadPromises).then(() => {
        if (isActive) {
          setStyleReadyKey(visiblePageKey);
        }
      });
    }

    return () => {
      isActive = false;
      injectedNodes.forEach((node) => node.remove());
      document.body.classList.remove("search-results-page");
    };
  }, [page, visiblePageKey]);

  return (
    <main className="spa-origin-shell">
      {!page || !isPageStyleReady ? null : visiblePageKey === "home" ? (
        <HomePage bodyHtml={page.bodyHtml} />
      ) : visiblePageKey === "search" ? (
        <SearchPage />
      ) : visiblePageKey === "productDetail" ? (
        <ProductDetailSpaPage />
      ) : visiblePageKey === "checkout" ? (
        <CheckoutPage />
      ) : visiblePageKey === "paymentComplete" ? (
        <PaymentCompletePage />
      ) : (
        <div
          className="spa-origin-section"
          dangerouslySetInnerHTML={{ __html: page.bodyHtml }}
        />
      )}
    </main>
  );
}

function GlobalAgentEntry() {
  const location = useLocation();
  const [hasSavedSkinProfile, setHasSavedSkinProfile] = useState(false);
  const [isSkinProfileResolved, setIsSkinProfileResolved] = useState(false);

  const hasTemporarySkinProfile = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return Boolean(params.get("skin_type") && params.get("sensitivity"));
  }, [location.search]);

  useEffect(() => {
    let isMounted = true;

    getSavedSkinProfile().then((profile) => {
      if (isMounted) {
        setHasSavedSkinProfile(Boolean(profile));
        setIsSkinProfileResolved(true);
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

  if (appMode === "community" || location.pathname.startsWith("/admin")) {
    return null;
  }

  const skinProfileStatus = hasSavedSkinProfile
    ? "saved"
    : hasTemporarySkinProfile
      ? "temporary"
      : isSkinProfileResolved
        ? "empty"
        : "empty";

  return (
    <AgentFloatingButton
      skinProfileStatus={skinProfileStatus}
      surface={location.pathname.startsWith("/product-detail") ? "productDetail" : "home"}
    />
  );
}

function GlobalFooter() {
  const location = useLocation();

  if (location.pathname === "/") {
    return null;
  }

  return <AppFooter />;
}

function RouteLoadingFallback() {
  return <div className="detail-loading">페이지를 불러오는 중입니다.</div>;
}

function PopularProductsRouteFallback() {
  return (
    <>
      <HomeHeader />
      <main className="popular-products-page popular-products-route-fallback" aria-label="인기상품 페이지 불러오는 중">
        <section className="popular-products-shell">
          <PopularProductsHeader category="" windowDays={7} />
          <div className="popular-products-grid" aria-hidden="true">
            {Array.from({ length: 10 }, (_, index) => (
              <article className="popular-product-card popular-product-card--skeleton" key={index}>
                <Skeleton className="popular-product-card__image" />
                <div className="popular-product-card__skeleton-body">
                  <Skeleton className="popular-product-card__brand" />
                  <Skeleton className="popular-product-card__name" />
                  <Skeleton className="popular-product-card__price" />
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>
    </>
  );
}

// 새 화면(/login, /signup, /signup/info)만 React Router로 연결하고, 나머지 기존 화면은 LegacyApp이 그대로 처리.
function App() {
  return (
    <>
      <Suspense fallback={<RouteLoadingFallback />}>
        <Routes>
          {appMode !== "community" && <Route path="/login" element={<LoginPage />} />}
          {appMode !== "community" && <Route path="/password-reset" element={<PasswordResetPage />} />}
          {appMode !== "community" && <Route path="/signup" element={<SignupTermsPage />} />}
          {appMode !== "community" && <Route path="/signup/info" element={<SignupInfoPage />} />}
          {appMode !== "community" && <Route path="/signup/skin-profile" element={<SignupSkinProfilePage />} />}
          {appMode !== "community" && <Route path="/mypage" element={<MyPageShell />} />}
          {appMode !== "community" && <Route path="/mypage/skin-profile" element={<SkinProfile />} />}
          {appMode !== "community" && <Route path="/mypage/wishlist" element={<WishList />} />}
          {appMode !== "community" && <Route path="/mypage/recent" element={<RecentProducts />} />}
          {appMode !== "community" && <Route path="/mypage/orders" element={<OrderList />} />}
          {appMode !== "community" && <Route path="/mypage/orders/:orderCode" element={<OrderDetail />} />}
          {appMode !== "community" && <Route path="/mypage/settings" element={<MyPageSettings />} />}
          {appMode !== "community" && <Route path="/skin-test" element={<SkinTestPage />} />}
          {appMode !== "community" && <Route path="/skin-test/result" element={<SkinTestResultPage />} />}
          {appMode !== "community" && <Route path="/skin-test/recommendations" element={<SkinTestRecommendationsPage />} />}
          {appMode !== "community" && <Route path="/admin" element={<AdminDashboardPage />} />}
          {appMode !== "community" && <Route path="/brand/:brandName" element={<BrandPage />} />}
          {appMode !== "community" && <Route path="/category/:categoryTitle" element={<CategoryPage />} />}
          {appMode !== "community" && <Route path="/cart" element={<CartPage />} />}
          <Route
            path="/products/popular"
            element={(
              <Suspense fallback={<PopularProductsRouteFallback />}>
                <PopularProductsPage />
              </Suspense>
            )}
          />
          <Route path="/recommendation-guide" element={<RecommendationGuidePage />} />
          <Route path="*" element={<LegacyApp />} />
        </Routes>
      </Suspense>
      <GlobalFooter />
      <GlobalAgentEntry />
    </>
  );
}

export default App;
