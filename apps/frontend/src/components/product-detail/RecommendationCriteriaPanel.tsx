import type { ProductDetail, ScoreBreakdown } from "../../types/recommendation";

type RecommendationCriteriaPanelProps = {
  product: ProductDetail;
};

type CriteriaTone = "positive" | "neutral" | "caution" | "unknown";

type CriteriaItem = {
  label: string;
  status: string;
  tone: CriteriaTone;
  description: string;
  score?: number;
};

const scoreToStatus = (score: number | undefined) => {
  if (score === undefined || Number.isNaN(score)) {
    return { status: "확인 필요", tone: "unknown" as const };
  }
  if (score >= 75) return { status: "높음", tone: "positive" as const };
  if (score >= 50) return { status: "보통", tone: "neutral" as const };
  return { status: "낮음", tone: "caution" as const };
};

const concentrationStatus = (breakdown: ScoreBreakdown) => {
  if (breakdown.concentration_bucket === "optimal") {
    return { status: "적정", tone: "positive" as const };
  }
  if (breakdown.concentration_bucket === "meaningful") {
    return { status: "의미 있는 수준", tone: "positive" as const };
  }
  if (breakdown.concentration_bucket || breakdown.concentration_warning) {
    return { status: "확인 필요", tone: "caution" as const };
  }
  return { status: "확인 필요", tone: "unknown" as const };
};

const buildCriteria = (product: ProductDetail): CriteriaItem[] => {
  const breakdown = product.score_breakdown;
  const concern = scoreToStatus(
    breakdown?.search_match_score || breakdown?.keyword_score || undefined
  );
  const effect = scoreToStatus(breakdown?.ingredient_effect_score);
  const evidence = scoreToStatus(breakdown?.ingredient_evidence_score);
  const skin = scoreToStatus(
    breakdown?.skin_type_match_score !== undefined
      ? (breakdown.skin_type_match_score + (breakdown.sensitivity_score ?? breakdown.skin_type_match_score)) / 2
      : undefined
  );
  const reviewSummary = product.review_summary;
  const reviewScore = reviewSummary?.average_rating
    ? Math.min(100, (reviewSummary.average_rating / 5) * 100)
    : undefined;
  const review = scoreToStatus(reviewScore);
  const price = scoreToStatus(breakdown?.price_value_score);
  const concentration = breakdown ? concentrationStatus(breakdown) : { status: "확인 필요", tone: "unknown" as const };
  const riskIsPresent = product.risk_flags.length > 0 || (breakdown?.risk_penalty ?? 0) < 0;

  return [
    {
      label: "입력 고민·피부 타입과의 일치",
      ...concern,
      score: breakdown?.search_match_score ?? breakdown?.keyword_score,
      description: product.reason_summary || "입력한 피부 고민과 상품 정보를 함께 비교했어요.",
    },
    {
      label: "핵심 성분과 기대 효능",
      ...effect,
      score: breakdown?.ingredient_effect_score,
      description: product.key_ingredients.length > 0
        ? `${product.key_ingredients.slice(0, 3).join(", ")} 성분을 중심으로 확인했어요.`
        : "핵심 성분 정보를 확인 중이에요.",
    },
    {
      label: "성분 근거 수준",
      ...evidence,
      score: breakdown?.ingredient_evidence_score,
      description: product.evidence.length > 0
        ? `표시 가능한 성분 근거 ${product.evidence.length}건을 확인했어요.`
        : "표시 가능한 성분 근거가 부족해요.",
    },
    {
      label: "함량 상태",
      ...concentration,
      score: breakdown?.concentration_fit_score,
      description: breakdown?.concentration_warning || "함량 구간과 근거 데이터를 기준으로 확인했어요.",
    },
    {
      label: "피부 타입·민감도 적합도",
      ...skin,
      score: breakdown?.skin_type_match_score,
      description: "피부 타입과 민감도 조건을 추천 기준에 반영했어요.",
    },
    {
      label: "정제 리뷰 기반 만족도 신호",
      ...review,
      score: reviewScore,
      description: reviewSummary?.review_count
        ? `리뷰 ${reviewSummary.review_count.toLocaleString("ko-KR")}개와 평균 평점을 참고했어요.`
        : "비교할 리뷰 데이터가 부족해요.",
    },
    {
      label: "가격·카테고리 등 구매 조건",
      ...price,
      score: breakdown?.price_value_score,
      description: product.lowest_price !== null
        ? "현재 확인된 가격과 요청 조건을 함께 살펴봤어요."
        : "가격 정보를 확인할 수 없어요.",
    },
    {
      label: "주의 성분 및 위험 감점",
      status: riskIsPresent ? "주의 필요" : "주의 없음",
      tone: riskIsPresent ? "caution" : "positive",
      description: riskIsPresent
        ? product.risk_flags[0] || "민감도에 따라 주의가 필요한 항목이 있어요."
        : "확인된 위험 감점 항목이 없어요.",
      score: breakdown?.risk_penalty ? Math.min(100, Math.abs(breakdown.risk_penalty) * 10) : 0,
    },
  ];
};

function RecommendationCriteriaPanel({ product }: RecommendationCriteriaPanelProps) {
  const criteria = buildCriteria(product);

  return (
    <section className="recommendation-criteria-panel" aria-labelledby="recommendation-criteria-title">
      <div className="recommendation-criteria-head">
        <div>
          <p className="recommendation-criteria-eyebrow">Recommendation Basis</p>
          <h2 id="recommendation-criteria-title">왜 이 상품인가요?</h2>
        </div>
        <p>내부 가중치 숫자 대신, 추천에 반영된 기준을 보여드려요.</p>
      </div>
      <div className="recommendation-criteria-list">
        {criteria.map((item) => (
          <article className="recommendation-criteria-item" key={item.label}>
            <div className="recommendation-criteria-row">
              <strong>{item.label}</strong>
              <span className={`recommendation-criteria-status ${item.tone}`}>{item.status}</span>
            </div>
            <div className="recommendation-criteria-meter" aria-hidden="true">
              <span style={{ width: `${item.score === undefined ? 0 : Math.max(0, Math.min(100, item.score))}%` }} />
            </div>
            <p>{item.description}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default RecommendationCriteriaPanel;
