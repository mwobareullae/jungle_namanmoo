import { useMemo, useState } from "react";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import ProductCard from "../components/ProductCard";
import type {
  ProductCardItem,
  PurchaseConstraints,
  RecommendationResponse,
  SortOption
} from "../types/recommendation";

type RecommendationResultsPageProps = {
  recommendation: RecommendationResponse;
  onOpenProduct: (productId: string) => void;
  onRestart: () => void;
};

const hasPurchaseConstraints = (constraints: PurchaseConstraints) =>
  constraints.categories.length > 0 ||
  constraints.brands.length > 0 ||
  constraints.price_min !== null ||
  constraints.price_max !== null ||
  constraints.price_text !== null ||
  constraints.price_max_text !== null;

const formatPrice = (price: number) => `${price.toLocaleString("ko-KR")}원`;

const formatPurchasePrice = (constraints: PurchaseConstraints) => {
  if (constraints.price_text) {
    return constraints.price_text;
  }

  if (constraints.price_min !== null && constraints.price_max !== null) {
    return `${formatPrice(constraints.price_min)}~${formatPrice(constraints.price_max)}`;
  }

  if (constraints.price_max !== null) {
    return `${formatPrice(constraints.price_max)} 이하`;
  }

  if (constraints.price_min !== null) {
    return `${formatPrice(constraints.price_min)} 이상`;
  }

  return null;
};

const buildPurchaseBadges = (constraints: PurchaseConstraints) => {
  const badges = [
    ...constraints.categories.map((category) => `카테고리 ${category.name}`),
    ...constraints.brands.map((brand) => `브랜드 ${brand.name}`)
  ];
  const priceBadge = formatPurchasePrice(constraints);

  if (priceBadge) {
    badges.push(`가격 ${priceBadge}`);
  }

  return badges;
};

const getRiskSortScore = (product: ProductCardItem) =>
  product.risk_flags.length + Math.abs(product.score_breakdown?.risk_penalty ?? 0);

function RecommendationResultsPage({
  recommendation,
  onOpenProduct,
  onRestart
}: RecommendationResultsPageProps) {
  const [sortOption, setSortOption] = useState<SortOption>("score");
  const purchaseBadges = buildPurchaseBadges(recommendation.summary.purchase_constraints);
  const hasConstraints = hasPurchaseConstraints(recommendation.summary.purchase_constraints);

  const sortedProducts = useMemo(() => {
    const products = [...recommendation.products];
    if (sortOption === "price") {
      return products.sort(
        (a, b) =>
          (a.lowest_price ?? Number.MAX_SAFE_INTEGER) - (b.lowest_price ?? Number.MAX_SAFE_INTEGER)
      );
    }

    if (sortOption === "risk") {
      return products.sort(
        (a, b) => getRiskSortScore(a) - getRiskSortScore(b) || b.total_score - a.total_score
      );
    }

    return products.sort((a, b) => b.total_score - a.total_score);
  }, [recommendation.products, sortOption]);

  return (
    <section className="wrap results-page">
      <div className="results-head">
        <div>
          <p className="eyebrow">Recommended for you</p>
          <h1 className="section-title">당신을 위한 추천 결과</h1>
        </div>
        <button className="secondary-button" type="button" onClick={onRestart}>
          다시 입력
        </button>
      </div>

      <div className="summary-panel">
        <div>
          <p className="summary-label">입력 요약</p>
          <div className="badges">
            <Badge>{recommendation.summary.skin_type}</Badge>
            <Badge>{recommendation.summary.sensitivity}</Badge>
            {recommendation.summary.avoid_ingredients.map((ingredient) => (
              <Badge key={ingredient} tone="risk">
                회피 {ingredient}
              </Badge>
            ))}
          </div>
        </div>
        <div>
          <p className="summary-label">해석된 고민</p>
          <div className="badges">
            {recommendation.summary.concerns.length > 0 ? (
              recommendation.summary.concerns.map((concern) => <Badge key={concern}>{concern}</Badge>)
            ) : (
              <Badge>기본 추천</Badge>
            )}
          </div>
        </div>
        <div>
          <p className="summary-label">추천 효능</p>
          <div className="badges">
            {recommendation.summary.effects.length > 0 ? (
              recommendation.summary.effects.map((effect) => (
                <Badge key={effect} tone="notice">
                  {effect}
                </Badge>
              ))
            ) : (
              <Badge tone="notice">성분 근거 확인</Badge>
            )}
          </div>
        </div>
        {hasConstraints ? (
          <div>
            <p className="summary-label">구매 조건</p>
            <div className="badges">
              {purchaseBadges.map((badge) => (
                <Badge key={badge} tone="notice">
                  {badge}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
        {recommendation.unmatched_terms.length > 0 ? (
          <div>
            <p className="summary-label">부분 매칭</p>
            <div className="badges">
              {recommendation.unmatched_terms.map((term) => (
                <Badge key={term} tone="risk">
                  {term}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="toolbar">
        <span>{sortedProducts.length}개 상품</span>
        <div className="sort-control" aria-label="정렬">
          <button
            className={sortOption === "score" ? "sort selected" : "sort"}
            type="button"
            onClick={() => setSortOption("score")}
          >
            점수순
          </button>
          <button
            className={sortOption === "price" ? "sort selected" : "sort"}
            type="button"
            onClick={() => setSortOption("price")}
          >
            가격순
          </button>
          <button
            className={sortOption === "risk" ? "sort selected" : "sort"}
            type="button"
            onClick={() => setSortOption("risk")}
          >
            위험 적은 순
          </button>
        </div>
      </div>

      {sortedProducts.length === 0 ? (
        <EmptyState
          title="조건에 맞는 상품이 없어요"
          description={
            hasConstraints
              ? "브랜드, 카테고리, 가격 조건을 조금 완화하면 추천 후보가 늘어납니다."
              : "입력 문장을 조금 더 일반적인 고민으로 바꾸면 추천 후보가 늘어납니다."
          }
          onAction={onRestart}
          actionLabel="다시 입력"
        />
      ) : (
        <div className="product-grid">
          {sortedProducts.map((product) => (
            <ProductCard key={product.product_id} product={product} onOpen={onOpenProduct} />
          ))}
        </div>
      )}
    </section>
  );
}

export default RecommendationResultsPage;
