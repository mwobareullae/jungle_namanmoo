import { useMemo, useState } from "react";
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
  routineTip: string;
  selectionCriteria: string;
  skinFit: string;
  verdict: string;
};

const MAX_COMPARISON_PRODUCTS = 3;

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const joinValues = (values: string[], fallback = "정보 없음") =>
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
    .replace(/치료/g, "케어")
    .replace(/완치/g, "해결")
    .replace(/보장/g, "단정")
    .replace(/반드시\s*/g, "")
    .replace(/무조건\s*/g, "")
    .replace(/효과가 뛰어납니다/g, "근거가 비교적 뚜렷해요")
    .replace(/효과적입니다/g, "도움이 될 수 있는 근거로 봤어요")
    .replace(/효과적이에요/g, "도움이 될 수 있는 근거로 봤어요")
    .replace(/효과가 있어요/g, "도움이 될 수 있는 근거가 있어요")
    .replace(/효과/g, "근거")
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
      ? "비슷한 상품 정보를 불러온 뒤 내 피부 기준으로 다시 판단해드릴게요."
      : "비교 상품 정보를 불러온 뒤 선택 기준을 정리해드릴게요.";
  }

  const profileLabel = getProfileLabel(skinType, sensitivity);
  const primaryEffect = recommendedProduct.evidence_tags[0];
  const reason = recommendedProduct.risk_flags.length === 0
    ? "주의 성분 표시가 적고"
    : primaryEffect
      ? `${primaryEffect} 케어 근거가 보여서`
      : "성분 근거와 가격을 함께 봤을 때";
  const prefix = profileLabel ? `${profileLabel} 기준이라면 ` : "";
  return sanitizeCosmeticClaimText(`${prefix}${getProductFullLabel(recommendedProduct)}을 먼저 고려해보는 게 좋아요. ${reason} 선택 부담이 낮아요.`);
};

const getDifferentiatorText = (products: ProductDetail[]) => {
  if (products.length < 2) {
    return "비교 상품을 불러오면 성분과 가격 차이를 함께 정리해드릴게요.";
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
    return sanitizeCosmeticClaimText(`${differenceLines.join(" / ")} 쪽 차이가 핵심이에요.`);
  }

  const cheapestProduct = getCheapestProduct(products);
  return cheapestProduct
    ? `${getProductLabel(cheapestProduct)}은 가격 부담이 낮고, 나머지는 성분 구성과 사용감을 같이 봐야 해요.`
    : "성분 구성이 비슷해 보여서 피부 고민, 사용감, 주의 성분을 함께 보는 게 좋아요.";
};

const getSkinFitText = (
  products: ProductDetail[],
  skinType?: string,
  sensitivity?: string,
) => {
  const profileLabel = getProfileLabel(skinType, sensitivity);
  const sharedEffects = getSharedValues(products.map((product) => product.evidence_tags));
  const effectText = sharedEffects.length > 0
    ? `${sharedEffects.slice(0, 3).join(", ")} 케어 포인트를 공통으로 볼 수 있어요`
    : "공통 효능보다 각 상품의 핵심 성분 차이를 보는 편이 좋아요";

  if (!profileLabel) {
    return sanitizeCosmeticClaimText(`${effectText}. 피부 타입을 적용하면 선택 기준을 더 좁힐 수 있어요.`);
  }

  return sanitizeCosmeticClaimText(`${profileLabel} 기준에서는 ${effectText}. 특히 자극 이력이 있다면 주의 성분이 적은 쪽을 우선으로 보세요.`);
};

const getCautionText = (products: ProductDetail[]) => {
  const riskSummaries = products
    .filter((product) => product.risk_flags.length > 0)
    .map((product) => `${getProductLabel(product)}: ${joinValues(product.risk_flags, "주의 성분 확인 필요")}`);

  if (riskSummaries.length === 0) {
    return "현재 데이터에서는 두드러진 주의 성분이 표시되지 않았어요. 그래도 민감한 피부라면 새 제품은 소량으로 먼저 확인하는 게 좋아요.";
  }

  return sanitizeCosmeticClaimText(`${riskSummaries.join(" / ")}은 반응 이력이 있다면 전성분을 한 번 더 확인하세요.`);
};

const getRoutineTipText = (products: ProductDetail[]) => {
  const effects = products.flatMap((product) => product.evidence_tags).join(" ");

  if (/각질|AHA|BHA|PHA/i.test(effects)) {
    return "각질 케어 계열은 저녁 루틴에서 낮은 빈도로 시작하고, 다음 단계에는 보습 제품을 함께 두는 편이 안정적이에요.";
  }

  if (/피지|모공/.test(effects)) {
    return "피지·모공 고민이라면 아침에는 가볍게, 저녁에는 보습 장벽을 해치지 않는 조합으로 쓰는 게 좋아요.";
  }

  if (/보습|장벽|진정/.test(effects)) {
    return "보습·장벽 케어 목적이라면 세안 후 수분 제품 다음 단계에 두고, 건조한 날에는 크림으로 마무리하세요.";
  }

  return "기존 루틴에 넣을 때는 한 번에 여러 제품을 바꾸기보다 하나씩 바꿔 피부 반응을 확인하는 게 좋아요.";
};

