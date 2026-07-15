import { useState } from "react";
import type { ProductDetail, RecommendationSummary, ScoreBreakdown } from "../../types/recommendation";

type RecommendationCriteriaPanelProps = {
  product: ProductDetail;
  summary?: RecommendationSummary | null;
};

type CriteriaTone = "positive" | "neutral" | "caution" | "unknown";

type CriteriaItem = {
  label: string;
  status: string;
  tone: CriteriaTone;
  description: string;
};

const statusFromScore = (score: number | undefined) => {
  if (score === undefined || Number.isNaN(score)) return { status: "정보 없음", tone: "unknown" as const };
  if (score >= 75) return { status: "높음", tone: "positive" as const };
  if (score >= 50) return { status: "보통", tone: "neutral" as const };
  return { status: "낮음", tone: "caution" as const };
};

const concentrationState = (breakdown: ScoreBreakdown | undefined) => {
  if (!breakdown || !breakdown.concentration_bucket || breakdown.concentration_bucket === "unknown") {
    return { status: "정보 없음", tone: "unknown" as const, description: "함량 정보가 공개되지 않았어요." };
  }
  if (breakdown.concentration_bucket === "optimal") {
    return { status: "적정", tone: "positive" as const, description: "함량 구간과 근거 데이터를 기준으로 적정 수준으로 분류했어요." };
  }
  if (breakdown.concentration_bucket === "meaningful") {
    return { status: "의미 있는 수준", tone: "positive" as const, description: "함량 구간과 근거 데이터를 기준으로 의미 있는 수준으로 분류했어요." };
  }
  return { status: "정보 없음", tone: "unknown" as const, description: "함량 정보가 공개되지 않았어요." };
};

const getConcerns = (summary?: RecommendationSummary | null) => summary?.matched_concerns ?? summary?.concerns ?? [];
const getEffects = (summary?: RecommendationSummary | null) => summary?.expected_effects ?? summary?.effects ?? [];

const buildCriteriaGroups = (product: ProductDetail, summary?: RecommendationSummary | null) => {
  const breakdown = product.score_breakdown;
  const reviewApplied = breakdown?.review_quality_applied === true && breakdown?.review_profile_affinity_applied === true;
  const concentration = concentrationState(breakdown);
  const riskPresent = (breakdown?.risk_flag_count ?? 0) > 0 || (breakdown?.risk_penalty ?? 0) > 0 || product.risk_flags.length > 0;
  const priceText = product.lowest_price === null ? "가격 정보가 공개되지 않았어요." : `${product.lowest_price.toLocaleString("ko-KR")}원 기준으로 살펴봤어요.`;
  const purchaseText = summary?.purchase_constraints?.price_text || summary?.purchase_constraints?.price_max_text;
  const skinScore = breakdown?.skin_profile_score ?? breakdown?.skin_type_match_score;
  const evidencePairs = product.evidence
    .slice(0, 3)
    .map((item) => `${item.ingredient_name} → ${item.effect_name}`)
    .join(", ");
  const evidenceSources = product.evidence
    .slice(0, 2)
    .map((item) => item.source_title)
    .filter(Boolean)
    .join(", ");

  return [
    {
      title: "성분·효능 근거",
      items: [
        {
          label: "핵심 성분과 기대 효능",
          ...statusFromScore(breakdown?.ingredient_effect_score),
          description: evidencePairs
            ? `${evidencePairs} 연결을 확인했어요.`
            : product.key_ingredients.length
              ? `${product.key_ingredients.slice(0, 3).join(", ")} 성분과 기대 효능의 연결 정보가 없어요.`
              : "핵심 성분 정보가 없어요.",
        },
        {
          label: "성분 근거 수준",
          ...statusFromScore(breakdown?.ingredient_evidence_score),
          description: product.evidence.length
            ? `표시 가능한 성분 근거 ${product.evidence.length}건을 확인했어요.${evidenceSources ? ` 출처: ${evidenceSources}` : ""}`
            : "표시 가능한 성분 근거가 없어요.",
        },
      ],
    },
    {
      title: "내 피부 적합",
      items: [
        {
          label: "피부 타입·민감도 적합도",
          ...statusFromScore(skinScore),
          description: "피부 타입과 민감도 조건을 추천 기준에 반영했어요.",
        },
        {
          label: "리뷰 만족도 신호",
          ...(reviewApplied ? statusFromScore(breakdown?.review_quality_score ?? breakdown?.review_profile_affinity_score) : { status: "정보 없음", tone: "unknown" as const }),
          description: reviewApplied ? "적용 가능한 리뷰 신호를 추천 기준에 반영했어요." : "리뷰 데이터 없음 · 중립 처리(점수 유·불리 없음).",
        },
      ],
    },
    {
      title: "요청·취향 적합",
      items: [
        {
          label: "가격·카테고리 등 구매 조건",
          ...statusFromScore(breakdown?.price_value_score),
          description: purchaseText ? `${priceText} 요청 조건: ${purchaseText}` : priceText,
        },
      ],
    },
    {
      title: "함량·안전",
      items: [
        { label: "함량 상태", ...concentration },
        {
          label: "주의 성분 및 위험 감점",
          status: riskPresent ? "주의 필요" : "주의 없음",
          tone: riskPresent ? "caution" as const : "positive" as const,
          description: riskPresent ? (breakdown?.risk_warnings?.[0] || product.risk_flags[0] || "주의가 필요한 항목이 있어요.") : "확인된 위험 감점 항목이 없어요.",
        },
      ],
    },
  ] as { title: string; items: CriteriaItem[] }[];
};

