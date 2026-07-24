import { useState } from "react";
import type { ProductDetail, RecommendationSummary, ScoreBreakdown } from "../../types/recommendation";

type Props = { product: ProductDetail; summary?: RecommendationSummary | null };

const concentrationState = (breakdown?: ScoreBreakdown) => {
  switch (breakdown?.concentration_bucket) {
    case "optimal":
      return { status: "적정", tone: "ok" as const, description: "함량 구간과 근거 데이터를 기준으로 적정 수준으로 분류했어요." };
    case "meaningful":
      return { status: "의미 있는 수준", tone: "ok" as const, description: "함량 구간과 근거 데이터를 기준으로 의미 있는 수준으로 분류했어요." };
    case "below_meaningful":
      return { status: "기준 미달", tone: "warn" as const, description: "현재 확인된 함량이 기대 효능을 뒷받침하기에 충분하지 않을 수 있어요." };
    case "above_optimal":
      return { status: "권장 범위 초과", tone: "warn" as const, description: "확인된 함량이 일반적인 권장 범위를 넘어 주의가 필요해요." };
    case "excessive":
      return { status: "과다 사용 주의", tone: "warn" as const, description: "함량이 높은 편으로 사용 전 주의사항을 확인해 주세요." };
    case "unknown":
    default:
      return { status: "정보 없음", tone: "info" as const, description: "함량 정보가 공개되지 않았어요." };
  }
};

const concernsOf = (summary?: RecommendationSummary | null) => summary?.matched_concerns ?? summary?.concerns ?? [];
const effectsOf = (summary?: RecommendationSummary | null) => summary?.expected_effects ?? summary?.effects ?? [];

const getLargestWeightLabel = (weights?: Record<string, number>) => {
  if (!weights) return null;
  const entries = Object.entries(weights).filter(([, value]) => typeof value === "number" && Number.isFinite(value));
  if (!entries.length) return null;
  const [key] = entries.reduce((largest, current) => current[1] > largest[1] ? current : largest);
  const normalized = key.toLowerCase();
  if (normalized.includes("ingredient_effect") || normalized.includes("ingredient_evidence")) return "성분·효능 근거";
  if (normalized.includes("concentration")) return "함량";
  if (normalized.includes("skin") || normalized.includes("sensitivity") || normalized.includes("behavior") || normalized.includes("review_profile")) return "내 피부 적합도";
  if (normalized.includes("price") || normalized.includes("search") || normalized.includes("keyword") || normalized.includes("market") || normalized.includes("review_quality")) return "구매·시장 신호";
  return "상품 기준";
};

export default function RecommendationCriteriaMockPanel({ product, summary }: Props) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const concerns = concernsOf(summary);
  const effects = effectsOf(summary);
  const concentration = concentrationState(product.score_breakdown);
  const firstEvidence = product.evidence[0];
  const source = firstEvidence?.source_title ? product.sources.find((item) => item.title === firstEvidence.source_title) : undefined;
  const weights = product.score_breakdown?.adjusted_weights;
  const largestWeightLabel = getLargestWeightLabel(weights);

  const expandedContent = <>
    <p className="recommendation-mock-sub">입력하신 고민을 효능 → 성분 → 함량 → 근거로 연결해, 이 상품이 왜 맞는지 보여드려요.</p>
    <section className="recommendation-mock-hero">
      <h3>내 고민에서 근거까지</h3><p>각 단계는 실제 추천 응답에서 이어집니다.</p>
      <div className="recommendation-mock-chain">
        <div className="recommendation-mock-node"><b>내 고민</b><div>{concerns.length ? concerns.map((item) => <span className="recommendation-mock-chip" key={item}>{item}</span>) : <em>입력 고민 정보 없음</em>}</div></div>
        <div className="recommendation-mock-node"><b>그래서 필요한 효능은</b><div>{effects.length ? effects.map((item) => <span className="recommendation-mock-chip" key={item}>{item}</span>) : <em>기대 효능 정보 없음</em>}</div></div>
        <div className="recommendation-mock-node"><b>그래서 고른 성분은</b><div>{product.key_ingredients.length ? product.key_ingredients.slice(0, 5).map((item) => <span className="recommendation-mock-chip ingredient" key={item}>{item}</span>) : <em>핵심 성분 정보 없음</em>}</div></div>
        <div className="recommendation-mock-node"><b>성분 함량은 충분한가</b><div><span className={`recommendation-mock-badge ${concentration.tone}`}>{concentration.status}</span></div></div>
        <div className="recommendation-mock-node"><b>성분 근거는</b><div className="recommendation-mock-evidence">{firstEvidence ? <><strong>{firstEvidence.ingredient_name} → {firstEvidence.effect_name}</strong><span>“{firstEvidence.source_title || firstEvidence.evidence_text}”</span>{source?.url ? <a href={source.url} target="_blank" rel="noreferrer">논문 원문 ↗</a> : null}</> : <em>표시 가능한 성분 근거 없음</em>}</div></div>
      </div>
      <div className="recommendation-mock-reason"><span>한 줄 요약</span><strong>{product.reason_summary || "추천 근거를 준비 중입니다."}</strong></div>
      {largestWeightLabel ? <p className="recommendation-mock-weight">이 추천에서 <b>{largestWeightLabel}</b> 관련 기준이 가장 큰 비중을 차지했습니다.</p> : null}
    </section>
  </>;

  return <>
    <section className="recommendation-mock-panel recommendation-mock-trigger" aria-label="추천 근거 열기">
      <div className="recommendation-mock-trigger-card">
        <div className="recommendation-mock-trigger-copy"><div className="recommendation-mock-trigger-heading"><img className="recommendation-mock-trigger-robot" src="/mwobareullae-rabbit-chat.png" alt="" /><strong>AI 추천 분석</strong></div></div>
        <strong className="recommendation-mock-trigger-score">{Math.round(product.total_score)}점</strong>
        <b className="recommendation-mock-trigger-question">왜 이 상품인가요?</b>
        <button className="recommendation-mock-trigger-button" type="button" onClick={() => setIsModalOpen(true)}>자세히 보기</button>
      </div>
    </section>
    {isModalOpen ? <div className="recommendation-mock-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setIsModalOpen(false); }}>
      <section className="recommendation-mock-modal" role="dialog" aria-modal="true" aria-label="추천 근거">
        <button className="recommendation-mock-modal-close" type="button" aria-label="추천 근거 닫기" onClick={() => setIsModalOpen(false)}>×</button>
        <h2 className="recommendation-mock-modal-title">왜 이 상품을 추천했나요?</h2>
        {expandedContent}
      </section>
    </div> : null}
  </>;
}
