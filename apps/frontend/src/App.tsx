import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { originalPages, type OriginalPageKey } from "./originalPages";
import CheckoutPage from "./pages/CheckoutPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import PaymentCompletePage from "./pages/PaymentCompletePage";
import PasswordResetPage from "./pages/PasswordResetPage";
import ProductDetailSpaPage from "./pages/ProductDetailSpaPage";
import SearchPage from "./pages/SearchPage";
import SignupInfoPage from "./pages/SignupInfoPage";
import SignupSkinProfilePage from "./pages/SignupSkinProfilePage";
import SignupTermsPage from "./pages/SignupTermsPage";

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
  const page = useMemo(() => originalPages[visiblePageKey], [visiblePageKey]);
  const isPageStyleReady = !needsStyleGate(visiblePageKey) || styleReadyKey === visiblePageKey;

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
        z-index: 120 !important;
      }

      .main-content {
        position: relative !important;
        z-index: 1 !important;
      }

      .search-container,
      .search-container.suggestions-open {
        position: relative !important;
        z-index: 600 !important;
      }

      .search-suggest-panel {
        z-index: 620 !important;
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
      {!isPageStyleReady ? null : visiblePageKey === "home" ? (
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

// 새 화면(/login, /signup, /signup/info)만 React Router로 연결하고, 나머지 기존 화면은 LegacyApp이 그대로 처리.
function App() {
  return (
    <Routes>
      {appMode !== "community" && <Route path="/login" element={<LoginPage />} />}
      {appMode !== "community" && <Route path="/password-reset" element={<PasswordResetPage />} />}
      {appMode !== "community" && <Route path="/signup" element={<SignupTermsPage />} />}
      {appMode !== "community" && <Route path="/signup/info" element={<SignupInfoPage />} />}
      {appMode !== "community" && <Route path="/signup/skin-profile" element={<SignupSkinProfilePage />} />}
      <Route path="*" element={<LegacyApp />} />
    </Routes>
  );
}

export default App;
