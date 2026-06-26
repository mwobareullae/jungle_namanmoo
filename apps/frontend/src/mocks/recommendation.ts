import type {
  ProductCardItem,
  ProductDetail,
  RecommendationRequest,
  RecommendationResponse
} from "../types/recommendation";

const mockImage = (seed: string, width = 720, height = 900) =>
  `https://picsum.photos/seed/mwobareullae-${seed}/${width}/${height}`;

const products: ProductDetail[] = [
  {
    product_id: "prod_001",
    rank: 1,
    total_score: 94,
    reason_summary: "수분 장벽과 진정 효능이 함께 필요할 때 맞는 성분 구성이에요.",
    brand: "MAISON CREME",
    name: "Hydra Veil Serum",
    thumbnail_url: mockImage("prod-001-thumb"),
    lowest_price: 19900,
    evidence_tags: ["성분 근거", "장벽 보습", "진정"],
    key_ingredients: ["히알루론산", "판테놀", "세라마이드"],
    risk_flags: [],
    score_breakdown: {
      ingredient_effect_score: 35,
      ingredient_evidence_score: 26,
      skin_type_match_score: 22,
      price_value_score: 11
    },
    image_urls: [mockImage("prod-001-detail-1"), mockImage("prod-001-detail-2")],
    content_confidence: "high",
    related_ingredients: ["히알루론산", "판테놀", "세라마이드"],
    purchase_url: "https://example.com/products/prod_001",
    evidence: [
      {
        ingredient_name: "판테놀",
        effect_name: "진정",
        evidence_level: "high",
        evidence_text: "피부 장벽 보조와 자극 완화 목적에 자주 쓰이는 성분입니다."
      },
      {
        ingredient_name: "세라마이드",
        effect_name: "장벽 강화",
        evidence_level: "high",
        evidence_text: "피부 지질 장벽을 보완해 수분 손실 관리에 도움을 줍니다."
      }
    ]
  },
  {
    product_id: "prod_002",
    rank: 2,
    total_score: 88,
    reason_summary: "모공과 피지 고민에 맞춰 나이아신아마이드와 아연 PCA를 우선 반영했어요.",
    brand: "ATELIER N",
    name: "Pore Refining Essence",
    thumbnail_url: mockImage("prod-002-thumb"),
    lowest_price: 24500,
    evidence_tags: ["피지 조절", "모공", "부분 매칭"],
    key_ingredients: ["나이아신아마이드", "아연 PCA"],
    risk_flags: ["향료"],
    score_breakdown: {
      ingredient_effect_score: 32,
      ingredient_evidence_score: 24,
      skin_type_match_score: 21,
      price_value_score: 11
    },
    image_urls: [mockImage("prod-002-detail-1"), mockImage("prod-002-detail-2")],
    content_confidence: "medium",
    related_ingredients: ["나이아신아마이드", "아연 PCA"],
    purchase_url: "https://example.com/products/prod_002",
    evidence: [
      {
        ingredient_name: "나이아신아마이드",
        effect_name: "피지 조절",
        evidence_level: "medium",
        evidence_text: "피지와 모공 관련 고민에서 우선 검토할 수 있는 고시 성분입니다."
      }
    ]
  },
  {
    product_id: "prod_003",
    rank: 3,
    total_score: 91,
    reason_summary: "민감도가 높을 때 진정 성분 중심으로 보수적으로 추천했어요.",
    brand: "HERBARIUM",
    name: "Calming Centella Ampoule",
    thumbnail_url: mockImage("prod-003-thumb"),
    lowest_price: null,
    evidence_tags: ["진정", "민감 피부", "가격 정보 없음"],
    key_ingredients: ["마데카소사이드", "알란토인", "판테놀"],
    risk_flags: [],
    score_breakdown: {
      ingredient_effect_score: 34,
      ingredient_evidence_score: 25,
      skin_type_match_score: 24,
      price_value_score: 8
    },
    image_urls: [mockImage("prod-003-detail-1"), mockImage("prod-003-detail-2")],
    content_confidence: "low",
    related_ingredients: ["마데카소사이드", "알란토인", "판테놀"],
    purchase_url: null,
    evidence: []
  },
  {
    product_id: "prod_004",
    rank: 4,
    total_score: 82,
    reason_summary: "좁쌀과 각질 고민에는 일부만 맞지만 가격 접근성이 좋아 후보로 남겼어요.",
    brand: "TERRA",
    name: "Clear Balance Drops",
    thumbnail_url: mockImage("prod-004-thumb"),
    lowest_price: 15900,
    evidence_tags: ["부분 매칭", "가격 접근성"],
    key_ingredients: ["살리실산", "아연 PCA"],
    risk_flags: ["고함량 알코올"],
    score_breakdown: {
      ingredient_effect_score: 28,
      ingredient_evidence_score: 22,
      skin_type_match_score: 18,
      price_value_score: 14
    },
    image_urls: [mockImage("prod-004-detail-1"), mockImage("prod-004-detail-2")],
    content_confidence: "unknown",
    related_ingredients: ["살리실산", "아연 PCA"],
    purchase_url: "https://example.com/products/prod_004",
    evidence: [
      {
        ingredient_name: "살리실산",
        effect_name: "각질 정돈",
        evidence_level: "medium",
        evidence_text: "BHA 계열 성분으로 모공 속 각질과 피지 관리에 활용됩니다."
      }
    ]
  }
];

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const buildSummary = (request: RecommendationRequest) => {
  const text = request.concern_text;
  const concerns = new Set<string>([request.skin_type]);
  const effects = new Set<string>();
  const unmatchedTerms: string[] = [];

  if (text.includes("모공")) {
    concerns.add("모공");
    effects.add("피지 조절");
  }

  if (text.includes("좁쌀") || text.includes("여드름")) {
    concerns.add("트러블");
    effects.add("진정");
    unmatchedTerms.push("좁쌀 여드름은 Phase 0에서 부분 매칭으로 처리");
  }

  if (text.includes("건조") || request.skin_type === "건성" || request.skin_type === "수부지") {
    concerns.add("속건조");
    effects.add("장벽 보습");
  }

  if (request.sensitivity === "높음" || text.includes("민감") || text.includes("진정")) {
    concerns.add("민감");
    effects.add("진정");
  }

  if (effects.size === 0) {
    effects.add("성분 근거 확인");
    unmatchedTerms.push("입력 고민을 표준 효능으로 완전히 매핑하지 못함");
  }

  return {
    concerns: Array.from(concerns),
    effects: Array.from(effects),
    unmatchedTerms
  };
};

