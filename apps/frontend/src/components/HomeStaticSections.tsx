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
}>;

type HomeMatchResultProps = {
  compact?: boolean;
};

function HomeMatchResult({ compact = false }: HomeMatchResultProps) {
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [query, setQuery] = useState("");
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);

  useEffect(() => {
    const handleRecommendationState = (event: Event) => {
      const detail = (event as RecommendationStateEvent).detail;
      setStatus(detail.status);
      setQuery(detail.query);
      setRecommendation(detail.recommendation);
    };

    window.addEventListener("home-recommendation-state", handleRecommendationState);
    return () => window.removeEventListener("home-recommendation-state", handleRecommendationState);
  }, []);

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
            <strong>성분 근거를 확인 중...</strong>
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
