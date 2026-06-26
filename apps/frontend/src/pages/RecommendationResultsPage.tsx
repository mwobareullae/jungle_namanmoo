import { useMemo, useState } from "react";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import ProductCard from "../components/ProductCard";
import type { RecommendationResponse, SortOption } from "../types/recommendation";

type RecommendationResultsPageProps = {
  recommendation: RecommendationResponse;
  onOpenProduct: (productId: string) => void;
  onRestart: () => void;
};

function RecommendationResultsPage({
  recommendation,
  onOpenProduct,
  onRestart
}: RecommendationResultsPageProps) {
  const [sortOption, setSortOption] = useState<SortOption>("score");

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
        (a, b) => a.risk_flags.length - b.risk_flags.length || b.total_score - a.total_score
      );
    }

    return products.sort((a, b) => b.total_score - a.total_score);
  }, [recommendation.products, sortOption]);

  return (
    <section className="wrap results-page">
      <div className="results-head">
        <div>
          <p className="eyebrow">Recommended for you</p>
          <h1 className="section-title">성분 근거로 고른 추천 결과</h1>
        </div>
        <button className="secondary-button" type="button" onClick={onRestart}>
          다시 입력
        </button>
      </div>

      <div className="summary-panel">
        <div>
          <p className="summary-label">해석된 고민</p>
          <div className="badges">
            {recommendation.summary.concerns.map((concern) => (
              <Badge key={concern}>{concern}</Badge>
            ))}
          </div>
        </div>
        <div>
          <p className="summary-label">추천 효능</p>
          <div className="badges">
            {recommendation.summary.effects.map((effect) => (
              <Badge key={effect} tone="notice">
                {effect}
              </Badge>
            ))}
          </div>
        </div>
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
          description="입력 문장을 조금 더 일반적인 고민으로 바꾸면 추천 후보가 늘어납니다."
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
