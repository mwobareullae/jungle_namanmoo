import { useState, type ReactNode } from "react";
import type { ProductDetail } from "../types/recommendation";

export type ProductComparisonDifference = {
  base?: string | null;
  compare?: string | null;
  description?: string | null;
  label: string;
};

type ProductComparisonSource = "comparison" | "similar";

type ProductComparisonPanelProps = {
  differences: ProductComparisonDifference[];
  errorMessage?: string;
  expectedProductCount: number;
  initiallyPriceOnly?: boolean;
  isLoading: boolean;
  onClose: () => void;
  products: ProductDetail[];
  recommendationReason?: string;
  sensitivity?: string;
  skinType?: string;
  source: ProductComparisonSource;
  summary?: string;
};

type ProductComparisonDecisionSummary = {
  caution: string;
  differentiator: string;
  externalNote?: string;
  priceValue: string;
  recommendedProductName?: string;
  routineTip: string;
  selectionCriteria: string;
  skinFit: string;
  verdict: string;
};

type ProductComparisonScenarioGuideItem = {
  label: ProductScenarioTagLabel;
  productName: string;
  reason: string;
  roleLabel: string;
  tone?: "caution";
};

type ProductScenarioTagLabel =
  | "성분 근거 우선"
  | "핵심 성분 차이"
  | "가격 부담 낮춤"
  | "가성비 비교"
  | "민감 피부 고려"
  | "주의 성분 적음"
  | "보습 집중"
  | "진정 포인트"
  | "장벽 성분"
  | "산뜻한 사용감"
  | "유분 부담 적음"
  | "데일리로 무난"
  | "전성분 확인"
  | "종합 점수 우선";

type ProductScenarioTag = {
  label: ProductScenarioTagLabel;
  tone?: "caution";
};

type ProductScenarioTagContext = {
  lowestPrice: number | null;
  maxEvidenceStrength: number;
  maxRiskCount: number;
  maxScore: number;
  minRiskCount: number;
  sensitivity?: string;
};

type ProductComparisonTableRow = {
  comparisonValues: string[];
  label: string;
  values: ReactNode[];
};

type ProductComparisonCardVariant = "current" | "candidate";

const MAX_SIMILAR_PRODUCTS = 2;

const formatPrice = (price: number | null) =>
  price === null ? "가격 확인 중이에요" : `${price.toLocaleString("ko-KR")}원`;

const joinValues = (values: string[], fallback = "확인 중이에요") =>
  values.filter(Boolean).slice(0, 4).join(", ") || fallback;

const uniqueValues = (values: string[]) => Array.from(new Set(values.filter(Boolean)));

const getSharedValues = (groups: string[][]) => {
  if (groups.length < 2) return [];

  const [firstGroup, ...restGroups] = groups.map((group) => new Set(group.filter(Boolean)));
  return Array.from(firstGroup).filter((value) => restGroups.every((group) => group.has(value)));
};

const getProductLabel = (product: ProductDetail) => product.brand || product.name;

const getProductFullLabel = (product: ProductDetail) =>
  product.brand ? `${product.brand} ${product.name}` : product.name;

const sanitizeCosmeticClaimText = (text: string) =>
  text
    .replace(/\s+/g, " ")
    .replace(/반드시\s*/g, "")
    .replace(/무조건\s*/g, "")
    .trim();

const isSensitiveProfile = (sensitivity?: string) =>
  Boolean(sensitivity && /(높음|민감|예민)/.test(sensitivity));

const getProfileLabel = (skinType?: string, sensitivity?: string) =>
  uniqueValues([
    skinType ? `${skinType} 피부` : "",
    sensitivity ? `민감도 ${sensitivity}` : "",
  ]).join(" + ");

const getRecommendedProduct = (
  products: ProductDetail[],
  sensitivity?: string,
) => {
  const shouldPrioritizeRisk = isSensitiveProfile(sensitivity);

  return [...products].sort((a, b) => {
    if (shouldPrioritizeRisk && a.risk_flags.length !== b.risk_flags.length) {
      return a.risk_flags.length - b.risk_flags.length;
    }

    if (a.total_score !== b.total_score) {
      return b.total_score - a.total_score;
    }

    if (a.risk_flags.length !== b.risk_flags.length) {
      return a.risk_flags.length - b.risk_flags.length;
    }

    if (a.lowest_price === null) return 1;
    if (b.lowest_price === null) return -1;
    return a.lowest_price - b.lowest_price;
  })[0] ?? null;
};

