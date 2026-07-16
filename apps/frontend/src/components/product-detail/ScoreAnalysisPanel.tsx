import { useState } from "react";
import type { ProductDetail } from "../../types/recommendation";

type Props = { product: ProductDetail };
type Axis = { key: string; label: string; score?: number; status: string; description: string };

const labels: Array<{ key: string; label: string; group: string }> = [
  { key: "ingredient_effect_score", label: "성분이 기대 효능에 맞는지", group: "성분과 효능 근거" }, { key: "ingredient_evidence_score", label: "성분 근거의 신뢰도", group: "성분과 효능 근거" }, { key: "concentration_fit_score", label: "성분 함량 적합도", group: "성분과 효능 근거" }, { key: "functional_claim_score", label: "기능성 정보", group: "성분과 효능 근거" },
  { key: "skin_profile_score", label: "피부 타입 적합도", group: "내 피부와의 적합도" }, { key: "skin_test_context_score", label: "피부 고민 테스트 반영", group: "내 피부와의 적합도" }, { key: "behavior_personalization_score", label: "관심·사용 기록 반영", group: "내 피부와의 적합도" }, { key: "review_profile_affinity_score", label: "비슷한 피부 리뷰", group: "내 피부와의 적합도" },
  { key: "search_match_score", label: "입력한 고민과의 일치", group: "구매 조건과 인기" }, { key: "price_value_score", label: "가격 조건", group: "구매 조건과 인기" }, { key: "market_signal_score", label: "상품 인기", group: "구매 조건과 인기" }, { key: "review_quality_score", label: "리뷰 만족도 데이터", group: "구매 조건과 인기" },
];

function weightFor(weights: Record<string, number> | undefined, key: string) {
  const explicitAliases: Record<string, string[]> = {
    price_value_score: ["price"],
    skin_profile_score: ["skin_type_match_score"],
    search_match_score: ["keyword_score"],
  };
  const aliases = [key, key.replace(/_score$/, ""), ...(explicitAliases[key] ?? [])].filter(Boolean);
  const value = aliases.map((alias) => weights?.[alias]).find((item) => typeof item === "number");
  return typeof value === "number" ? (Math.abs(value) <= 1 ? value * 100 : value) : undefined;
}

function axisData(product: ProductDetail): Axis[] {
  const score = product.score_breakdown;
  const skin = score?.skin_profile_score ?? score?.skin_type_match_score;
  const search = score?.search_match_score ?? score?.keyword_score;
  const reviewApplied = score?.review_quality_applied === true;
  const profileReviewApplied = score?.review_profile_affinity_applied === true;
  const skinTestApplied = score?.skin_test_context_applied === true;
  const behaviorApplied = score?.behavior_personalization_applied === true;
  return labels.map(({ key, label }) => {
    const value = key === "skin_profile_score" ? skin : key === "search_match_score" ? search : score?.[key as keyof typeof score];
    const numeric = typeof value === "number" ? value : undefined;
    if (key === "review_quality_score" && !reviewApplied) return { key, label, score: numeric, status: "데이터 부족", description: "아직 충분한 리뷰 정보가 없어 유리하거나 불리하지 않게 반영했어요." };
    if (key === "review_profile_affinity_score" && !profileReviewApplied) return { key, label, score: numeric, status: "데이터 부족", description: "비슷한 피부의 리뷰 정보가 부족해 중립적으로 반영했어요." };
    if (key === "skin_test_context_score" && !skinTestApplied) return { key, label, score: numeric, status: "데이터 부족", description: "연결된 피부 고민 테스트 결과가 없어 이 기준의 가중치를 제외했어요." };
    if (key === "behavior_personalization_score" && !behaviorApplied) return { key, label, score: numeric, status: "데이터 부족", description: "추천에 사용할 조회·찜·장바구니 기록이 없어 이 기준의 가중치를 제외했어요." };
    if (key === "search_match_score" && numeric === 0) return { key, label, score: numeric, status: "매칭 없음", description: "입력한 고민과 일치하는 검색 기준을 찾지 못했어요." };
    if (numeric === undefined) return { key, label, status: "정보 없음", description: "API 응답에 이 기준의 점수 정보가 없어 표시하지 못했어요." };
    return { key, label, score: numeric, status: "반영됨", description: "이 기준을 추천 점수에 반영했어요." };
  });
}

export default function ScoreAnalysisPanel({ product }: Props) {
  const [openAxes, setOpenAxes] = useState<Set<string>>(new Set());
  const breakdown = product.score_breakdown;
  if (!breakdown) return null;
  const groups = ["성분과 효능 근거", "내 피부와의 적합도", "구매 조건과 인기"].map((title) => ({ title, items: axisData(product).filter((axis) => labels.find((item) => item.key === axis.key)?.group === title) }));
  const axes = groups.flatMap((group) => group.items);
  const weights = breakdown.adjusted_weights;
  const riskCount = breakdown.risk_flag_count ?? 0;
  const riskPenalty = breakdown.risk_penalty ?? 0;
  return <article className="naver-preview-score-analysis"><h2>점수분석</h2><div className="naver-preview-score-intro"><strong>최종 추천 점수 {Math.round(product.total_score)}점</strong><span>{product.reason_summary || "상품 정보를 여러 기준으로 살펴본 결과예요."}</span></div><div className="naver-preview-score-controls"><button type="button" onClick={() => setOpenAxes(new Set(axes.map((axis) => axis.key)))}>전체 펼치기</button><button type="button" onClick={() => setOpenAxes(new Set())}>전체 닫기</button></div><div className="naver-preview-score-grid">{axes.map((axis) => { const weight = weightFor(weights, axis.key); const contribution = typeof axis.score === "number" && typeof weight === "number" ? axis.score * weight / 100 : undefined; return <details className="naver-preview-score-card" key={axis.key} open={openAxes.has(axis.key)} onToggle={(event) => { const nextOpen = event.currentTarget.open; setOpenAxes((current) => { const next = new Set(current); if (nextOpen) next.add(axis.key); else next.delete(axis.key); return next; }); }}><summary><span>{axis.label}<em className={`naver-preview-score-status ${axis.status === "반영됨" ? "is-applied" : "is-neutral"}`}>{axis.status}</em></span><strong>{typeof contribution === "number" ? `${contribution.toFixed(1)}점` : "-"}</strong></summary><p>{axis.description}</p><div className="naver-preview-score-metrics">기준 점수 {typeof axis.score === "number" ? `${Math.round(axis.score)}점` : "-"} · 반영 비중 {typeof weight === "number" ? `${weight.toFixed(1)}%` : "-"} · 최종 반영 {typeof contribution === "number" ? `${contribution.toFixed(1)}점` : "-"}</div></details>; })}</div><div className={`naver-preview-score-warning${riskCount || riskPenalty > 0 ? " is-risk" : ""}`}>{riskCount || riskPenalty > 0 ? <>주의가 필요한 성분 {riskCount}개 · 추천 점수에 {riskPenalty}점 반영{breakdown.risk_warnings?.length ? <ul>{breakdown.risk_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}</> : "주의 없음 · 확인된 위험 성분이 없어요."}</div></article>;
}
