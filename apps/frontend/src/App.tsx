import { useEffect, useRef, useState } from "react";
import AppHeader from "./components/AppHeader";
import { api } from "./lib/api";
import AnalysisLoadingPage from "./pages/AnalysisLoadingPage";
import ConcernInputPage from "./pages/ConcernInputPage";
import ProductDetailPage from "./pages/ProductDetailPage";
import ProductNotFoundPage from "./pages/ProductNotFoundPage";
import RecommendationResultsPage from "./pages/RecommendationResultsPage";
import type {
  ProductDetail,
  RecommendationRequest,
  RecommendationResponse
} from "./types/recommendation";

type View = "input" | "loading" | "results" | "detail" | "notFound";

type AppHistoryState = {
  app: "mubareullae";
  view: View;
  productId?: string;
};

const initialRequest: RecommendationRequest = {
  skin_type: "수부지",
  sensitivity: "보통",
  avoid_ingredients: [],
  concern_text: ""
};

const minimumLoadingMs = 3200;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const writeHistoryState = (
  view: View,
  mode: "push" | "replace",
  productId?: string
) => {
  const state: AppHistoryState = {
    app: "mubareullae",
    view,
    ...(productId ? { productId } : {})
  };

  if (mode === "replace") {
    window.history.replaceState(state, "", window.location.href);
    return;
  }

  window.history.pushState(state, "", window.location.href);
};

const isAppHistoryState = (value: unknown): value is AppHistoryState => {
  if (!value || typeof value !== "object") {
    return false;
  }

  const state = value as Partial<AppHistoryState>;
  return state.app === "mubareullae" && typeof state.view === "string";
};

const logRecommendationRequest = (
  rawRequest: RecommendationRequest,
  nextRequest: RecommendationRequest
) => {
  console.groupCollapsed("[mubareullae] recommendation request");
  console.table({
    skin_type: nextRequest.skin_type,
    sensitivity: nextRequest.sensitivity,
    concern_text_raw: rawRequest.concern_text,
    concern_text_trimmed: nextRequest.concern_text,
    is_concern_text_trimmed: rawRequest.concern_text !== nextRequest.concern_text
  });
  console.groupEnd();
};

function App() {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
  const [view, setView] = useState<View>("input");
  const [request, setRequest] = useState<RecommendationRequest>(initialRequest);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [selectedProduct, setSelectedProduct] = useState<ProductDetail | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [analysisRunId, setAnalysisRunId] = useState(0);
  const recommendationRef = useRef<RecommendationResponse | null>(null);
  const restoreRequestIdRef = useRef(0);
  const submissionRequestIdRef = useRef(0);

  useEffect(() => {
    recommendationRef.current = recommendation;
  }, [recommendation]);

  useEffect(() => {
    writeHistoryState("input", "replace");

    const restoreView = async (state: unknown) => {
      restoreRequestIdRef.current += 1;
      submissionRequestIdRef.current += 1;
      const restoreRequestId = restoreRequestIdRef.current;

      setErrorMessage(null);
      setIsSubmitting(false);

      if (!isAppHistoryState(state)) {
        setSelectedProduct(null);
        setView("input");
        return;
      }

      if (state.view === "detail" && state.productId) {
        try {
          const product = await api.getProduct(
            state.productId,
            recommendationRef.current?.recommendation_id
          );

          if (restoreRequestIdRef.current !== restoreRequestId) {
            return;
          }

          setSelectedProduct(product);
          setView("detail");
        } catch {
          if (restoreRequestIdRef.current !== restoreRequestId) {
            return;
          }

          setSelectedProduct(null);
          setView("notFound");
        }
        return;
      }

      if (state.view === "results") {
        setSelectedProduct(null);
        setView(recommendationRef.current ? "results" : "input");
        return;
      }

      if (state.view === "loading") {
        setSelectedProduct(null);
        setView(recommendationRef.current ? "results" : "input");
        return;
      }

      setSelectedProduct(null);
      setView(state.view);
    };

    const handlePopState = (event: PopStateEvent) => {
      void restoreView(event.state);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const startRecommendation = async () => {
    if (isSubmitting) {
      return;
    }

    const concernText = request.concern_text.trim();
    if (concernText.length === 0) {
      setErrorMessage("피부 고민을 입력해주세요.");
      return;
    }

    const nextRequest = {
      ...request,
      concern_text: concernText
    };

    logRecommendationRequest(request, nextRequest);

    setRequest(nextRequest);
    setErrorMessage(null);
    setIsSubmitting(true);
    setAnalysisRunId((currentId) => currentId + 1);
    setView("loading");
    const submissionRequestId = submissionRequestIdRef.current + 1;
    submissionRequestIdRef.current = submissionRequestId;
    writeHistoryState("loading", view === "loading" ? "replace" : "push");

    try {
      const [response] = await Promise.all([
        api.createRecommendation(nextRequest),
        wait(minimumLoadingMs)
      ]);

      if (submissionRequestIdRef.current !== submissionRequestId) {
        return;
      }

      setRecommendation(response);
      setView("results");
      writeHistoryState("results", "replace");
    } catch {
      if (submissionRequestIdRef.current === submissionRequestId) {
        setErrorMessage("분석에 실패했어요. 입력값은 보존했으니 다시 시도해주세요.");
      }
    } finally {
      if (submissionRequestIdRef.current === submissionRequestId) {
        setIsSubmitting(false);
      }
    }
  };

  const openProduct = async (productId: string) => {
    setErrorMessage(null);
    try {
      const product = await api.getProduct(productId, recommendation?.recommendation_id);
      setSelectedProduct(product);
      setView("detail");
      writeHistoryState("detail", "push", productId);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch {
      setSelectedProduct(null);
      setView("notFound");
      writeHistoryState("notFound", "push", productId);
    }
  };

  const goHome = () => {
    submissionRequestIdRef.current += 1;
    setSelectedProduct(null);
    setView("input");
    setErrorMessage(null);
    writeHistoryState("input", "push");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const editRequest = () => {
    submissionRequestIdRef.current += 1;
    setIsSubmitting(false);
    setSelectedProduct(null);
    setView("input");
    setErrorMessage(null);
    writeHistoryState("input", "replace");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const goResults = () => {
    if (recommendation && window.history.length > 1) {
      window.history.back();
      return;
    }

    setSelectedProduct(null);
    setView(recommendation ? "results" : "input");
    setErrorMessage(null);
    writeHistoryState(recommendation ? "results" : "input", "push");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <main className="app-shell">
      <AppHeader apiBaseUrl={apiBaseUrl} onHome={goHome} />

      {view === "input" ? (
        <ConcernInputPage
          value={request}
          isSubmitting={isSubmitting}
          errorMessage={errorMessage}
          onChange={(nextValue) => {
            setRequest(nextValue);
            setErrorMessage(null);
          }}
          onSubmit={startRecommendation}
        />
      ) : null}

      {view === "loading" ? (
        <AnalysisLoadingPage
          key={analysisRunId}
          request={request}
          isLoading={isSubmitting}
          errorMessage={errorMessage}
          onRetry={startRecommendation}
          onEdit={editRequest}
        />
      ) : null}

      {view === "results" && recommendation ? (
        <RecommendationResultsPage
          recommendation={recommendation}
          onOpenProduct={openProduct}
          onRestart={goHome}
        />
      ) : null}

      {view === "detail" && selectedProduct ? (
        <ProductDetailPage product={selectedProduct} onBack={goResults} />
      ) : null}

      {view === "notFound" ? <ProductNotFoundPage onBack={goResults} /> : null}
    </main>
  );
}

export default App;
