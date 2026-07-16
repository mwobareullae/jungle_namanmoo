import { useState } from "react";
import type { ProductDetail, RecommendationSummary, ScoreBreakdown } from "../../types/recommendation";

type Props = { product: ProductDetail; summary?: RecommendationSummary | null };
type Tone = "ok" | "info" | "warn";
type Item = { label: string; status: string; tone: Tone; description: string };

const scoreState = (score: number | undefined): { status: string; tone: Tone } => {
  if (score === undefined || Number.isNaN(score)) return { status: "정보 없음", tone: "info" };
  if (score >= 75) return { status: "높음", tone: "ok" };
  if (score >= 50) return { status: "보통", tone: "info" };
  return { status: "낮음", tone: "warn" };
};

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

function getGroups(product: ProductDetail, summary?: RecommendationSummary | null) {
  const breakdown = product.score_breakdown;
  const reviewsApplied = breakdown?.review_quality_applied === true && breakdown?.review_profile_affinity_applied === true;
  const concentration = concentrationState(breakdown);
  const risk = (breakdown?.risk_flag_count ?? 0) > 0 || (breakdown?.risk_penalty ?? 0) > 0 || product.risk_flags.length > 0;
  const purchase = summary?.purchase_constraints?.price_text || summary?.purchase_constraints?.price_max_text;
  const price = product.lowest_price === null ? "가격 정보가 공개되지 않았어요." : `${product.lowest_price.toLocaleString("ko-KR")}원 기준으로 살펴봤어요.`;
  const skinScore = breakdown?.skin_profile_score ?? breakdown?.skin_type_match_score;
  const groups: Array<{ title: string; items: Item[] }> = [
    { title: "성분·효능 근거", items: [
      { label: "핵심 성분과 기대 효능", ...scoreState(breakdown?.ingredient_effect_score), description: product.key_ingredients.length ? `${product.key_ingredients.slice(0, 3).join(", ")} 성분과 기대 효능을 비교했어요.` : "핵심 성분 정보가 없어요." },
      { label: "성분 근거 수준", ...scoreState(breakdown?.ingredient_evidence_score), description: product.evidence.length ? `표시 가능한 성분 근거 ${product.evidence.length}건을 확인했어요.` : "표시 가능한 성분 근거가 없어요." },
    ] },
    { title: "내 피부 적합", items: [
      { label: "피부 타입·민감도 적합도", ...scoreState(skinScore), description: "피부 타입과 민감도 조건을 추천 기준에 반영했어요." },
      { label: "리뷰 반영", ...(reviewsApplied ? scoreState(breakdown?.review_quality_score ?? breakdown?.review_profile_affinity_score) : { status: "정보 없음", tone: "info" as const }), description: reviewsApplied ? "적용 가능한 리뷰 신호를 추천 기준에 반영했어요." : "리뷰 데이터 없음 · 중립 처리(점수 유·불리 없음)." },
    ] },
    { title: "요청·취향 적합", items: [
      { label: "가격·카테고리 조건", ...scoreState(breakdown?.price_value_score), description: purchase ? `${price} 요청 조건: ${purchase}` : price },
    ] },
    { title: "함량·안전", items: [
      { label: "함량 상태", ...concentration },
      { label: "주의 성분 및 위험 감점", status: risk ? "주의 필요" : "주의 없음", tone: risk ? "warn" as const : "ok" as const, description: risk ? (breakdown?.risk_warnings?.[0] || product.risk_flags[0] || "주의가 필요한 항목이 있어요.") : "확인된 위험 감점 항목이 없어요." },
    ] },
  ];
  return groups;
}