const getCheapestProduct = (products: ProductDetail[]) =>
  products.reduce<ProductDetail | null>((currentCheapest, product) => {
    if (product.lowest_price === null) return currentCheapest;
    if (!currentCheapest || currentCheapest.lowest_price === null) return product;
    return product.lowest_price < currentCheapest.lowest_price ? product : currentCheapest;
  }, null);

const getLowestComparablePrice = (products: ProductDetail[]) =>
  products.reduce<number | null>((lowestPrice, product) => {
    if (product.lowest_price === null) return lowestPrice;
    if (lowestPrice === null) return product.lowest_price;
    return Math.min(lowestPrice, product.lowest_price);
  }, null);

const getReviewComparisonValue = (product: ProductDetail) => {
  const rating = product.review_summary?.average_rating;
  return rating === null || rating === undefined ? "평점 정보 없음" : `${rating.toFixed(1)}점`;
};

const getPurchaseComparisonValue = (product: ProductDetail) => {
  if (!product.purchase_info) return "구매 상태 정보 없음";
  if (!product.purchase_info.can_purchase) return "현재 구매 불가";
  return product.purchase_info.available_quantity === 0 ? "일시 품절" : "구매 가능";
};

const getCautionComparisonValue = (product: ProductDetail) =>
  product.risk_flags.length > 0 ? joinValues(product.risk_flags, "") : "확인된 주의 성분 없음";

const getCautionIngredientNames = (product: ProductDetail) =>
  uniqueValues(
    product.risk_flags.map((riskFlag) => riskFlag.split(":", 1)[0]?.trim() ?? ""),
  );

const renderInlineCautionComparisonValue = (product: ProductDetail) => {
  const ingredientNames = getCautionIngredientNames(product);
  if (ingredientNames.length === 0) return "확인된 주의 성분 없음";

  return <span className="product-comparison-caution-value">{joinValues(ingredientNames, "")}</span>;
};

const getProductUniqueValues = (
  product: ProductDetail,
  products: ProductDetail[],
  key: "evidence_tags" | "key_ingredients",
) =>
  uniqueValues(product[key]).filter(
    (value) => !products.some((otherProduct) => otherProduct.product_id !== product.product_id && otherProduct[key].includes(value)),
  );

const getVerdictText = (
  products: ProductDetail[],
  source: ProductComparisonSource,
  skinType?: string,
  sensitivity?: string,
) => {
  const recommendedProduct = getRecommendedProduct(products, sensitivity);
  if (!recommendedProduct) {
    return source === "similar"
      ? "비슷한 상품을 불러오고 있어요. 준비되면 먼저 볼 만한 후보를 정리해드릴게요."
      : "비교할 상품을 불러오고 있어요. 곧 선택 포인트를 정리해드릴게요.";
  }

  const profileLabel = getProfileLabel(skinType, sensitivity);
  const primaryEffect = recommendedProduct.evidence_tags[0];

  if (profileLabel) {
    return sanitizeCosmeticClaimText(
      `${profileLabel} 기준으로 보면 먼저 확인해봐도 좋아요. ${primaryEffect ? `${primaryEffect} 포인트도 함께 봐주세요.` : "피부 고민과 성분 기준을 같이 봐주세요."}`,
    );
  }

  if (recommendedProduct.risk_flags.length === 0) {
    return "체크할 성분 부담이 낮은 편이라 먼저 보기 좋아요. 민감한 피부라면 전성분만 한 번 더 확인해주세요.";
  }

  if (primaryEffect) {
    return `${primaryEffect} 포인트가 보여서 먼저 비교해볼 만해요. 가격과 성분 차이도 같이 확인해보세요.`;
  }

  return "피부 고민과 성분 기준을 같이 봤을 때 먼저 확인해보면 좋아요.";
};

