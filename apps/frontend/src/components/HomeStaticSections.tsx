import { Fragment, useEffect, useMemo, useState } from "react";
import type { RecommendationResponse } from "../types/recommendation";

const ArrowIcon = () => (
  <svg
    fill="none"
    height="16"
    stroke="currentColor"
    strokeLinecap="round"
    strokeLinejoin="round"
    strokeWidth="2"
    viewBox="0 0 24 24"
    width="16"
  >
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);

const LoadingIcon = () => (
  <svg
    fill="none"
    height="18"
    stroke="white"
    strokeLinecap="round"
    strokeLinejoin="round"
    strokeWidth="2"
    viewBox="0 0 24 24"
    width="18"
  >
    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
  </svg>
);

type RecommendationStateEvent = CustomEvent<{
  status: "idle" | "loading" | "success" | "error";
  query: string;
  recommendation: RecommendationResponse | null;
  scope?: "home" | "search";
}>;

type HomeMatchResultProps = {
  compact?: boolean;
  scope?: "home" | "search";
};

const loadingMessages = [
  "피부 고민을 정리하고 있어요",
  "성분 근거를 확인하고 있어요",
  "피부에 맞는 상품을 고르고 있어요"
];

function HomeMatchResult({ compact = false, scope = "home" }: HomeMatchResultProps) {
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [loadingStep, setLoadingStep] = useState(0);

  useEffect(() => {
    const handleRecommendationState = (event: Event) => {
      const detail = (event as RecommendationStateEvent).detail;
      if (detail.scope && detail.scope !== scope) return;
      if (detail.status === "loading") {
        setLoadingStep(0);
      }
      setStatus(detail.status);
      setQuery(detail.query);
      setRecommendation(detail.recommendation);
    };

    window.addEventListener("home-recommendation-state", handleRecommendationState);
    return () => window.removeEventListener("home-recommendation-state", handleRecommendationState);
  }, [scope]);

  const keyIngredients = useMemo(
    () => Array.from(new Set((recommendation?.products ?? []).flatMap((product) => product.key_ingredients))).slice(0, 6),
    [recommendation]
  );
  const concerns = useMemo(() => {
    const normalizedQuery = query.replace(/\s/g, "");
    return (recommendation?.summary.concerns ?? []).filter(
      (concern) => concern.replace(/\s/g, "") !== normalizedQuery
    );
  }, [query, recommendation]);

  const scoreItems = (recommendation?.products ?? []).slice(0, 4);
  const isActive = status !== "idle";
  const isLoading = status === "loading";
  const loadingMessage = loadingStep >= 6 ? "조금만 더 기다려 주세요" : loadingMessages[loadingStep % loadingMessages.length];

  useEffect(() => {
    if (!isLoading) return;

    const intervalId = window.setInterval(() => setLoadingStep((step) => step + 1), 3000);
    return () => window.clearInterval(intervalId);
  }, [isLoading]);

  return (
    <div
      className={`ai-result-section${isActive ? " active" : ""}${compact ? " compact" : ""}`}
      id="aiResultSection"
    >
      <div className="ai-result-inner">
        <div className="ai-thinking" id="aiThinking" style={{ display: isLoading ? "flex" : "none" }}>
          <div className="thinking-icon">
            <LoadingIcon />
          </div>
          <div className="thinking-text">
            <strong aria-atomic="true" aria-live="polite" className="ai-thinking-status" key={loadingMessage}>{loadingMessage}</strong>
            <span>
              피부 고민을 분석하고 최적의 성분과 제품을 찾고 있어요{" "}
              <span className="loading-dots">
                <span />
                <span />
                <span />
              </span>
            </span>
          </div>
        </div>

        <div className="analysis-flow" id="analysisFlow" style={{ display: status === "success" ? "grid" : "none" }}>
          <Fragment>
            <div className="flow-card active">
              <div className="flow-step"><span className="step-num">1</span>피부 고민</div>
              <h4 id="flowConcern">{concerns.length ? concerns.slice(0, 2).join(" · ") : "피부 고민 분석"}</h4>
              <div className="flow-tags" id="flowConcernTags">
                {concerns.slice(0, 4).map((concern, index) => (
                  <span className={`flow-tag${index < 2 ? " highlight" : ""}`} key={concern}>{concern}</span>
                ))}
                {recommendation ? (
                  <>
                    <span className="flow-tag profile">피부 {recommendation.summary.skin_type}</span>
                    <span className="flow-tag profile">민감도 {recommendation.summary.sensitivity}</span>
                  </>
                ) : null}
              </div>
            </div>
            <div className="flow-arrow"><ArrowIcon /></div>
            <div className="flow-card active">
              <div className="flow-step"><span className="step-num">2</span>필요 효능</div>
              <h4>분석된 효능</h4>
              <div className="flow-tags" id="flowEffects">
                {(recommendation?.summary.effects ?? []).slice(0, 5).map((effect, index) => (
                  <span className={`flow-tag${index < 2 ? " highlight" : ""}`} key={effect}>{effect}</span>
                ))}
              </div>
            </div>
            <div className="flow-arrow"><ArrowIcon /></div>
            <div className="flow-card active">
              <div className="flow-step"><span className="step-num">3</span>핵심 성분</div>
              <h4>추천 성분</h4>
              <div className="flow-tags" id="flowIngredients">
                {keyIngredients.map((ingredient, index) => (
                  <span className={`flow-tag${index < 2 ? " highlight" : ""}`} key={ingredient}>{ingredient}</span>
                ))}
              </div>
            </div>
            <div className="flow-arrow"><ArrowIcon /></div>
            <div className="flow-card active">
              <div className="flow-step"><span className="step-num">4</span>매칭 결과</div>
              <h4>추천 상품 <span id="matchCount">{recommendation?.products.length ?? 0}</span>개</h4>
              <div id="flowScores">
                <div style={{ marginBottom: 8, fontSize: 12, fontWeight: 500, color: "var(--accent-text)", textTransform: "uppercase" }}>매칭 점수</div>
                {scoreItems.map((product) => (
                  <div className="score-bar" key={product.product_id}>
                    <span style={{ fontSize: 12, minWidth: 90, color: "var(--muted)" }}>{product.brand}</span>
                    <div className="score-track"><div className="score-fill" style={{ width: `${product.total_score}%` }} /></div>
                    <span className="score-num">{product.total_score}점</span>
                  </div>
                ))}
              </div>
            </div>
          </Fragment>
        </div>
      </div>
    </div>
  );
}

export { HomeMatchResult };
