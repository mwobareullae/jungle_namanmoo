import { useEffect, useMemo, useState } from "react";
import AppHeader from "./components/AppHeader";
import { api } from "./lib/api";
import AnalysisLoadingPage from "./pages/AnalysisLoadingPage";
import ConcernInputPage from "./pages/ConcernInputPage";
import HomePage from "./pages/HomePage";
import ProductDetailPage from "./pages/ProductDetailPage";
import ProductNotFoundPage from "./pages/ProductNotFoundPage";
import RecommendationResultsPage from "./pages/RecommendationResultsPage";
import type {
  ApiError,
  ProductDetail,
  RecommendationRequest,
  RecommendationResponse,
  Sensitivity,
  SkinType
} from "./types/recommendation";

type Route =
  | { name: "home"; community: boolean }
  | { name: "search"; request: RecommendationRequest; page: number; recommendationId?: string }
  | { name: "product"; productId: string; recommendationId?: string }
  | { name: "checkout"; productId?: string; recommendationId?: string; mode?: string }
  | { name: "paymentComplete" }
  | { name: "notFound" };

const initialRequest: RecommendationRequest = {
  skin_type: "수부지",
  sensitivity: "보통",
  avoid_ingredients: [],
  concern_text: ""
};

const pageSize = 10;
const minimumLoadingMs = 450;
const skinTypes: SkinType[] = ["건성", "지성", "복합성", "수부지", "중성"];
const sensitivities: Sensitivity[] = ["낮음", "보통", "높음"];

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const isApiError = (error: unknown): error is ApiError => {
  if (!error || typeof error !== "object") {
    return false;
  }

  const candidate = error as Partial<ApiError>;
  return typeof candidate.status === "number" && typeof candidate.message === "string";
};

const normalizeSkinType = (value: string | null): SkinType =>
  skinTypes.includes(value as SkinType) ? (value as SkinType) : initialRequest.skin_type;

const normalizeSensitivity = (value: string | null): Sensitivity =>
  sensitivities.includes(value as Sensitivity) ? (value as Sensitivity) : initialRequest.sensitivity;

const parsePositiveInt = (value: string | null, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
};

const getAppModeFromEnv = () => {
  const envMode = import.meta.env.VITE_APP_MODE;
  return typeof envMode === "string" && envMode.toLowerCase() === "community"
    ? "community"
    : "commerce";
};

const parseRoute = (location: Location): Route => {
  const { pathname, search } = location;
  const params = new URLSearchParams(search);

  if (pathname === "/" || pathname === "/community") {
    return { name: "home", community: pathname === "/community" || getAppModeFromEnv() === "community" };
  }

  if (pathname === "/search") {
    return {
      name: "search",
      request: {
        skin_type: normalizeSkinType(params.get("skin_type")),
        sensitivity: normalizeSensitivity(params.get("sensitivity")),
        avoid_ingredients: [],
        concern_text: params.get("keyword") ?? params.get("concern_text") ?? ""
      },
      page: parsePositiveInt(params.get("page"), 1),
      recommendationId: params.get("recommendation_id") || undefined
    };
  }

  const productMatch = pathname.match(/^\/products\/([^/]+)$/);
  if (productMatch) {
    return {
      name: "product",
      productId: decodeURIComponent(productMatch[1]),
      recommendationId: params.get("recommendation_id") || undefined
    };
  }

  if (pathname === "/checkout") {
    return {
      name: "checkout",
      productId: params.get("id") || undefined,
      recommendationId: params.get("recommendation_id") || undefined,
      mode: params.get("mode") || undefined
    };
  }

  if (pathname === "/payment-complete") {
    return { name: "paymentComplete" };
  }

  return { name: "notFound" };
};

const legacyPathToSpaPath = (location: Location) => {
  const params = new URLSearchParams(location.search);
  const pathname = location.pathname;

  if (pathname.endsWith("/beauty-commerce-aqua-glass.html") || pathname.endsWith("/index.html")) {
    return "/";
  }

  if (pathname.endsWith("/beauty-commerce-search.html")) {
    return `/search${location.search}`;
  }

  if (pathname.endsWith("/beauty-commerce-product-detail.html")) {
    const productId = params.get("id");
    if (!productId) return "/";
    const nextParams = new URLSearchParams();
    const recommendationId = params.get("recommendation_id");
    if (recommendationId) nextParams.set("recommendation_id", recommendationId);
    const query = nextParams.toString();
    return `/products/${encodeURIComponent(productId)}${query ? `?${query}` : ""}`;
  }

  if (pathname.endsWith("/beauty-commerce-checkout.html")) {
    return `/checkout${location.search}`;
  }

  if (pathname.endsWith("/beauty-commerce-payment-complete.html")) {
    return "/payment-complete";
  }

  return null;
};

