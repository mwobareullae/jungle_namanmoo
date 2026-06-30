import { useEffect, useMemo, useState } from "react";
import { originalPages, type OriginalPageKey } from "./originalPages";

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
  const page = useMemo(() => originalPages[pageKey], [pageKey]);

  useEffect(() => {
    const handleNavigation = () => setPageKey(getCurrentPageKey());

    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, []);

  useEffect(() => {
    const injectedNodes: HTMLElement[] = [];
    document.documentElement.dataset.appMode =
      import.meta.env.VITE_APP_MODE === "community" ? "community" : "commerce";

    document.body.classList.toggle("search-results-page", pageKey === "search");

    const headContainer = document.createElement("div");
    headContainer.innerHTML = page.headHtml;
    Array.from(headContainer.children).forEach((node) => {
      document.head.appendChild(node);
      injectedNodes.push(node as HTMLElement);
    });

    window.setTimeout(() => {
      page.scripts.forEach((scriptText) => {
        const script = document.createElement("script");
        script.textContent = scriptText;
        document.body.appendChild(script);
        injectedNodes.push(script);
      });
    }, 0);

    return () => {
      injectedNodes.forEach((node) => node.remove());
      document.body.classList.remove("search-results-page");
    };
  }, [page, pageKey]);

  return (
    <main
      className="spa-origin-shell"
      dangerouslySetInnerHTML={{ __html: page.bodyHtml }}
    />
  );
}

export default App;
