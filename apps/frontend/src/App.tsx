import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { originalPages, type OriginalPageKey } from "./originalPages";
import CheckoutPage from "./pages/CheckoutPage";
import HomePage from "./pages/HomePage";
import PaymentCompletePage from "./pages/PaymentCompletePage";
import ProductDetailSpaPage from "./pages/ProductDetailSpaPage";
import SearchPage from "./pages/SearchPage";

const appMode = import.meta.env.VITE_APP_MODE === "community" ? "community" : "commerce";
const gaMeasurementId = import.meta.env.VITE_GA_MEASUREMENT_ID;

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
