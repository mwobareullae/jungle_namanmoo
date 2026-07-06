const checkoutStyleHrefs = [
  "/spa-assets/Design_system/aqua-glass-system.css",
  "/spa-assets/Design_system/aqua-glass-shopping.css",
  "/spa-assets/Design_system/aqua-checkout.css",
];

const paymentCompleteStyleHrefs = [
  "/spa-assets/Design_system/aqua-glass-system.css",
  "/spa-assets/Design_system/aqua-glass-shopping.css",
  "/spa-assets/Design_system/aqua-payment-complete.css",
];

const APP_NAVIGATION_STYLE_ATTRIBUTE = "data-app-navigation-style";

const getTargetStyleHrefs = (url: string) => {
  const { pathname } = new URL(url, window.location.origin);

  if (pathname.startsWith("/cart") || pathname.startsWith("/checkout")) {
    return checkoutStyleHrefs;
  }

  if (pathname.startsWith("/payment-complete")) {
    return paymentCompleteStyleHrefs;
  }

  return [];
};

const findLoadedStyleLink = (href: string) => {
  const absoluteHref = new URL(href, window.location.origin).href;
  return Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')).find(
    (link) => link.href === absoluteHref && link.sheet,
  );
};

const loadStyleLink = (href: string) => new Promise<void>((resolve) => {
  const loadedLink = findLoadedStyleLink(href);
  if (loadedLink) {
    resolve();
    return;
  }

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.setAttribute(APP_NAVIGATION_STYLE_ATTRIBUTE, "true");
  link.addEventListener("load", () => resolve(), { once: true });
  link.addEventListener("error", () => resolve(), { once: true });
  document.head.appendChild(link);
});

const loadTargetStyles = async (url: string) => {
  const styleHrefs = getTargetStyleHrefs(url);
  if (styleHrefs.length === 0) return;

  await Promise.all(styleHrefs.map((href) => loadStyleLink(href)));
};

export const navigateWithinApp = async (url: string) => {
  await loadTargetStyles(url);
  window.history.pushState(null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "auto" });
};
