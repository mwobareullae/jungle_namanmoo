import { useState } from "react";
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

const initialRequest: RecommendationRequest = {
  skin_type: "수부지",
  sensitivity: "보통",
  avoid_ingredients: [],
  concern_text: ""
};

const minimumLoadingMs = 3200;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const logRecommendationRequest = (
  rawRequest: RecommendationRequest,
  nextRequest: RecommendationRequest
) => {
  console.groupCollapsed("[muwobareullae] recommendation request");
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

    try {
      const [response] = await Promise.all([
        api.createRecommendation(nextRequest),
        wait(minimumLoadingMs)
      ]);
      setRecommendation(response);
      setView("results");
    } catch {
      setErrorMessage("분석에 실패했어요. 입력값은 보존했으니 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const openProduct = async (productId: string) => {
    setErrorMessage(null);
    try {
      const product = await api.getProduct(productId);
      setSelectedProduct(product);
      setView("detail");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch {
      setSelectedProduct(null);
      setView("notFound");
    }
  };

  const goHome = () => {
    setView("input");
    setErrorMessage(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const goResults = () => {
    setView(recommendation ? "results" : "input");
    setErrorMessage(null);
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
          onEdit={() => setView("input")}
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