const getDifferentiatorText = (products: ProductDetail[]) => {
  if (products.length < 2) {
    return "비슷한 상품을 불러오면 성분, 가격, 추천 근거의 차이를 함께 정리해드릴게요.";
  }

  const differenceLines = products.map((product) => {
    const uniqueEffects = getProductUniqueValues(product, products, "evidence_tags");
    const uniqueIngredients = getProductUniqueValues(product, products, "key_ingredients");
    const focus = uniqueEffects.length > 0
      ? uniqueEffects.slice(0, 2).join(", ")
      : uniqueIngredients.length > 0
        ? uniqueIngredients.slice(0, 2).join(", ")
        : null;
    return focus ? `${getProductLabel(product)}은 ${focus}` : null;
  }).filter(Boolean);

  if (differenceLines.length > 0) {
    return sanitizeCosmeticClaimText(`${differenceLines.join(" / ")} 쪽에서 차이가 보여요.`);
  }

  const cheapestProduct = getCheapestProduct(products);
  return cheapestProduct
    ? `${getProductLabel(cheapestProduct)}은 가격 부담이 낮고, 나머지는 성분 구성과 사용감을 함께 봐야 해요.`
    : "성분 구성은 비슷해 보여요. 가격, 사용감, 주의 성분을 함께 보는 게 좋아요.";
};

const getSkinFitText = (
  products: ProductDetail[],
  skinType?: string,
  sensitivity?: string,
) => {
  const profileLabel = getProfileLabel(skinType, sensitivity);
  const sharedEffects = getSharedValues(products.map((product) => product.evidence_tags));
  const effectText = sharedEffects.length > 0
    ? `${sharedEffects.slice(0, 3).join(", ")} 포인트를 공통으로 볼 수 있어요.`
    : "공통 효능보다 각 상품의 성분 차이를 보는 편이 좋아요.";

  if (!profileLabel) {
    return sanitizeCosmeticClaimText(`${effectText} 피부 타입을 적용하면 선택 기준을 더 좁힐 수 있어요.`);
  }

  return sanitizeCosmeticClaimText(`${profileLabel}에서는 ${effectText} 민감한 편이라면 주의 성분이 적은 쪽을 우선으로 보세요.`);
};

const getCautionText = (products: ProductDetail[]) => {
  const riskSummaries = products
    .filter((product) => product.risk_flags.length > 0)
    .map((product) => `${getProductLabel(product)}: ${joinValues(product.risk_flags, "주의 성분 정보 없음")}`);

  if (riskSummaries.length === 0) {
    return "현재 데이터에서는 뚜렷한 주의 성분이 표시되지 않았어요. 민감한 피부라면 전성분을 한 번 더 확인해주세요.";
  }

  return sanitizeCosmeticClaimText(`${riskSummaries.join(" / ")} 반응 이력이 있다면 전성분을 먼저 확인해주세요.`);
};

const getRoutineTipText = (products: ProductDetail[]) => {
  const effects = products.flatMap((product) => product.evidence_tags).join(" ");

  if (/각질|AHA|BHA|PHA/i.test(effects)) {
    return "각질 케어 계열은 낮은 빈도부터 시작하고, 다음 단계에는 보습 제품을 함께 두는 편이 안정적이에요.";
  }

  if (/유분|모공/.test(effects)) {
    return "유분과 모공 고민이라면 아침에는 가볍게, 저녁에는 보습 장벽을 해치지 않는 조합이 좋아요.";
  }

  if (/보습|장벽|진정/.test(effects)) {
    return "보습과 장벽 케어 목적이라면 세안 후 수분 제품 다음 단계에 두고, 건조한 날에는 크림으로 마무리해보세요.";
  }

  return "기존 루틴에 넣을 때는 한 번에 여러 제품을 바꾸기보다 하나씩 바꿔 피부 반응을 확인하는 게 좋아요.";
};

const getPriceValueText = (
  products: ProductDetail[],
  recommendedProduct: ProductDetail | null,
) => {
  const pricedProducts = products.filter((product) => product.lowest_price !== null);
  if (pricedProducts.length === 0) {
    return "가격 정보가 부족해 가성비 판단은 아직 어려워요.";
  }

  const cheapestProduct = getCheapestProduct(products);
  if (!cheapestProduct || cheapestProduct.lowest_price === null) {
    return "가격 정보는 일부만 확인돼요. 성분과 주의 성분을 우선으로 비교해주세요.";
  }

  if (recommendedProduct?.product_id === cheapestProduct.product_id) {
    return `${getProductLabel(cheapestProduct)}은 비교 상품 중 가격 부담도 낮은 편이에요.`;
  }

  if (recommendedProduct?.lowest_price !== null && recommendedProduct?.lowest_price !== undefined) {
    const difference = recommendedProduct.lowest_price - cheapestProduct.lowest_price;
    if (difference > 0) {
      return `${getProductLabel(recommendedProduct)}은 최저가 상품보다 ${difference.toLocaleString("ko-KR")}원 높지만, 피부 기준과 성분 근거를 함께 볼 필요가 있어요.`;
    }
  }

  return `${getProductLabel(cheapestProduct)}은 가격 부담이 낮아요. 다만 가격만으로 고르기보다 주의 성분과 필요한 케어 포인트를 함께 확인해주세요.`;
};

