import { Link } from "react-router-dom";
import { useState } from "react";
import type { ProductDetail } from "../types/recommendation";
import {
  getSimilarityReasonLabels,
  type ProductComparisonProfile
} from "../lib/productComparisonPresentation";

export type ProductComparisonDifference = {
  base?: string | null;
  compare?: string | null;
  description?: string | null;
  label: string;
};

type ProductComparisonSource = "comparison" | "similar";

type ProductComparisonPanelProps = {
  candidateMatchReasons?: Readonly<Record<string, readonly string[]>>;
  comparisonProfile?: ProductComparisonProfile;
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

const MAX_SIMILAR_PRODUCTS = 2;

const formatPrice = (price: number | null) =>
  price === null ? "가격 확인 중이에요" : `${price.toLocaleString("ko-KR")}원`;

const uniqueValues = (values: readonly string[]) =>
  Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));

const getLowestPriceProductIds = (products: readonly ProductDetail[]) => {
  const productsWithPrice = products.filter((product) => product.lowest_price !== null);
  if (productsWithPrice.length === 0) return new Set<string>();

  const lowestPrice = Math.min(
    ...productsWithPrice.map((product) => product.lowest_price ?? Infinity)
  );
  return new Set(
    productsWithPrice
      .filter((product) => product.lowest_price === lowestPrice)
      .map((product) => product.product_id)
  );
};

const getMostReviewedProductIds = (products: readonly ProductDetail[]) => {
  const productsWithReviews = products.filter(
    (product) => (product.review_summary?.review_count ?? 0) > 0
  );
  if (productsWithReviews.length === 0) return new Set<string>();

  const mostReviewedCount = Math.max(
    ...productsWithReviews.map((product) => product.review_summary?.review_count ?? 0)
  );
  return new Set(
    productsWithReviews
      .filter((product) => (product.review_summary?.review_count ?? 0) === mostReviewedCount)
      .map((product) => product.product_id)
  );
};

export const getComparisonHighlightProductIds = (products: readonly ProductDetail[]) => {
  const candidateProducts = products.slice(1, MAX_SIMILAR_PRODUCTS + 1);
  if (candidateProducts.length !== MAX_SIMILAR_PRODUCTS) {
    return {
      lowestPriceProductIds: new Set<string>(),
      mostReviewedProductIds: new Set<string>()
    };
  }

  return {
    lowestPriceProductIds: getLowestPriceProductIds(candidateProducts),
    mostReviewedProductIds: getMostReviewedProductIds(candidateProducts)
  };
};

const getCardLabel = (index: number) => (index === 0 ? "현재 상품" : `비교 상품 ${index}`);

const getProfileDescription = (
  profile: ProductComparisonProfile | undefined,
  skinType?: string,
  sensitivity?: string
) => {
  const values = uniqueValues([
    ...(profile?.matchedConcerns ?? []),
    ...(profile?.expectedEffects ?? [])
  ]).slice(0, 3);
  const skinProfile = uniqueValues([
    skinType ? `${skinType} 피부` : "",
    sensitivity ? `민감도 ${sensitivity}` : ""
  ]).join(" · ");

  if (values.length > 0 && skinProfile)
    return `${values.join(" · ")} 고민과 ${skinProfile} 기준으로 비교해요.`;
  if (values.length > 0) return `${values.join(" · ")} 고민 기준으로 비교해요.`;
  if (skinProfile) return `${skinProfile} 기준으로 비슷한 후보를 비교해요.`;
  return "가격, 핵심 성분, 리뷰 수를 기준으로 비교해요.";
};

