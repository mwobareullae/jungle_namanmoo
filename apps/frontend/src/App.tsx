import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { originalPages, type OriginalPageKey } from "./originalPages";
import CheckoutPage from "./pages/CheckoutPage";
import HomePage from "./pages/HomePage";
import PaymentCompletePage from "./pages/PaymentCompletePage";
import ProductDetailSpaPage from "./pages/ProductDetailSpaPage";
import SearchPage from "./pages/SearchPage";

const appMode = import.meta.env.VITE_APP_MODE === "community" ? "community" : "commerce";
const gaMeasurementId = import.meta.env.VITE_GA_MEASUREMENT_ID;

document.documentElement.dataset.appMode = appMode;

const getCurrentPageKey = (): OriginalPageKey => {
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

function App() {
  const [pageKey, setPageKey] = useState<OriginalPageKey>(() => getCurrentPageKey());
  const visiblePageKey = appMode === "community" && ["checkout", "paymentComplete"].includes(pageKey)
    ? "home"
    : pageKey;
  const page = useMemo(() => originalPages[visiblePageKey], [visiblePageKey]);

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
    document.documentElement.dataset.appMode = appMode;

    document.body.classList.toggle("search-results-page", visiblePageKey === "search");

    const headContainer = document.createElement("div");
    headContainer.innerHTML = page.headHtml;
    Array.from(headContainer.children).forEach((node) => {
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

    return () => {
      injectedNodes.forEach((node) => node.remove());
      document.body.classList.remove("search-results-page");
    };
  }, [page, visiblePageKey]);

  return (
    <main className="spa-origin-shell">
      {visiblePageKey === "home" ? (
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

export default App;
