import { DotLottieReact } from "@lottiefiles/dotlottie-react";
import { useEffect, useState } from "react";

const loadingMessage = "필요한 정보를 모아 정리하고 있어요";

const getPrefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function ProductListLoadingState() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(getPrefersReducedMotion);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = () => setPrefersReducedMotion(mediaQuery.matches);

    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  return (
    <div aria-atomic="true" aria-busy="true" aria-live="polite" className="product-list-loading-state" role="status">
      <DotLottieReact
        aria-hidden="true"
        autoplay={!prefersReducedMotion}
        className="product-list-loading-state__animation"
        loop={!prefersReducedMotion}
        src="/animations/loading.lottie"
      />
      <p>{loadingMessage}</p>
    </div>
  );
}

export default ProductListLoadingState;