export const mockRecommendationApi = {
  async createRecommendation(request: RecommendationRequest): Promise<RecommendationResponse> {
    const waitMs = request.concern_text.includes("지연") ? 16000 : 900;
    await delay(waitMs);

    if (request.concern_text.includes("실패")) {
      throw { status: 500, message: "mock recommendation failed" };
    }

    const { concerns, effects, unmatchedTerms } = buildSummary(request);
    const filteredProducts: ProductCardItem[] = request.concern_text.includes("빈결과")
      ? []
      : products.map((product) =>
          clone({
            product_id: product.product_id,
            rank: product.rank,
            total_score: product.total_score,
            reason_summary: product.reason_summary,
            brand: product.brand,
            name: product.name,
            thumbnail_url: product.thumbnail_url,
            lowest_price: product.lowest_price,
            evidence_tags: product.evidence_tags,
            key_ingredients: product.key_ingredients,
            risk_flags: product.risk_flags,
            score_breakdown: product.score_breakdown
          })
        );

    return {
      recommendation_id: `rec_${Date.now()}`,
      summary: {
        concerns,
        effects
      },
      unmatched_terms: unmatchedTerms,
      products: filteredProducts
    };
  },

  async getProduct(productId: string): Promise<ProductDetail> {
    await delay(300);
    const product = products.find((item) => item.product_id === productId);

    if (!product) {
      throw { status: 404, message: "product not found" };
    }

    return clone(product);
  }
};
