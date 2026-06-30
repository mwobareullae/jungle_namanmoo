import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
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

const howSteps = [
  {
    title: "피부 고민 입력",
    copy: "일상 언어로 편하게 고민을 말씀해 주세요. 피부 타입, 트러블, 원하는 효과 모두 OK",
    icon: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  },
  {
    title: "효능 분석",
    copy: "피부 고민에 필요한 효능을 도출합니다. 보습, 진정, 미백, 각질 제거 등",
    icon: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
  },
  {
    title: "성분 매핑",
    copy: "효능을 발휘하는 핵심 성분을 식별하고 성분 데이터베이스와 매칭합니다",
    icon: (
      <>
        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
  },
  {
    title: "제품 점수 추천",
    copy: "성분 함량·조합·리뷰를 종합해 0~100점 매칭 스코어로 최적 제품을 추천합니다",
    icon: (
      <>
        <circle cx="12" cy="8" r="6" />
        <path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" />
      </>
    ),
  },
] satisfies Array<{ title: string; copy: string; icon: ReactNode }>;

function HomeHowItWorks() {
  return (
    <section className="how-section">
      <div className="how-inner">
        <div>
          <div className="sec-eyebrow">How It Works</div>
          <div className="section-title" style={{ fontSize: 24, marginTop: 4 }}>
            어떻게 작동하나요?
          </div>
          <div className="section-subtitle">4단계 성분 근거 분석으로 필요한 제품을 추천합니다</div>
        </div>
        <div className="how-steps">
          {howSteps.map((step, index) => (
            <div className="how-step" key={step.title}>
              <div className="step-icon">
                <svg
                  fill="none"
                  height="26"
                  stroke="#94e0f8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.5"
                  viewBox="0 0 24 24"
                  width="26"
                >
                  {step.icon}
                </svg>
                <span className="step-number">{index + 1}</span>
              </div>
              <h4>{step.title}</h4>
              <p>{step.copy}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const ingredients = [
  {
    name: "나이아신아마이드",
    effect: "미백 · 모공 축소 · 피지 조절",
    copy: "멜라닌 전달을 억제해 피부 톤을 균일하게 만들고, 피지 분비를 억제해 모공을 줄여줍니다. 민감한 피부에도 비교적 안전합니다.",
    icon: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
      </>
    ),
  },
  {
    name: "살리실산 (BHA)",
    effect: "각질 제거 · 모공 청소 · 항균",
    copy: "지용성 성분으로 모공 속까지 침투해 피지와 각질을 녹입니다. 여드름성·지성 피부에 탁월한 효과를 보입니다.",
    icon: <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />,
  },
  {
    name: "히알루론산",
    effect: "수분 공급 · 피부 장벽 강화",
    copy: "자기 무게의 1000배 수분을 머금는 능력으로 피부 깊숙이 수분을 공급하고 촉촉함을 오래 유지시킵니다.",
    icon: <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />,
  },
  {
    name: "레티놀",
    effect: "주름 개선 · 세포 재생 · 피부 탄력",
    copy: "세포 재생을 촉진하고 콜라겐 합성을 자극합니다. 처음 사용 시 저농도로 시작하는 것을 권장합니다.",
    icon: (
      <>
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
        <polyline points="17 6 23 6 23 12" />
      </>
    ),
  },
  {
    name: "세라마이드",
    effect: "피부 장벽 복구 · 보습 · 민감 진정",
    copy: "피부 장벽의 핵심 구성 요소로 외부 자극으로부터 피부를 보호하고 수분 손실을 막아줍니다.",
    icon: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  },
  {
    name: "판테놀 (비타민B5)",
    effect: "진정 · 보습 · 상처 회복",
    copy: "트러블 후 피부 회복을 돕고 강력한 보습 효과로 민감해진 피부를 부드럽게 진정시켜 줍니다.",
    icon: <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />,
  },
] satisfies Array<{ name: string; effect: string; copy: string; icon: ReactNode }>;

function HomeIngredientGuide() {
  return (
    <section className="ingr-section">
      <div className="ingr-inner">
        <div className="section-header">
          <div>
            <div className="sec-eyebrow">Ingredient Guide</div>
            <div className="section-title">대표 성분 가이드</div>
            <div className="section-subtitle">각 고민별 핵심 성분을 미리 알아보세요</div>
          </div>
        </div>
        <div className="ingr-grid">
          {ingredients.map((ingredient) => (
            <div className="ingr-card" key={ingredient.name}>
              <div className="ingr-card-icon">
                <svg
                  fill="none"
                  height="22"
                  stroke="#94e0f8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.5"
                  viewBox="0 0 24 24"
                  width="22"
                >
                  {ingredient.icon}
                </svg>
              </div>
              <h4>{ingredient.name}</h4>
              <div className="ingr-effect">{ingredient.effect}</div>
              <p>{ingredient.copy}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const footerColumns = [
  ["고객 지원", "공지사항", "자주 묻는 질문", "1:1 문의", "교환/반품 안내", "배송 조회"],
  ["쇼핑", "신상품", "베스트", "세일", "브랜드", "맞춤 추천"],
  ["회사", "회사소개", "이용약관", "개인정보처리방침", "입점 문의", "채용"],
];

function HomeFooter() {
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
        {footerColumns.map(([title, ...items]) => (
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
        <span>© 2025 뭐바를래. All rights reserved.</span>
        <span>사업자등록번호 123-45-67890 | 대표 홍길동</span>
      </div>
    </footer>
  );
}

export { HomeFooter, HomeHowItWorks, HomeIngredientGuide, HomeMatchResult };