const buildSearchPath = (
  request: RecommendationRequest,
  page = 1,
  recommendationId?: string
) => {
  const params = new URLSearchParams({
    keyword: request.concern_text.trim(),
    skin_type: request.skin_type,
    sensitivity: request.sensitivity,
    page_size: String(pageSize)
  });

  if (page > 1) params.set("page", String(page));
  if (recommendationId) params.set("recommendation_id", recommendationId);

  return `/search?${params.toString()}`;
};

const applyNarrativeToProduct = (product: ProductDetail, narrative: ProductDetail["narrative"]) => {
  if (!narrative) return product;

  const explanation = narrative.product_explanations.find((item) => item.product_id === product.product_id);

  return {
    ...product,
    narrative,
    reason_summary: explanation?.card.reason ?? product.reason_summary,
    evidence_tags: explanation?.card.chips.length ? explanation.card.chips : product.evidence_tags
  };
};

function SearchRoute({
  route,
  onNavigate,
  onOpenProduct
}: {
  route: Extract<Route, { name: "search" }>;
  onNavigate: (path: string, mode?: "push" | "replace") => void;
  onOpenProduct: (productId: string, recommendationId?: string) => void;
}) {
  const [request, setRequest] = useState<RecommendationRequest>(route.request);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const keyword = route.request.concern_text.trim();

  useEffect(() => {
    setRequest(route.request);
  }, [route.request.concern_text, route.request.sensitivity, route.request.skin_type]);

  useEffect(() => {
    if (!keyword) {
      setRecommendation(null);
      setIsLoading(false);
      setErrorMessage(null);
      return;
    }

    let isActive = true;
    setIsLoading(true);
    setErrorMessage(null);

    const load = async () => {
      try {
        const [response] = await Promise.all([
          route.recommendationId
            ? api.getRecommendation(route.recommendationId, route.page, pageSize)
            : api.createRecommendation(route.request, route.page, pageSize),
          wait(minimumLoadingMs)
        ]);

        if (!isActive) return;
        setRecommendation(response);
        setErrorMessage(null);

        if (!route.recommendationId) {
          onNavigate(buildSearchPath(route.request, route.page, response.recommendation_id), "replace");
        }
      } catch (error) {
        if (!isActive) return;
        setRecommendation(null);
        setErrorMessage(
          isApiError(error)
            ? error.message
            : "분석에 실패했어요. 입력값은 보존했으니 다시 시도해주세요."
        );
      } finally {
        if (isActive) setIsLoading(false);
      }
    };

    void load();

    return () => {
      isActive = false;
    };
  }, [keyword, route.page, route.recommendationId]);

  const submitSearch = () => {
    const concernText = request.concern_text.trim();
    if (!concernText) {
      setErrorMessage("피부 고민을 입력해주세요.");
      return;
    }

    onNavigate(buildSearchPath({ ...request, concern_text: concernText }));
  };

  if (!keyword) {
    return (
      <ConcernInputPage
        value={request}
        isSubmitting={false}
        errorMessage={errorMessage}
        onChange={(nextValue) => {
          setRequest(nextValue);
          setErrorMessage(null);
        }}
        onSubmit={submitSearch}
      />
    );
  }

  if (isLoading) {
    return (
      <AnalysisLoadingPage
        request={route.request}
        isLoading={isLoading}
        errorMessage={null}
        onRetry={() => onNavigate(buildSearchPath(route.request, route.page, route.recommendationId), "replace")}
        onEdit={() => onNavigate("/search")}
      />
    );
  }

  if (errorMessage || !recommendation) {
    return (
      <AnalysisLoadingPage
        request={route.request}
        isLoading={false}
        errorMessage={errorMessage}
        onRetry={() => onNavigate(buildSearchPath(route.request, route.page, route.recommendationId), "replace")}
        onEdit={() => onNavigate("/search")}
      />
    );
  }

  return (
    <RecommendationResultsPage
      recommendation={recommendation}
      onOpenProduct={(productId) => onOpenProduct(productId, recommendation.recommendation_id)}
      onRestart={() => onNavigate("/search")}
      onPageChange={(page) => onNavigate(buildSearchPath(route.request, page, recommendation.recommendation_id))}
    />
  );
}