const getPriceValueText = (
  products: ProductDetail[],
  recommendedProduct: ProductDetail | null,
) => {
  const pricedProducts = products.filter((product) => product.lowest_price !== null);
  if (pricedProducts.length === 0) {
    return "가격 정보가 부족해 가성비 판단은 아직 어려워요. 구조화된 용량 정보가 없어 ml당 가격도 계산하지 못해요.";
  }

  const cheapestProduct = getCheapestProduct(products);
  if (!cheapestProduct) {
    return "가격 정보는 일부만 확인되어 성분과 주의 성분을 우선으로 보는 게 좋아요.";
  }
  const cheapestPrice = cheapestProduct.lowest_price;
  if (cheapestPrice === null) {
    return "가격 정보는 일부만 확인되어 성분과 주의 성분을 우선으로 보는 게 좋아요.";
  }

  if (recommendedProduct?.product_id === cheapestProduct.product_id) {
    return `${getProductLabel(cheapestProduct)}은 비교 상품 중 가격 부담도 가장 낮아요. 구조화된 용량 정보가 없어 ml당 가격은 계산하지 못해요.`;
  }

  if (recommendedProduct?.lowest_price !== null && recommendedProduct?.lowest_price !== undefined) {
    const difference = recommendedProduct.lowest_price - cheapestPrice;
    if (difference > 0) {
      return `${getProductLabel(recommendedProduct)}은 최저가 상품보다 ${difference.toLocaleString("ko-KR")}원 높지만, 피부 기준과 성분 근거를 함께 볼 필요가 있어요.`;
    }
  }

  return `${getProductLabel(cheapestProduct)}은 가격 부담이 낮아요. 다만 가격만으로 고르기보다 주의 성분과 필요한 케어 포인트를 같이 확인하세요.`;
};

const getSelectionCriteriaText = (
  products: ProductDetail[],
  recommendedProduct: ProductDetail | null,
  sensitivity?: string,
) => {
  if (!recommendedProduct) {
    return "비교 상품을 불러온 뒤 피부 기준, 주의 성분, 가격 부담 순서로 선택 기준을 정리해드릴게요.";
  }

  const cheapestProduct = getCheapestProduct(products);
  const recommendedLabel = getProductLabel(recommendedProduct);

  if (isSensitiveProfile(sensitivity)) {
    return sanitizeCosmeticClaimText(`피부가 예민하다면 주의 성분 표시가 적은 ${recommendedLabel}을 먼저 보세요. 가격이 더 중요하면 가격 판단 카드의 최저가 상품과 성분 차이를 같이 확인하면 좋아요.`);
  }

  if (cheapestProduct && cheapestProduct.product_id !== recommendedProduct.product_id) {
    return sanitizeCosmeticClaimText(`성분 근거와 피부 기준을 우선하면 ${recommendedLabel}을 먼저 고려해보고, 가격 부담을 줄이는 게 우선이면 ${getProductLabel(cheapestProduct)}과 비교하세요.`);
  }

  return sanitizeCosmeticClaimText(`빠르게 하나만 고르고 싶다면 ${recommendedLabel}을 먼저 고려해보는 게 좋아요. 단, 특정 성분에 반응한 적이 있다면 주의할 점 카드를 먼저 확인하는 게 좋아요.`);
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
    routineTip: getRoutineTipText(products),
    selectionCriteria: getSelectionCriteriaText(products, recommendedProduct, sensitivity),
    skinFit: getSkinFitText(products, skinType, sensitivity),
    verdict: getVerdictText(products, source, skinType, sensitivity),
  };
};

const getComparisonTags = (product: ProductDetail) => (
  product.evidence_tags.length > 0 ? product.evidence_tags : product.key_ingredients
).slice(0, 4);

const getCardLabel = (index: number, source: ProductComparisonSource) => {
  if (index === 0) return "현재 상품";
  if (source === "similar") return `비슷한 상품 ${index}`;
  return index === 1 ? "비교 상품" : `비교 상품 ${index}`;
};

