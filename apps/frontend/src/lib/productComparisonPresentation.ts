export type ProductComparisonProfile = {
  expectedEffects: readonly string[];
  matchedConcerns: readonly string[];
};

const similarityReasonLabels: Record<string, string> = {
  same_category: "같은 카테고리",
  shared_effects: "기대 효능 유사",
  shared_ingredients: "핵심 성분 유사",
  similar_price: "가격대 비슷",
  similar_skin_profile: "피부 타입 유사",
};

const uniqueValues = (values: readonly string[]) => Array.from(new Set(
  values.map((value) => value.trim()).filter(Boolean),
));

export const getSimilarityReasonLabels = (matchReasons: readonly string[]) =>
  uniqueValues(matchReasons)
    .flatMap((reason) => similarityReasonLabels[reason] ? [similarityReasonLabels[reason]] : [])
    .slice(0, 3);
