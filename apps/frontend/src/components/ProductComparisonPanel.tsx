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

type ProductComparisonTradeoffItem = {
  label: "성분 기준" | "주의 성분";
  text: string;
  tone?: "caution";
};

type ProductComparisonScenarioGuideItem = {
  label: string;
  productName: string;
  reason: string;
};

type ProductComparisonTableRow = {
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

const getProductScenarioGuideItems = (products: ProductDetail[]): ProductComparisonScenarioGuideItem[] => {
  const guides: ProductComparisonScenarioGuideItem[] = [];
  const usedProductIds = new Set<string>();
  const cheapestProduct = getCheapestProduct(products);
  const lowRiskProducts = products.filter((product) => product.risk_flags.length === 0);
  const calmingProduct =
    lowRiskProducts.find((product) => hasAnyKeyword(product.evidence_tags, ["진정", "보습"])) ||
    products.find((product) => hasAnyKeyword(product.evidence_tags, ["진정", "보습"])) ||
    cheapestProduct ||
    products[0];

  if (calmingProduct) {
    guides.push({
      label: cheapestProduct?.product_id === calmingProduct.product_id ? "가성비·진정" : "진정 케어",
      productName: getProductLabel(calmingProduct),
      reason: cheapestProduct?.product_id === calmingProduct.product_id
        ? "부담 없이 진정 위주라면"
        : "진정 포인트를 우선하면",
    });
    usedProductIds.add(calmingProduct.product_id);
  }

  const barrierProduct =
    products.find((product) => (
      !usedProductIds.has(product.product_id) &&
      (
        hasAnyKeyword(product.evidence_tags, ["장벽", "보습"]) ||
        hasAnyKeyword(product.key_ingredients, ["세라마이드", "판테놀", "베타-글루칸"])
      )
    )) ||
    products.find((product) => !usedProductIds.has(product.product_id));

  if (barrierProduct) {
    guides.push({
      label: hasAnyKeyword([...barrierProduct.evidence_tags, ...barrierProduct.key_ingredients], ["장벽", "세라마이드", "판테놀"])
        ? "장벽 강화"
        : "성분 비교",
      productName: getProductLabel(barrierProduct),
      reason: hasAnyKeyword(barrierProduct.key_ingredients, ["세라마이드", "판테놀", "베타-글루칸"])
        ? "장벽 성분까지 챙기려면"
        : "성분 차이를 보고 고르려면",
    });
    usedProductIds.add(barrierProduct.product_id);
  }

  if (guides.length < 2) {
    const fallbackProduct = products.find((product) => !usedProductIds.has(product.product_id));
    if (fallbackProduct) {
      guides.push({
        label: fallbackProduct.evidence_tags[0] || "선택 기준",
        productName: getProductLabel(fallbackProduct),
        reason: "다른 선택지도 함께 보려면",
      });
    }
  }

  return guides.slice(0, 2);
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

const getProductTradeoffSummary = (product: ProductDetail): ProductComparisonTradeoffItem[] => {
  const ingredientPoints = uniqueValues([...product.evidence_tags, ...product.key_ingredients]).slice(0, 2);
  const riskFlags = product.risk_flags.slice(0, 2);

  return [
    {
      label: "성분 기준",
      text: ingredientPoints.length > 0
        ? `${ingredientPoints.join("·")} 포인트가 보여요.`
        : "상세 비교표에서 성분을 확인해보세요.",
    },
    {
      label: "주의 성분",
      text: riskFlags.length > 0
        ? `${riskFlags.join("·")} 확인이 필요해요.`
        : "한 번 더 볼 성분이 없어요.",
      tone: riskFlags.length > 0 ? "caution" : undefined,
    },
  ];
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
  const tradeoffs = getProductTradeoffSummary(product);
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
        <div className="product-comparison-card__tradeoffs">
          {tradeoffs.map((item) => (
            <p
              className={item.tone === "caution" ? "caution" : undefined}
              key={item.label}
            >
              <strong>{item.label}</strong>
              <span>{item.text}</span>
            </p>
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
          <article className="product-comparison-scenario-guide__item" key={`${item.label}-${item.productName}`}>
            <span>{item.label}</span>
            <p>
              {item.reason} <strong>{item.productName}</strong>
            </p>
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
  isLoading,
  onClose,
  products,
  recommendationReason,
  sensitivity,
  skinType,
  source,
  summary,
}: ProductComparisonPanelProps) {
  const [isDetailOpen, setIsDetailOpen] = useState(false);
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
  const scenarioGuideItems = getProductScenarioGuideItems(visibleProducts);
  const currentConcernSet = new Set(currentProduct?.evidence_tags ?? []);
  const lowestPrice = getLowestComparablePrice(visibleProducts);
  const comparisonRows: ProductComparisonTableRow[] = [{
    label: "고민 적합도",
    values: visibleProducts.map((product, index) => (
      renderComparableValues(product.evidence_tags, index === 0 ? new Set<string>() : currentConcernSet)
    )),
  },
  {
    label: "핵심 성분",
    values: visibleProducts.map((product) => (
      renderComparableValues(
        product.key_ingredients,
        new Set(product.key_ingredients.slice(0, 2)),
      )
    )),
  },
  {
    label: "가격 부담",
    values: visibleProducts.map((product) => renderPriceComparisonValue(product, lowestPrice)),
  },
  {
    label: "별점(리뷰)",
    values: visibleProducts.map(() => "리뷰 데이터 준비 중"),
  },
  {
    label: "타입별 선호도",
    values: visibleProducts.map(() => "선호도 데이터 준비 중"),
  }];

  return (
    <section className="product-comparison-panel" id="productComparisonPanel" aria-labelledby="productComparisonTitle">
      <div className="product-comparison-panel__head">
        <div>
          <p>가격, 성분, 피부 고민 기준으로 같이 비교해보세요.</p>
          <h2 id="productComparisonTitle">비슷한 후보를 골라봤어요</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="AI 상품 요약 닫기">×</button>
      </div>

      <div className={`product-comparison-grid count-${Math.max(comparisonCardProducts.length, expectedCandidateCount + 1, 1)}`}>
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
      </div>

      {visibleProducts.length > 1 ? (
        <div className="product-comparison-detail">
          <button
            className="product-comparison-detail-toggle"
            type="button"
            aria-expanded={isDetailOpen}
            onClick={() => setIsDetailOpen((currentValue) => !currentValue)}
          >
            {isDetailOpen ? "비교 내용 접기" : "더 자세히 비교하기"}
            <span aria-hidden="true">{isDetailOpen ? "▲" : "▼"}</span>
          </button>
          {isDetailOpen ? (
            <div className="product-comparison-detail-content">
              {differences.length > 0 ? (
                <div className="product-comparison-differences">
                  {differences.map((difference, index) => (
                    <article className="product-comparison-difference" key={`${difference.label}-${index}`}>
                      <strong>{difference.label}</strong>
                      {difference.description ? <p>{difference.description}</p> : null}
                      {(difference.base || difference.compare) ? (
                        <div className="product-comparison-difference__values">
                          {difference.base ? <span>{difference.base}</span> : <span>현재 상품 정보 없음</span>}
                          {difference.compare ? <span>{difference.compare}</span> : <span>비교 상품 정보 없음</span>}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : null}
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
                          <span className="product-comparison-table__product-name" title={product.name}>
                            {product.name}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonRows.map((row) => (
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
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="product-comparison-summary">
        <ProductComparisonScenarioGuide
          externalNote={decisionSummary.externalNote}
          items={scenarioGuideItems}
        />
        <p className="product-comparison-summary__notice">
          AI 요약은 상품 성분과 가격 데이터를 기준으로 한 선택 보조 정보입니다. 피부 반응은 개인차가 있을 수 있어요.
        </p>
      </div>
    </section>
  );
}

export default ProductComparisonPanel;