function ProductComparisonCard({
  candidateMatchReasons,
  hasMostReviews,
  isLowestPrice,
  label,
  product,
  variant
}: {
  candidateMatchReasons: readonly string[];
  hasMostReviews: boolean;
  isLowestPrice: boolean;
  label: string;
  product: ProductDetail;
  variant: "current" | "candidate";
}) {
  const [hasImageError, setHasImageError] = useState(false);
  const detailPath = `/product-detail?id=${encodeURIComponent(product.product_id)}`;
  const tags = uniqueValues(
    product.evidence_tags.length > 0 ? product.evidence_tags : product.key_ingredients
  ).slice(0, 3);
  const similarityLabels = getSimilarityReasonLabels(candidateMatchReasons);

  const productContent = (
    <>
      <div className="product-comparison-card__image">
        {product.thumbnail_url && !hasImageError ? (
          <img
            alt={product.name}
            onError={() => setHasImageError(true)}
            src={product.thumbnail_url}
          />
        ) : (
          <span>이미지 준비 중이에요</span>
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
    </>
  );

  return (
    <article className={`product-comparison-card ${variant}`}>
      <div className="product-comparison-card__label">{label}</div>
      {variant === "candidate" ? (
        <Link className="product-comparison-card__link" to={detailPath}>
          {productContent}
        </Link>
      ) : (
        productContent
      )}
      <div
        aria-hidden={variant === "current" ? true : undefined}
        className={`product-comparison-card__recommendation${variant === "current" ? " current" : ""}`}
      >
        {variant === "candidate" && similarityLabels.length > 0 ? (
          <div className="product-comparison-card__reasons">
            {similarityLabels.map((reason) => (
              <span key={reason}>{reason}</span>
            ))}
          </div>
        ) : null}
        {isLowestPrice || hasMostReviews ? (
          <div className="product-comparison-card__info">
            {isLowestPrice ? (
              <span className="product-comparison-card__info-chip">최저가</span>
            ) : null}
            {hasMostReviews ? (
              <span className="product-comparison-card__info-chip">리뷰 많음</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function ProductComparisonLoadingCard({ label }: { label: string }) {
  return (
    <article aria-busy="true" className="product-comparison-card loading">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__image">
        <span>상품을 불러오고 있어요</span>
      </div>
      <div className="product-comparison-card__body">
        <div className="product-comparison-skeleton short" />
        <div className="product-comparison-skeleton long" />
        <div className="product-comparison-skeleton price" />
      </div>
      <div aria-hidden="true" className="product-comparison-card__recommendation" />
    </article>
  );
}

function ProductComparisonEmptyCard({ label, message }: { label: string; message: string }) {
  return (
    <article className="product-comparison-card empty">
      <div className="product-comparison-card__label">{label}</div>
      <div className="product-comparison-card__empty">{message}</div>
      <div aria-hidden="true" className="product-comparison-card__recommendation" />
    </article>
  );
}

function ProductComparisonPanel({
  candidateMatchReasons = {},
  comparisonProfile,
  errorMessage,
  expectedProductCount,
  initiallyPriceOnly = false,
  isLoading,
  onClose,
  products,
  sensitivity,
  skinType
}: ProductComparisonPanelProps) {
  const visibleProducts = products.slice(0, MAX_SIMILAR_PRODUCTS + 1);
  const candidateProducts = visibleProducts.slice(1);
  const expectedCandidateCount = Math.min(
    Math.max(expectedProductCount - 1, 1),
    MAX_SIMILAR_PRODUCTS
  );
  const missingCandidateCount = Math.max(expectedCandidateCount - candidateProducts.length, 0);
  const { lowestPriceProductIds, mostReviewedProductIds } =
    getComparisonHighlightProductIds(visibleProducts);

  if (visibleProducts.length === 0) return null;

  const cards = (
    <>
      {visibleProducts.map((product, index) => (
        <ProductComparisonCard
          candidateMatchReasons={
            index === 0 ? [] : (candidateMatchReasons[product.product_id] ?? [])
          }
          hasMostReviews={index > 0 && mostReviewedProductIds.has(product.product_id)}
          isLowestPrice={index > 0 && lowestPriceProductIds.has(product.product_id)}
          key={product.product_id}
          label={getCardLabel(index)}
          product={product}
          variant={index === 0 ? "current" : "candidate"}
        />
      ))}
      {Array.from({ length: isLoading ? missingCandidateCount : 0 }).map((_, index) => (
        <ProductComparisonLoadingCard
          key={`loading-${index}`}
          label={getCardLabel(candidateProducts.length + index + 1)}
        />
      ))}
      {!isLoading && missingCandidateCount > 0 ? (
        <ProductComparisonEmptyCard
          label={getCardLabel(candidateProducts.length + 1)}
          message={errorMessage || "비교 상품 정보를 불러오지 못했습니다."}
        />
      ) : null}
    </>
  );

  return (
    <section
      className={`product-comparison-panel${initiallyPriceOnly ? " product-comparison-panel--inline" : ""}`}
      id="productComparisonPanel"
      aria-labelledby="productComparisonTitle"
    >
      <div className="product-comparison-panel__head">
        <div>
          <p>{getProfileDescription(comparisonProfile, skinType, sensitivity)}</p>
          <h2 id="productComparisonTitle">추천 상품 비교</h2>
        </div>
        {!initiallyPriceOnly ? (
          <button type="button" onClick={onClose} aria-label="상품 비교 닫기">
            ×
          </button>
        ) : null}
      </div>

      <div
        className={`product-comparison-grid count-${Math.max(visibleProducts.length, expectedCandidateCount + 1)}`}
      >
        {cards}
      </div>
    </section>
  );
}

export default ProductComparisonPanel;
