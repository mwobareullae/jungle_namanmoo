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
              <h4 id="flowConcern">{query.length > 30 ? `${query.slice(0, 30)}...` : query || "입력된 고민"}</h4>
              <div className="flow-tags" id="flowConcernTags">
                {(recommendation?.summary.concerns ?? []).slice(0, 4).map((concern, index) => (
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

const footerColumns = [
  ["고객 지원", "공지사항", "자주 묻는 질문", "1:1 문의", "교환/반품 안내", "배송 조회"],
  ["쇼핑", "신상품", "베스트", "세일", "브랜드", "맞춤 추천"],
  ["회사", "회사소개", "이용약관", "개인정보처리방침", "입점 문의", "채용"],
];

const communityFooterColumns = [
  ["서비스", "맞춤 추천", "성분 가이드", "자주 묻는 질문"],
  ["회사", "회사소개", "이용약관", "개인정보처리방침"],
];

function HomeFooter() {
  const columns = import.meta.env.VITE_APP_MODE === "community" ? communityFooterColumns : footerColumns;

  return (
    <footer>
      <div className="footer-inner">
        <div className="footer-brand">
          <a className="logo" href="/">
            뭐바를래
          </a>
          <p className="footer-desc">
            피부 고민에서 시작해 최적의 성분과 제품까지.
            <br />
            뭐바를래는 성분 함량과 근거 데이터를 함께 보고
            <br />
            납득 가능한 선택지를 골라드립니다.
          </p>
        </div>
        {columns.map(([title, ...items]) => (
          <div className="footer-col" key={title}>
            <h5>{title}</h5>
            <ul>
              {items.map((item) => (
                <li key={item}>
                  <a href="/#defaultSection">{item}</a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="footer-bottom">
        <span>© 2026 뭐바를래. All rights reserved.</span>
      </div>
    </footer>
  );
}

export { HomeFooter, HomeMatchResult };