function RecommendationCriteriaPanel({ product, summary }: RecommendationCriteriaPanelProps) {
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const concerns = getConcerns(summary);
  const effects = getEffects(summary);
  const ingredients = product.key_ingredients;
  const concentration = concentrationState(product.score_breakdown);
  const firstEvidence = product.evidence[0];
  const firstEvidenceSource = firstEvidence?.source_title ? product.sources.find((source) => source.title === firstEvidence.source_title) : undefined;
  const adjustedWeights = product.score_breakdown?.adjusted_weights;
  const hasEvidenceWeight = adjustedWeights && (adjustedWeights.ingredient_effect !== undefined || adjustedWeights.ingredient_evidence !== undefined);
  const groups = buildCriteriaGroups(product, summary);

  return (
    <section className="recommendation-criteria-panel" aria-labelledby="recommendation-criteria-title">
      <header className="recommendation-criteria-head">
        <div>
          <p className="recommendation-criteria-eyebrow">Recommendation Basis</p>
          <h2 id="recommendation-criteria-title">왜 이 상품인가요?</h2>
        </div>
        <div className="recommendation-criteria-score"><strong>{Math.round(product.total_score)}</strong><span>추천 점수</span></div>
        <p>내부 가중치 숫자 대신, 추천에 반영된 기준을 보여드려요.</p>
      </header>

      <div className="recommendation-criteria-hero">
        <strong className="recommendation-criteria-hero-title">내 고민에서 근거까지</strong>
        <p className="recommendation-criteria-hero-sub">입력 고민을 효능·성분·함량·근거로 연결해 보여드려요.</p>
        <div className="recommendation-criteria-chain">
          <div className="recommendation-criteria-node"><span>내 고민</span><div>{concerns.length ? concerns.map((item) => <b key={item}>{item}</b>) : <em>입력 고민 정보 없음</em>}</div><small>↓ 그래서 필요한 효능은</small></div>
          <div className="recommendation-criteria-node"><span>필요한 효능</span><div>{effects.length ? effects.map((item) => <b key={item}>{item}</b>) : <em>기대 효능 정보 없음</em>}</div><small>↓ 그래서 고른 성분은</small></div>
          <div className="recommendation-criteria-node"><span>핵심 성분</span><div>{ingredients.length ? ingredients.slice(0, 5).map((item) => <b className="ingredient" key={item}>{item}</b>) : <em>핵심 성분 정보 없음</em>}</div><small>↓ 이 성분이 이만큼 들었나 (함량)</small></div>
          <div className="recommendation-criteria-node"><span>함량 상태</span><div><b className={`recommendation-criteria-inline-status ${concentration.tone}`}>{concentration.status}</b></div><small>↓ 무슨 근거로</small></div>
          <div className="recommendation-criteria-node"><span>근거</span><div>{firstEvidence ? <><b>{firstEvidence.ingredient_name} → {firstEvidence.effect_name}</b><em>{firstEvidence.source_title || firstEvidence.evidence_text}</em>{firstEvidenceSource?.url ? <a href={firstEvidenceSource.url} target="_blank" rel="noreferrer">출처 보기 ↗</a> : null}</> : <em>표시 가능한 성분 근거 없음</em>}</div></div>
        </div>
        <div className="recommendation-criteria-reason"><span>한 줄 요약</span><strong>{product.reason_summary || "추천 근거를 준비 중입니다."}</strong></div>
        {hasEvidenceWeight ? <p className="recommendation-criteria-headline">이 추천에서 성분·효능 근거가 가장 큰 비중</p> : null}
      </div>

      <button className="recommendation-criteria-details-toggle" type="button" aria-expanded={isDetailsOpen} onClick={() => setIsDetailsOpen((open) => !open)}>
        상세 점수 근거 {isDetailsOpen ? "접기" : "보기"}<span aria-hidden="true">{isDetailsOpen ? "⌃" : "⌄"}</span>
      </button>
      {isDetailsOpen ? <div className="recommendation-criteria-groups">
        {groups.map((group) => <section className="recommendation-criteria-group" key={group.title}><h3>{group.title}</h3>{group.items.map((item) => <article className="recommendation-criteria-item" key={item.label}><div className="recommendation-criteria-row"><strong>{item.label}</strong><span className={`recommendation-criteria-status ${item.tone}`}>{item.status}</span></div><p>{item.description}</p></article>)}</section>)}
      </div> : null}
    </section>
  );
}

export default RecommendationCriteriaPanel;