const getSelectionCriteriaText = (
  products: ProductDetail[],
  recommendedProduct: ProductDetail | null,
  sensitivity?: string,
) => {
  if (!recommendedProduct) {
    return "비교 상품이 준비되면 피부 기준, 주의 성분, 가격 부담 순서로 선택 기준을 정리해드릴게요.";
  }

  const cheapestProduct = getCheapestProduct(products);
  const recommendedLabel = getProductLabel(recommendedProduct);

  if (isSensitiveProfile(sensitivity)) {
    return `${recommendedLabel}처럼 주의 성분 표시가 적은 상품을 먼저 보고, 가격이 중요하면 최저가 상품과 성분 차이를 같이 확인해보세요.`;
  }

  if (cheapestProduct && cheapestProduct.product_id !== recommendedProduct.product_id) {
    return `성분 근거와 피부 기준을 우선하면 ${recommendedLabel}을 먼저 보고, 가격 부담을 줄이고 싶다면 ${getProductLabel(cheapestProduct)}과 비교해보세요.`;
  }

  return `${recommendedLabel}을 먼저 고려해볼 만해요. 특정 성분에 반응한 적이 있다면 주의 성분 카드를 먼저 확인해주세요.`;
};

const getDecisionSummary = (
  products: ProductDetail[],
  source: ProductComparisonSource,
  skinType?: string,
  sensitivity?: string,
  summary?: string,
  recommendationReason?: string,
): ProductComparisonDecisionSummary => {
  const recommendedProduct = getRecommendedProduct(products, sensitivity);
  const externalNote = sanitizeCosmeticClaimText(summary || recommendationReason || "");

  return {
    caution: getCautionText(products),
    differentiator: getDifferentiatorText(products),
    externalNote: externalNote || undefined,
    priceValue: getPriceValueText(products, recommendedProduct),
    recommendedProductName: recommendedProduct ? getProductFullLabel(recommendedProduct) : undefined,
    routineTip: getRoutineTipText(products),
    selectionCriteria: getSelectionCriteriaText(products, recommendedProduct, sensitivity),
    skinFit: getSkinFitText(products, skinType, sensitivity),
    verdict: getVerdictText(products, source, skinType, sensitivity),
  };
};

const hasAnyKeyword = (values: string[], keywords: string[]) =>
  values.some((value) => keywords.some((keyword) => value.includes(keyword)));

const getScenarioProductRoleLabel = (index: number) => {
  if (index === 0) return "보고 있는 상품";
  return `비교 후보 ${index}`;
};

const getProductEvidenceStrength = (product: ProductDetail) => {
  const evidenceScore = product.score_breakdown?.ingredient_evidence_score ?? 0;
  return product.evidence.length + product.sources.length + evidenceScore;
};