export default function RecommendationCriteriaMockPanel({ product, summary }: Props) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const concerns = concernsOf(summary);
  const effects = effectsOf(summary);
  const concentration = concentrationState(product.score_breakdown);
  const firstEvidence = product.evidence[0];
  const source = firstEvidence?.source_title ? product.sources.find((item) => item.title === firstEvidence.source_title) : undefined;
  const groups = getGroups(product, summary);
  const weights = product.score_breakdown?.adjusted_weights;
  const largestWeightLabel = getLargestWeightLabel(weights);

  const expandedContent = <>
    <p className="recommendation-mock-sub">입력하신 고민을 효능 → 성분 → 함량 → 근거로 연결해, 이 상품이 왜 맞는지 보여드려요.</p>
    <section className="recommendation-mock-hero">
      <h3>내 고민에서 근거까지</h3><p>각 단계는 실제 추천 응답에서 이어집니다.</p>
      <div className="recommendation-mock-chain">
        <div className="recommendation-mock-node"><b>내 고민</b><div>{concerns.length ? concerns.map((item) => <span className="recommendation-mock-chip" key={item}>{item}</span>) : <em>입력 고민 정보 없음</em>}</div><small>↓ 그래서 필요한 효능은</small></div>
        <div className="recommendation-mock-node"><b>필요한 효능</b><div>{effects.length ? effects.map((item) => <span className="recommendation-mock-chip" key={item}>{item}</span>) : <em>기대 효능 정보 없음</em>}</div><small>↓ 그래서 고른 성분은</small></div>
        <div className="recommendation-mock-node"><b>핵심 성분</b><div>{product.key_ingredients.length ? product.key_ingredients.slice(0, 5).map((item) => <span className="recommendation-mock-chip ingredient" key={item}>{item}</span>) : <em>핵심 성분 정보 없음</em>}</div><small>↓ 이 성분이 이만큼 들었나 (함량)</small></div>
        <div className="recommendation-mock-node"><b>함량 상태</b><div><span className={`recommendation-mock-badge ${concentration.tone}`}>{concentration.status}</span></div><small>↓ 무슨 근거로</small></div>
        <div className="recommendation-mock-node"><b>근거</b><div className="recommendation-mock-evidence">{firstEvidence ? <><strong>{firstEvidence.ingredient_name} → {firstEvidence.effect_name}</strong><span>“{firstEvidence.source_title || firstEvidence.evidence_text}”</span>{source?.url ? <a href={source.url} target="_blank" rel="noreferrer">논문 원문 ↗</a> : null}</> : <em>표시 가능한 성분 근거 없음</em>}</div></div>
      </div>
      <div className="recommendation-mock-reason"><span>한 줄 요약</span><strong>{product.reason_summary || "추천 근거를 준비 중입니다."}</strong></div>
      {largestWeightLabel ? <p className="recommendation-mock-weight">이 추천에서 <b>{largestWeightLabel} 관련 기준이 가장 큰 비중</b></p> : null}
    </section>
    <details className="recommendation-mock-details" open><summary>상세 점수 근거 보기 <span>▸</span></summary><div className="recommendation-mock-groups">{groups.map((group) => <section className="recommendation-mock-group" key={group.title}><h3>{group.title}</h3>{group.items.map((item) => <article key={item.label}><div><strong>{item.label}</strong><span className={`recommendation-mock-badge ${item.tone}`}>{item.status}</span></div><p>{item.description}</p></article>)}</section>)}</div></details>
  </>;

  return <>
    <section className="recommendation-mock-panel recommendation-mock-trigger" aria-label="추천 근거 열기">
      <div className="recommendation-mock-trigger-card">
        <div className="recommendation-mock-trigger-copy"><div className="recommendation-mock-trigger-heading"><img className="recommendation-mock-trigger-robot" src="/mwobareullae-rabbit-chat.png" alt="" /><strong>AI 추천 분석</strong></div><b>왜 이 상품인가요?</b><p>입력하신 고민을 효능 → 성분 → 함량 → 근거로 연결해, 이 상품이 왜 맞는지 보여드려요.</p></div>
        <strong className="recommendation-mock-trigger-score">{Math.round(product.total_score)}점</strong>
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
