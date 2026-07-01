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

const fetchedStyleHrefs = new Set<string>();

const getTargetStyleHrefs = (url: string) => {
  const { pathname } = new URL(url, window.location.origin);

  if (pathname.startsWith("/checkout")) {
    return checkoutStyleHrefs;
  }

  if (pathname.startsWith("/payment-complete")) {
    return paymentCompleteStyleHrefs;
  }

  return [];
};

const warmTargetStyles = async (url: string) => {
  const styleHrefs = getTargetStyleHrefs(url).filter((href) => !fetchedStyleHrefs.has(href));
  if (styleHrefs.length === 0) return;

  await Promise.allSettled(
    styleHrefs.map(async (href) => {
      const response = await fetch(href, { cache: "force-cache" });
      if (response.ok) {
        fetchedStyleHrefs.add(href);
      }
    }),
  );
};

export const navigateWithinApp = async (url: string) => {
  await warmTargetStyles(url);
  window.history.pushState(null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "auto" });
};