const getScenarioTagCandidates = (
  product: ProductDetail,
  products: ProductDetail[],
  context: ProductScenarioTagContext,
): ProductScenarioTag[] => {
  const candidates: ProductScenarioTag[] = [];
  const uniqueIngredients = getProductUniqueValues(product, products, "key_ingredients");
  const uniqueEffects = getProductUniqueValues(product, products, "evidence_tags");
  const relatedKeywords = [...product.evidence_tags, ...product.key_ingredients];
  const isLowestPrice = product.lowest_price !== null && product.lowest_price === context.lowestPrice;
  const hasRiskAdvantage = product.risk_flags.length === context.minRiskCount &&
    context.minRiskCount < context.maxRiskCount;
  const hasEvidenceAdvantage = getProductEvidenceStrength(product) === context.maxEvidenceStrength &&
    context.maxEvidenceStrength > 0;
  const hasTopScore = product.total_score === context.maxScore;

  if (isSensitiveProfile(context.sensitivity) && hasRiskAdvantage) {
    candidates.push({ label: "민감 피부 고려" });
  }

  if (hasRiskAdvantage && product.risk_flags.length === 0) {
    candidates.push({ label: "주의 성분 적음" });
  }

  if (isLowestPrice && hasTopScore) {
    candidates.push({ label: "가성비 비교" });
  }

  if (isLowestPrice) {
    candidates.push({ label: "가격 부담 낮춤" });
  }

  if (uniqueIngredients.length > 0 || uniqueEffects.length > 0) {
    candidates.push({ label: "핵심 성분 차이" });
  }

  if (hasEvidenceAdvantage || hasTopScore) {
    candidates.push({ label: "성분 근거 우선" });
  }

  if (hasAnyKeyword(product.evidence_tags, ["보습", "수분", "수분감"])) {
    candidates.push({ label: "보습 집중" });
  }

  if (hasAnyKeyword(product.evidence_tags, ["진정", "민감"])) {
    candidates.push({ label: "진정 포인트" });
  }

  if (hasAnyKeyword(relatedKeywords, ["장벽", "세라마이드", "판테놀", "베타-글루칸", "베타글루칸"])) {
    candidates.push({ label: "장벽 성분" });
  }

  if (product.risk_flags.length > 0) {
    candidates.push({ label: "전성분 확인", tone: "caution" });
  }

  if (hasTopScore) {
    candidates.push({ label: "종합 점수 우선" });
  }

  candidates.push({ label: "데일리로 무난" });
  candidates.push({ label: "종합 점수 우선" });

  return candidates;
};

const getFallbackScenarioTag = (usedLabels: Set<ProductScenarioTagLabel>): ProductScenarioTag =>
  ([
    { label: "데일리로 무난" },
    { label: "종합 점수 우선" },
    { label: "성분 근거 우선" },
  ] as ProductScenarioTag[]).find((tag) => !usedLabels.has(tag.label)) ?? { label: "데일리로 무난" };

const getScenarioReason = (product: ProductDetail, tag: ProductScenarioTagLabel) => {
  const productName = getProductLabel(product);

  switch (tag) {
    case "성분 근거 우선":
      return `성분 근거를 먼저 보고 싶다면 ${productName}`;
    case "핵심 성분 차이":
      return `다른 성분 구성을 비교하려면 ${productName}`;
    case "가격 부담 낮춤":
      return `가격 부담을 낮추고 싶다면 ${productName}`;
    case "가성비 비교":
      return `가격과 성분 기준을 함께 보면 ${productName}`;
    case "민감 피부 고려":
      return `민감한 편이라면 ${productName}`;
    case "주의 성분 적음":
      return `성분 부담을 줄이고 싶다면 ${productName}`;
    case "보습 집중":
      return `보습 포인트를 우선하면 ${productName}`;
    case "진정 포인트":
      return `진정 포인트를 우선하면 ${productName}`;
    case "장벽 성분":
      return `장벽 성분까지 비교하려면 ${productName}`;
    case "산뜻한 사용감":
      return `가볍게 쓰는 사용감을 원하면 ${productName}`;
    case "유분 부담 적음":
      return `유분 부담을 줄이고 싶다면 ${productName}`;
    case "데일리로 무난":
      return `매일 쓰기 무난한 후보로 ${productName}`;
    case "전성분 확인":
      return `특정 성분에 민감했다면 ${productName} 전성분을 먼저 확인해보세요`;
    case "종합 점수 우선":
      return `종합 기준으로 먼저 보면 ${productName}`;
    default:
      return `비교 기준을 함께 보고 싶다면 ${productName}`;
  }
};

const getProductScenarioGuideItems = (
  products: ProductDetail[],
  sensitivity?: string,
): ProductComparisonScenarioGuideItem[] => {
  const scenarioProducts = products.slice(0, MAX_SIMILAR_PRODUCTS + 1);
  const riskCounts = scenarioProducts.map((product) => product.risk_flags.length);
  const evidenceStrengths = scenarioProducts.map(getProductEvidenceStrength);
  const context: ProductScenarioTagContext = {
    lowestPrice: getLowestComparablePrice(scenarioProducts),
    maxEvidenceStrength: Math.max(0, ...evidenceStrengths),
    maxRiskCount: Math.max(0, ...riskCounts),
    maxScore: Math.max(0, ...scenarioProducts.map((product) => product.total_score)),
    minRiskCount: Math.min(...riskCounts),
    sensitivity,
  };

  const usedLabels = new Set<ProductScenarioTagLabel>();

  return scenarioProducts.map((product, index) => {
    const tagCandidates = getScenarioTagCandidates(product, scenarioProducts, context);
    const tag = tagCandidates.find((candidate) => !usedLabels.has(candidate.label)) ??
      getFallbackScenarioTag(usedLabels);
    usedLabels.add(tag.label);

    return {
      label: tag.label,
      productName: getProductLabel(product),
      reason: getScenarioReason(product, tag.label),
      roleLabel: getScenarioProductRoleLabel(index),
      tone: tag.tone,
    };
  });
};