function ProductComparisonCard({
  label,
  product,
}: {
  label: string;
  product: ProductDetail;
}) {
  const tags = getComparisonTags(product);

  return (
    <article className="product-comparison-card">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__image">
        {product.thumbnail_url ? (
          <img src={product.thumbnail_url} alt={product.name} />
        ) : (
          <span>이미지 준비중</span>
        )}
      </div>
      <div className="product-comparison-card__body">
        <div className="product-comparison-card__brand">{product.brand}</div>
        <h3>{product.name}</h3>
        <div className="product-comparison-card__price">{formatPrice(product.lowest_price)}</div>
        {tags.length > 0 ? (
          <div className="product-comparison-card__tags">
            {tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function ProductComparisonLoadingCard({ label }: { label: string }) {
  return (
    <article className="product-comparison-card loading" aria-busy="true">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__image">
        <span>불러오는 중</span>
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
  const expectedCardCount = Math.min(Math.max(expectedProductCount, 2), MAX_COMPARISON_PRODUCTS);
  const visibleProducts = products.slice(0, MAX_COMPARISON_PRODUCTS);
  const missingCardCount = Math.max(expectedCardCount - visibleProducts.length, 0);
  const decisionSummary = useMemo(
    () => getDecisionSummary(visibleProducts, source, skinType, sensitivity, summary, recommendationReason),
    [recommendationReason, sensitivity, skinType, source, summary, visibleProducts],
  );
  const summaryItems = [
    { body: decisionSummary.differentiator, label: "차이점" },
    { body: decisionSummary.skinFit, label: "내 피부 기준" },
    { body: decisionSummary.caution, label: "주의할 점", tone: "caution" },
    { body: decisionSummary.routineTip, label: "루틴 적합성" },
    { body: decisionSummary.priceValue, label: "가격 판단" },
    { body: decisionSummary.selectionCriteria, label: "선택 기준" },
  ];
  const comparisonRows = useMemo(() => [
    {
      label: "가격",
      values: visibleProducts.map((product) => formatPrice(product.lowest_price)),
    },
    {
      label: "주요 효능",
      values: visibleProducts.map((product) => joinValues(product.evidence_tags)),
    },
    {
      label: "핵심 성분",
      values: visibleProducts.map((product) => joinValues(product.key_ingredients)),
    },
    {
      label: "주의 성분",
      values: visibleProducts.map((product) => joinValues(product.risk_flags, "주의 성분 정보 없음")),
    },
  ], [visibleProducts]);

  return (
    <section className="product-comparison-panel" id="productComparisonPanel" aria-labelledby="productComparisonTitle">
      <div className="product-comparison-panel__head">
        <div>
          <p>{source === "similar" ? "AI 유사 상품 비교" : "AI 비교 결과"}</p>
          <h2 id="productComparisonTitle">선택한 제품 비교하기</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="상품 비교 닫기">×</button>
      </div>

      <div className={`product-comparison-grid count-${expectedCardCount}`}>
        {visibleProducts.map((product, index) => (
          <ProductComparisonCard
            key={product.product_id}
            label={getCardLabel(index, source)}
            product={product}
          />
        ))}
        {Array.from({ length: isLoading ? missingCardCount : 0 }).map((_, index) => {
          const labelIndex = visibleProducts.length + index;
          return (
            <ProductComparisonLoadingCard
              key={`loading-${labelIndex}`}
              label={getCardLabel(labelIndex, source)}
            />
          );
        })}
        {!isLoading && missingCardCount > 0 ? (
          <ProductComparisonEmptyCard
            label={getCardLabel(visibleProducts.length, source)}
            message={errorMessage || "비교할 상품 정보를 불러오지 못했습니다."}
          />
        ) : null}
      </div>

      <div className="product-comparison-summary">
        <div className="product-comparison-summary__title">
          <span aria-hidden="true">◆</span>
          <strong>AI 상품 요약</strong>
        </div>
        <div className="product-comparison-summary__verdict">
          <span>추천 판단</span>
          <strong>{decisionSummary.verdict}</strong>
        </div>
        <div className="product-comparison-summary__grid">
          {summaryItems.map((item) => (
            <article
              className={`product-comparison-summary__item${item.tone === "caution" ? " caution" : ""}`}
              key={item.label}
            >
              <strong>{item.label}</strong>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
        {decisionSummary.externalNote ? (
          <p className="product-comparison-summary__note">{decisionSummary.externalNote}</p>
        ) : null}
        <p className="product-comparison-summary__notice">
          AI 요약은 상품 성분과 가격 데이터 기준의 선택 보조 정보예요. 피부 반응은 개인차가 있어요.
        </p>
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
        {visibleProducts.length > 1 ? (
          <>
            <button
              className="product-comparison-detail-toggle"
              type="button"
              aria-expanded={isDetailOpen}
              onClick={() => setIsDetailOpen((currentValue) => !currentValue)}
            >
              {isDetailOpen ? "상세 비교표 접기" : "상세 비교표 보기"}
              <span aria-hidden="true">{isDetailOpen ? "▲" : "▼"}</span>
            </button>
            {isDetailOpen ? (
              <div className="product-comparison-table-wrap">
                <table className="product-comparison-table">
                  <colgroup>
                    <col className="product-comparison-table__label-col" />
                    {visibleProducts.map((product) => (
                      <col className="product-comparison-table__product-col" key={product.product_id} />
                    ))}
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">항목</th>
                      {visibleProducts.map((product, index) => (
                        <th scope="col" key={product.product_id}>{getCardLabel(index, source)}</th>
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
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

export default ProductComparisonPanel;
