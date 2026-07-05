import HomeHeader from "../components/HomeHeader";

type RecommendationStepIcon = "concern" | "effect" | "ingredient" | "score";

const recommendationSteps = [
  {
    icon: "concern",
    title: "피부 고민 입력",
    copy: "사용자가 입력한 피부 고민, 피부 타입, 민감도를 추천 기준으로 함께 확인합니다.",
  },
  {
    icon: "effect",
    title: "효능 분석",
    copy: "입력된 고민을 보습, 진정, 미백, 각질 제거 같은 필요한 효능으로 정리합니다.",
  },
  {
    icon: "ingredient",
    title: "성분 매칭",
    copy: "효능을 발휘하는 핵심 성분을 찾고 성분 데이터베이스와 연결합니다.",
  },
  {
    icon: "score",
    title: "제품 점수 추천",
    copy: "성분, 피부 타입 적합도, 가격과 리뷰 신호를 종합해 매칭 점수 기준으로 보여줍니다.",
  },
] satisfies Array<{
  icon: RecommendationStepIcon;
  title: string;
  copy: string;
}>;

const guideIngredients = [
  {
    name: "나이아신아마이드",
    effect: "미백 · 모공 축소 · 피지 조절",
    copy: "피부 톤과 피지 고민에 자주 연결되는 성분으로, 잡티와 모공 고민 추천에서 주요 근거가 됩니다.",
  },
  {
    name: "살리실산 (BHA)",
    effect: "각질 제거 · 모공 청소 · 피지 케어",
    copy: "피지와 각질 고민에 연결되는 성분으로, 지성 피부와 트러블성 고민에서 우선 확인합니다.",
  },
  {
    name: "히알루론산",
    effect: "수분 공급 · 보습 · 장벽 보조",
    copy: "수분 부족과 건조함에 연결되는 성분으로, 보습 중심 추천의 기본 근거가 됩니다.",
  },
  {
    name: "세라마이드",
    effect: "피부 장벽 복구 · 보습 · 민감 진정",
    copy: "장벽 손상, 건조, 민감 고민에 연결되는 성분으로 보습과 진정 추천에서 중요합니다.",
  },
  {
    name: "판테놀 (비타민B5)",
    effect: "진정 · 보습 · 장벽 보조",
    copy: "붉어짐과 민감 고민에 연결되는 성분으로, 자극 완화 추천에서 주요하게 봅니다.",
  },
  {
    name: "레티놀",
    effect: "주름 개선 · 피부결 · 탄력",
    copy: "탄력과 주름 고민에 연결되지만 민감도에 따라 주의가 필요해 보조 신호로 함께 확인합니다.",
  },
  {
    name: "마데카소사이드",
    effect: "진정 · 장벽 보조 · 피부 회복",
    copy: "민감하거나 손상된 피부 컨디션에 연결되는 성분으로, 진정 추천에서 강하게 반영됩니다.",
  },
  {
    name: "센텔라/병풀",
    effect: "진정 · 붉은기 · 장벽 보조",
    copy: "붉어짐과 민감 피부 고민에 자주 연결되는 성분으로, 진정 중심 제품에서 중요하게 봅니다.",
  },
  {
    name: "아데노신",
    effect: "주름 개선 · 탄력 · 기능성 케어",
    copy: "탄력 저하와 잔주름 고민에 연결되는 기능성 성분으로, 안티에이징 추천에서 확인합니다.",
  },
  {
    name: "트라넥사믹애씨드",
    effect: "잡티 케어 · 톤 균일화 · 미백",
    copy: "색소침착과 잡티 고민에 연결되는 성분으로, 피부톤 개선 추천에서 핵심 근거가 됩니다.",
  },
  {
    name: "징크PCA",
    effect: "피지 조절 · 모공 고민 · 트러블 보조",
    copy: "과도한 피지와 모공 고민에 연결되는 성분으로, 지성 피부 추천에서 보조 신호로 봅니다.",
  },
  {
    name: "페트롤라툼/미네랄오일",
    effect: "보습막 · 수분 손실 방지 · 장벽 보호",
    copy: "건조하고 장벽이 약한 피부에 연결되는 성분으로, 강한 보습막이 필요한 제품에서 중요합니다.",
  },
];

function RecommendationStepIcon({ type }: { type: RecommendationStepIcon }) {
  if (type === "concern") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5.5 6.5h13v8.25h-7.25L6.5 18.5v-3.75h-1z" />
      </svg>
    );
  }

  if (type === "effect") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M3.5 12h4l2-6.5 4 13 2.4-6.5h4.6" />
      </svg>
    );
  }

  if (type === "ingredient") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M8 4.75H5.75A1.75 1.75 0 0 0 4 6.5V8" />
        <path d="M16 4.75h2.25A1.75 1.75 0 0 1 20 6.5V8" />
        <path d="M20 16v1.5a1.75 1.75 0 0 1-1.75 1.75H16" />
        <path d="M8 19.25H5.75A1.75 1.75 0 0 1 4 17.5V16" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="8" r="4" />
      <path d="M9.5 11.5 8 20l4-2.25L16 20l-1.5-8.5" />
    </svg>
  );
}

function RecommendationGuidePage() {
  return (
    <div className="recommendation-guide-shell">
      <HomeHeader />
      <main className="recommendation-guide-page">
        <div className="recommendation-guide-page__inner">
          <section className="recommendation-guide-hero">
            <p className="recommendation-guide-eyebrow">Recommendation Guide</p>
            <h1>추천 기준 알아보기</h1>
            <p>
              뭐바를래는 피부 고민을 바로 상품으로 연결하지 않고, 필요한 효능과 핵심 성분을 먼저
              정리한 뒤 제품 후보를 비교합니다.
            </p>
          </section>

          <section className="recommendation-guide-section">
            <div className="recommendation-guide-section__head">
              <p className="recommendation-guide-eyebrow">How It Works</p>
              <h2>어떻게 추천하나요?</h2>
              <p>4단계 성분 근거 분석으로 사용자의 피부 고민에 맞는 제품을 찾습니다.</p>
            </div>
            <div className="recommendation-guide-steps">
              {recommendationSteps.map((step, index) => (
                <article className="recommendation-guide-step" key={step.title}>
                  <div className="recommendation-guide-step__icon">
                    <RecommendationStepIcon type={step.icon} />
                    <span className="recommendation-guide-step__number">{index + 1}</span>
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="recommendation-guide-section">
            <div className="recommendation-guide-section__head">
              <p className="recommendation-guide-eyebrow">Ingredient Guide</p>
              <h2>대표 성분 가이드</h2>
              <p>피부 고민별 추천 근거로 자주 쓰이는 핵심 성분입니다.</p>
            </div>
            <div className="recommendation-guide-ingredients">
              {guideIngredients.map((ingredient) => (
                <article className="recommendation-guide-ingredient" key={ingredient.name}>
                  <h3>{ingredient.name}</h3>
                  <div className="recommendation-guide-ingredient__effect">{ingredient.effect}</div>
                  <p>{ingredient.copy}</p>
                </article>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

export default RecommendationGuidePage;