const getComparisonTags = (product: ProductDetail) => (
  product.evidence_tags.length > 0 ? product.evidence_tags : product.key_ingredients
).slice(0, 4);

const renderComparableValues = (
  values: string[],
  highlightedValues: Set<string>,
  fallback = "확인 중이에요",
) => {
  const displayValues = uniqueValues(values).slice(0, 4);
  if (displayValues.length === 0) return fallback;

  return (
    <span className="product-comparison-table__value-list">
      {displayValues.map((value, index) => {
        const content = highlightedValues.has(value) ? (
          <strong>{value}</strong>
        ) : (
          <span>{value}</span>
        );

        return (
          <span key={value}>
            {content}
            {index < displayValues.length - 1 ? ", " : ""}
          </span>
        );
      })}
    </span>
  );
};

const renderPriceComparisonValue = (product: ProductDetail, lowestPrice: number | null) => {
  const isLowestPrice = product.lowest_price !== null && product.lowest_price === lowestPrice;

  return (
    <span className="product-comparison-table__price-value">
      <strong className={isLowestPrice ? "is-lowest" : undefined}>
        {formatPrice(product.lowest_price)}
      </strong>
      {isLowestPrice ? (
        <span className="product-comparison-table__best-price">최저</span>
      ) : null}
    </span>
  );
};

const getCardLabel = (index: number) => {
  if (index === 0) return "보고 있는 상품";
  return `비교 후보 ${index}`;
};