function ProductRoute({
  route,
  isCommerceMode,
  onNavigate
}: {
  route: Extract<Route, { name: "product" }>;
  isCommerceMode: boolean;
  onNavigate: (path: string) => void;
}) {
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isMissing, setIsMissing] = useState(false);

  useEffect(() => {
    let isActive = true;
    setIsLoading(true);
    setIsMissing(false);

    const load = async () => {
      try {
        const [detail, narrative] = await Promise.all([
          api.getProduct(route.productId, route.recommendationId),
          route.recommendationId
            ? api.getRecommendationNarrative(route.recommendationId).catch(() => null)
            : Promise.resolve(null)
        ]);

        if (!isActive) return;
        setProduct(applyNarrativeToProduct(detail, narrative));
      } catch {
        if (!isActive) return;
        setProduct(null);
        setIsMissing(true);
      } finally {
        if (isActive) setIsLoading(false);
      }
    };

    void load();

    return () => {
      isActive = false;
    };
  }, [route.productId, route.recommendationId]);

  if (isLoading) {
    return <div className="wrap empty-box">상품 정보를 불러오는 중입니다.</div>;
  }

  if (isMissing || !product) {
    return <ProductNotFoundPage onBack={() => onNavigate("/search")} />;
  }

  return (
    <ProductDetailPage
      product={product}
      isCommerceMode={isCommerceMode}
      onBack={() => onNavigate(route.recommendationId ? `/search?recommendation_id=${route.recommendationId}` : "/search")}
    />
  );
}

function CheckoutPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <section className="wrap checkout-page">
      <p className="eyebrow">Checkout</p>
      <h1 className="section-title">체크아웃</h1>
      <p className="muted-copy">결제 기능은 커머스 버전에서 연결됩니다.</p>
      <button className="primary-button" type="button" onClick={() => onNavigate("/")}>홈으로</button>
    </section>
  );
}

function PaymentCompletePage({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <section className="wrap checkout-page">
      <p className="eyebrow">Payment Complete</p>
      <h1 className="section-title">결제 완료</h1>
      <p className="muted-copy">결제 완료 화면은 커머스 버전에서 사용됩니다.</p>
      <button className="primary-button" type="button" onClick={() => onNavigate("/")}>홈으로</button>
    </section>
  );
}

function App() {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location));
  const isCommunityMode = useMemo(
    () => route.name === "home" ? route.community : getAppModeFromEnv() === "community",
    [route]
  );
  const isCommerceMode = !isCommunityMode;

  const navigate = (path: string, mode: "push" | "replace" = "push") => {
    if (mode === "replace") {
      window.history.replaceState({}, "", path);
    } else {
      window.history.pushState({}, "", path);
    }
    setRoute(parseRoute(window.location));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    const canonicalPath = legacyPathToSpaPath(window.location);
    if (canonicalPath) {
      navigate(canonicalPath, "replace");
    }

    const handlePopState = () => {
      setRoute(parseRoute(window.location));
      window.scrollTo({ top: 0, behavior: "auto" });
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const openProduct = (productId: string, recommendationId?: string) => {
    const params = new URLSearchParams();
    if (recommendationId) params.set("recommendation_id", recommendationId);
    const query = params.toString();
    navigate(`/products/${encodeURIComponent(productId)}${query ? `?${query}` : ""}`);
  };

  return (
    <main className={isCommunityMode ? "app-shell community-mode" : "app-shell commerce-mode"}>
      <AppHeader apiBaseUrl={apiBaseUrl} isCommunityMode={isCommunityMode} onNavigate={navigate} />

      {route.name === "home" ? (
        <HomePage
          onSearch={(concernText = "") => {
            if (!concernText) {
              navigate("/search");
              return;
            }
            navigate(buildSearchPath({ ...initialRequest, concern_text: concernText }));
          }}
          onOpenProduct={openProduct}
        />
      ) : null}

      {route.name === "search" ? (
        <SearchRoute route={route} onNavigate={navigate} onOpenProduct={openProduct} />
      ) : null}

      {route.name === "product" ? (
        <ProductRoute route={route} isCommerceMode={isCommerceMode} onNavigate={navigate} />
      ) : null}

      {route.name === "checkout" ? <CheckoutPage onNavigate={navigate} /> : null}

      {route.name === "paymentComplete" ? <PaymentCompletePage onNavigate={navigate} /> : null}

      {route.name === "notFound" ? <ProductNotFoundPage onBack={() => navigate("/")} /> : null}
    </main>
  );
}

export default App;
