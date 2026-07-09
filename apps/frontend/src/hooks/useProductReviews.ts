import { useMemo } from "react";

export type ProductReview = {
  id: string;
  nickname: string;
  initial: string;
  skinType: string;
  skinTone: string;
  concerns: string[];
  irritation: "low" | "medium" | "high";
  rating: number;
  createdAt: string;
  optionName: string;
  body: string;
  photos: string[];
  likeCount: number;
  isRepurchase: boolean;
  usedOverMonth: boolean;
};

export type ProductReviewSummary = {
  averageRating: number;
  totalCount: number;
  ratingDistribution: Record<1 | 2 | 3 | 4 | 5, number>;
  stats: {
    label: string;
    text: string;
    percent: number;
  }[];
};

const mockProductReviews: ProductReview[] = [
  {
    id: "review-001",
    nickname: "민지***",
    initial: "민",
    skinType: "복합성",
    skinTone: "봄웜톤",
    concerns: ["트러블", "블랙헤드"],
    irritation: "low",
    rating: 4,
    createdAt: "2026-06-23",
    optionName: "수지세럼 30mL 기획 (+30mL 리필팩)",
    body: "묽기가 딱 적당해서 흡수도 빠르고, 아침에 써도 끈적임 없이 산뜻했어요. 다만 기대했던 것만큼 보습 지속력은 크지 않았어요.",
    photos: [],
    likeCount: 49,
    isRepurchase: false,
    usedOverMonth: false,
  },
  {
    id: "review-002",
    nickname: "로라레",
    initial: "로",
    skinType: "건성",
    skinTone: "겨울쿨톤",
    concerns: ["미백", "주름"],
    irritation: "low",
    rating: 5,
    createdAt: "2026-06-27",
    optionName: "세럼 30mL (+크림 30mL)",
    body: "가벼운 수분세럼이라 여름철에 쓰기 좋아요. 점도가 살짝 있으면서 촉촉한 제형이라 베이스가 쫀쫀하게 잘 먹었고, 번들거리거나 끈적이지 않아서 부담이 없었어요.",
    photos: ["review-photo-soft-blue", "review-photo-cream"],
    likeCount: 12,
    isRepurchase: false,
    usedOverMonth: true,
  },
  {
    id: "review-003",
    nickname: "지우***",
    initial: "지",
    skinType: "복합성",
    skinTone: "20대",
    concerns: ["진정", "속건조"],
    irritation: "low",
    rating: 4,
    createdAt: "2026-06-20",
    optionName: "세럼 단품 30mL",
    body: "AI 추천으로 알게 된 제품인데 실제로 써보니 근거 태그에 나온 진정 효과가 체감돼요. 재구매 의사 있습니다.",
    photos: [],
    likeCount: 5,
    isRepurchase: true,
    usedOverMonth: false,
  },
  {
    id: "review-004",
    nickname: "수연",
    initial: "수",
    skinType: "수부지",
    skinTone: "여름쿨톤",
    concerns: ["모공", "피지"],
    irritation: "medium",
    rating: 5,
    createdAt: "2026-06-29",
    optionName: "더블 기획 30mL x 2",
    body: "오후 유분이 신경 쓰이는 피부인데 산뜻하게 마무리돼서 만족했어요. 메이크업 전에 발라도 밀림이 거의 없었습니다.",
    photos: ["review-photo-shelf"],
    likeCount: 31,
    isRepurchase: true,
    usedOverMonth: true,
  },
  {
    id: "review-005",
    nickname: "하나***",
    initial: "하",
    skinType: "민감성",
    skinTone: "가을웜톤",
    concerns: ["홍조", "장벽"],
    irritation: "low",
    rating: 5,
    createdAt: "2026-06-18",
    optionName: "민감 피부 기획 세트",
    body: "향이 강하지 않고 따갑지 않아서 좋았어요. 피부가 예민한 날에도 부담 없이 바르기 괜찮았습니다.",
    photos: [],
    likeCount: 28,
    isRepurchase: false,
    usedOverMonth: true,
  },
  {
    id: "review-006",
    nickname: "다은",
    initial: "다",
    skinType: "지성",
    skinTone: "봄웜톤",
    concerns: ["피지", "블랙헤드"],
    irritation: "medium",
    rating: 3,
    createdAt: "2026-06-12",
    optionName: "세럼 30mL",
    body: "흡수는 빠른데 제 피부에는 살짝 건조하게 느껴졌어요. 산뜻한 마무리를 좋아하면 괜찮을 것 같아요.",
    photos: [],
    likeCount: 8,
    isRepurchase: false,
    usedOverMonth: false,
  },
  {
    id: "review-007",
    nickname: "유나***",
    initial: "유",
    skinType: "건성",
    skinTone: "겨울쿨톤",
    concerns: ["속건조", "각질"],
    irritation: "low",
    rating: 5,
    createdAt: "2026-06-30",
    optionName: "세럼 30mL + 미니어처",
    body: "세안 후 바로 발랐을 때 당김이 줄어드는 느낌이 좋아요. 한 달 넘게 쓰면서 피부결이 편안해졌습니다.",
    photos: ["review-photo-dropper"],
    likeCount: 44,
    isRepurchase: true,
    usedOverMonth: true,
  },
  {
    id: "review-008",
    nickname: "예린",
    initial: "예",
    skinType: "중성",
    skinTone: "여름쿨톤",
    concerns: ["미백", "피부톤"],
    irritation: "low",
    rating: 4,
    createdAt: "2026-06-17",
    optionName: "브라이트닝 세럼 30mL",
    body: "즉각적인 톤업보다는 꾸준히 쓰기 좋은 촉촉한 세럼 느낌이에요. 피부 표현이 맑아 보여서 계속 쓰고 있습니다.",
    photos: [],
    likeCount: 18,
    isRepurchase: false,
    usedOverMonth: true,
  },
  {
    id: "review-009",
    nickname: "서아***",
    initial: "서",
    skinType: "복합성",
    skinTone: "가을웜톤",
    concerns: ["트러블", "진정"],
    irritation: "low",
    rating: 5,
    createdAt: "2026-06-26",
    optionName: "트러블 케어 세트",
    body: "붉게 올라온 날 저녁에 바르면 다음 날 피부가 덜 예민해 보여요. 산뜻하지만 속은 편안하게 잡아주는 편입니다.",
    photos: ["review-photo-bath"],
    likeCount: 37,
    isRepurchase: false,
    usedOverMonth: false,
  },
  {
    id: "review-010",
    nickname: "채린",
    initial: "채",
    skinType: "수부지",
    skinTone: "봄웜톤",
    concerns: ["속건조", "모공"],
    irritation: "low",
    rating: 4,
    createdAt: "2026-06-10",
    optionName: "수분 세럼 30mL",
    body: "수분감은 좋은데 많이 바르면 살짝 번들거려서 양 조절이 필요했어요. 적당히 바르면 피부가 편해요.",
    photos: [],
    likeCount: 14,
    isRepurchase: false,
    usedOverMonth: false,
  },
  {
    id: "review-011",
    nickname: "나윤***",
    initial: "나",
    skinType: "민감성",
    skinTone: "겨울쿨톤",
    concerns: ["장벽", "홍조"],
    irritation: "low",
    rating: 5,
    createdAt: "2026-06-15",
    optionName: "장벽 케어 세럼",
    body: "피부가 얇은 편인데 따갑지 않았고, 크림 전에 바르면 보습감이 오래 갔어요. 재구매해서 엄마랑 같이 쓰는 중입니다.",
    photos: ["review-photo-pouch", "review-photo-texture"],
    likeCount: 52,
    isRepurchase: true,
    usedOverMonth: true,
  },
  {
    id: "review-012",
    nickname: "소희",
    initial: "소",
    skinType: "지성",
    skinTone: "여름쿨톤",
    concerns: ["피지", "모공"],
    irritation: "medium",
    rating: 2,
    createdAt: "2026-06-05",
    optionName: "세럼 단품 30mL",
    body: "제 피부에는 보습감이 조금 부족했고, 기대만큼 모공 쪽 변화는 크지 않았어요. 산뜻한 사용감은 괜찮았습니다.",
    photos: [],
    likeCount: 3,
    isRepurchase: false,
    usedOverMonth: false,
  },
];

const buildReviewSummary = (reviews: ProductReview[]): ProductReviewSummary => {
  const totalCount = reviews.length;
  const ratingDistribution = reviews.reduce<ProductReviewSummary["ratingDistribution"]>(
    (result, review) => {
      result[review.rating as 1 | 2 | 3 | 4 | 5] += 1;
      return result;
    },
    { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
  );
  const ratingSum = reviews.reduce((sum, review) => sum + review.rating, 0);

  return {
    averageRating: Number((ratingSum / totalCount).toFixed(1)),
    totalCount,
    ratingDistribution,
    stats: [
      { label: "피부타입", text: "건성에 좋아요", percent: 53 },
      { label: "피부고민", text: "보습에 좋아요", percent: 71 },
      { label: "자극도", text: "자극없이 순해요", percent: 76 },
    ],
  };
};

export const useProductReviews = (_productId: string | null | undefined) => {
  return useMemo(
    () => ({
      reviews: mockProductReviews,
      summary: buildReviewSummary(mockProductReviews),
    }),
    []
  );
};