function ProductComparisonCard({
  label,
  product,
  variant = "candidate",
}: {
  label: string;
  product: ProductDetail;
  variant?: ProductComparisonCardVariant;
}) {
  const tags = getComparisonTags(product);
  const [hasImageError, setHasImageError] = useState(false);
  const shouldShowImage = Boolean(product.thumbnail_url) && !hasImageError;

  return (
    <article className={`product-comparison-card ${variant}`}>
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__image">
        {shouldShowImage ? (
          <img
            src={product.thumbnail_url ?? ""}
            alt={product.name}
            onError={() => setHasImageError(true)}
          />
        ) : (
          <span>이미지 준비 중이에요</span>
        )}
      </div>
      <div className="product-comparison-card__body">
        <div className="product-comparison-card__brand">{product.brand}</div>
        <h3>{product.name}</h3>
        <div className="product-comparison-card__price">{formatPrice(product.lowest_price)}</div>
        <div className="product-comparison-card__tags">
          {tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </div>
    </article>
  );
}

function ProductComparisonLoadingCard({ label }: { label: string }) {
  return (
    <article className="product-comparison-card loading" aria-busy="true">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__image">
        <span>상품을 불러오고 있어요</span>
      </div>
      <div className="product-comparison-card__body">
        <div className="product-comparison-skeleton short" />
        <div className="product-comparison-skeleton long" />
        <div className="product-comparison-skeleton price" />
      </div>
    </article>
  );
}

function ProductComparisonEmptyCard({
  label,
  message,
}: {
  label: string;
  message: string;
}) {
  return (
    <article className="product-comparison-card empty">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__empty">{message}</div>
    </article>
  );
}

function ProductComparisonScenarioGuide({
  externalNote,
  items,
}: {
  externalNote?: string;
  items: ProductComparisonScenarioGuideItem[];
}) {
  if (items.length === 0) return null;

  return (
    <div className="product-comparison-scenario-guide">
      <div className="product-comparison-scenario-guide__head">
        <strong>이럴 땐 이 상품</strong>
        <span>{externalNote || "피부 반응은 개인차가 있어요"}</span>
      </div>
      <div className="product-comparison-scenario-guide__grid">
        {items.map((item) => (
          <article
            className={`product-comparison-scenario-guide__item${item.tone === "caution" ? " caution" : ""}`}
            key={`${item.label}-${item.productName}`}
          >
            <span>{item.label}</span>
            <div className="product-comparison-scenario-guide__copy">
              <em>{item.roleLabel}</em>
              <p>{item.reason}</p>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ProductComparisonPanel({
  differences,
  errorMessage,
  expectedProductCount,
  initiallyPriceOnly = false,
  isLoading,
  onClose,
  products,
  recommendationReason,
  sensitivity,
  skinType,
  source,
  summary,
}: ProductComparisonPanelProps) {
  const [isDifferentOnly, setIsDifferentOnly] = useState(false);
  const expectedCandidateCount = Math.min(Math.max(expectedProductCount - 1, 1), MAX_SIMILAR_PRODUCTS);
  const visibleProducts = products.slice(0, MAX_SIMILAR_PRODUCTS + 1);
  const currentProduct = visibleProducts[0] ?? null;
  const candidateProducts = visibleProducts.slice(1, MAX_SIMILAR_PRODUCTS + 1);
  const comparisonCardProducts = visibleProducts.slice(0, MAX_SIMILAR_PRODUCTS + 1);
  const missingCandidateCount = Math.max(expectedCandidateCount - candidateProducts.length, 0);
  const decisionSummary = getDecisionSummary(
    visibleProducts,
    source,
    skinType,
    sensitivity,
    summary,
    recommendationReason,
  );
  const scenarioGuideItems = getProductScenarioGuideItems(visibleProducts, sensitivity);
  const currentIngredientSet = new Set(currentProduct?.key_ingredients ?? []);
  const lowestPrice = getLowestComparablePrice(visibleProducts);
  const comparisonRows: ProductComparisonTableRow[] = [{
    label: "고민 적합도",
    comparisonValues: visibleProducts.map((product) => joinValues(product.evidence_tags)),
    values: visibleProducts.map((product) => (
      renderComparableValues(product.evidence_tags, new Set<string>())
    )),
  },
  {
    label: "핵심 성분",
    comparisonValues: visibleProducts.map((product) => joinValues(product.key_ingredients)),
    values: visibleProducts.map((product, index) => (
      renderComparableValues(
        product.key_ingredients,
        index === 0 ? new Set<string>() : currentIngredientSet,
      )
    )),
  },
  {
    label: initiallyPriceOnly ? "가격" : "최저가",
    comparisonValues: visibleProducts.map((product) => formatPrice(product.lowest_price)),
    values: visibleProducts.map((product) => renderPriceComparisonValue(product, lowestPrice)),
  },
  {
    label: "별점",
    comparisonValues: visibleProducts.map(getReviewComparisonValue),
    values: visibleProducts.map((product) => getReviewComparisonValue(product)),
  },
  {
    label: "주의 성분",
    comparisonValues: visibleProducts.map(getCautionComparisonValue),
    values: visibleProducts.map((product) => (
      initiallyPriceOnly
        ? renderInlineCautionComparisonValue(product)
        : getCautionComparisonValue(product)
    )),
  },
  {
    label: "구매 상태",
    comparisonValues: visibleProducts.map(getPurchaseComparisonValue),
    values: visibleProducts.map((product) => getPurchaseComparisonValue(product)),
  }];
  const inlineComparisonRows = ["고민 적합도", "핵심 성분", "주의 성분", "별점", "구매 상태"]
    .map((label) => comparisonRows.find((row) => row.label === label))
    .filter((row): row is ProductComparisonTableRow => Boolean(row));
  const visibleComparisonRows = initiallyPriceOnly
    ? inlineComparisonRows
    : isDifferentOnly
      ? comparisonRows.filter((row) => new Set(row.comparisonValues).size > 1)
      : comparisonRows;
  const comparisonCards = (
    <>
      {comparisonCardProducts.map((product, index) => (
        <ProductComparisonCard
          key={product.product_id}
          label={getCardLabel(index)}
          product={product}
          variant={index === 0 ? "current" : "candidate"}
        />
      ))}
      {Array.from({ length: isLoading ? missingCandidateCount : 0 }).map((_, index) => {
        const labelIndex = candidateProducts.length + index + 1;
        return (
          <ProductComparisonLoadingCard
            key={`loading-${labelIndex}`}
            label={getCardLabel(labelIndex)}
          />
        );
      })}
      {!isLoading && missingCandidateCount > 0 ? (
        <ProductComparisonEmptyCard
          label={getCardLabel(candidateProducts.length + 1)}
          message={errorMessage || "비교 상품 정보를 불러오지 못했습니다."}
        />
      ) : null}
    </>
  );

  return (
    <section className={`product-comparison-panel${initiallyPriceOnly ? " product-comparison-panel--inline" : ""}`} id="productComparisonPanel" aria-labelledby="productComparisonTitle">
      <div className="product-comparison-panel__head" style={initiallyPriceOnly ? { position: "static" } : undefined}>
        <div>
          <p>{visibleProducts.length}개 상품을 실제 가격, 성분, 리뷰 정보로 비교합니다.</p>
          <h2 id="productComparisonTitle">비슷한 후보를 골라봤어요</h2>
        </div>
        {!initiallyPriceOnly ? (
          <div className="product-comparison-panel__actions">
            <button
              aria-pressed={isDifferentOnly}
              className="product-comparison-diff-toggle"
              onClick={() => setIsDifferentOnly((currentValue) => !currentValue)}
              type="button"
            >
              다른 점만 보기
            </button>
            <button type="button" onClick={onClose} aria-label="상품 비교 닫기">×</button>
          </div>
        ) : null}
      </div>

      {initiallyPriceOnly || isLoading || missingCandidateCount > 0 ? (
        initiallyPriceOnly ? (
          <div className={`product-comparison-grid product-comparison-grid--aligned count-${Math.max(comparisonCardProducts.length, expectedCandidateCount + 1, 1)}`}>
            <div aria-hidden="true" className="product-comparison-grid__gutter" />
            <div className="product-comparison-grid__cards">{comparisonCards}</div>
          </div>
        ) : (
          <div className={`product-comparison-grid count-${Math.max(comparisonCardProducts.length, expectedCandidateCount + 1, 1)}`}>
            {comparisonCards}
          </div>
        )
      ) : null}

      {visibleProducts.length > 1 ? (
        <div className="product-comparison-detail">
          {!initiallyPriceOnly && differences.length > 0 ? (
            <div className="product-comparison-differences">
              {differences.map((difference, index) => (
                <article className="product-comparison-difference" key={`${difference.label}-${index}`}>
                  <strong>{difference.label}</strong>
                  {difference.description ? <p>{difference.description}</p> : null}
                </article>
              ))}
            </div>
          ) : null}
          {initiallyPriceOnly ? (
            <div className="product-comparison-row-list" aria-label="상품별 상세 비교 정보">
              {visibleComparisonRows.map((row) => {
                const hasCautionIngredients = row.label === "주의 성분"
                  && visibleProducts.some((product) => getCautionIngredientNames(product).length > 0);

                return (
                  <div className={`product-comparison-row-list__row${hasCautionIngredients ? " is-caution" : ""}`} key={row.label}>
                    <strong>{row.label}</strong>
                    <div className="product-comparison-row-list__values">
                      {row.values.map((value, productIndex) => (
                        <span key={`${row.label}-${visibleProducts[productIndex]?.product_id ?? productIndex}`}>{value}</span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="product-comparison-table-wrap">
              <table className="product-comparison-table">
                <colgroup>
                  <col className="product-comparison-table__label-col" style={{ width: "120px" }} />
                  {visibleProducts.map((product) => (
                    <col className="product-comparison-table__product-col" key={product.product_id} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">비교 포인트</th>
                    {visibleProducts.map((product, index) => (
                      <th scope="col" key={product.product_id}>
                        <span className="product-comparison-table__column-label">
                          {getCardLabel(index)}
                        </span>
                        {product.thumbnail_url ? <img className="product-comparison-table__thumbnail" src={product.thumbnail_url} alt="" /> : null}
                        <span className="product-comparison-table__product-name" title={product.name}>
                          {product.name}
                        </span>
                        <span className="product-comparison-table__product-meta">{product.brand} · {formatPrice(product.lowest_price)}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleComparisonRows.map((row) => (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      {row.values.map((value, index) => (
                        <td key={`${row.label}-${visibleProducts[index]?.product_id ?? index}`}>{value}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {!initiallyPriceOnly ? (
        <div className="product-comparison-summary">
          <ProductComparisonScenarioGuide
            externalNote={decisionSummary.externalNote}
            items={scenarioGuideItems}
          />
          <p className="product-comparison-summary__notice">
            AI 요약은 상품 성분과 가격 데이터를 기준으로 한 선택 보조 정보입니다. 피부 반응은 개인차가 있을 수 있어요.
          </p>
        </div>
      ) : null}
    </section>
  );
}

export default ProductComparisonPanel;
