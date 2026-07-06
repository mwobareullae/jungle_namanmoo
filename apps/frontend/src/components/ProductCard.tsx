import Badge from "./Badge";
import type { ProductCardItem } from "../types/recommendation";

type ProductCardProps = {
  product: ProductCardItem;
  onOpen: (productId: string) => void;
};

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function ProductCard({ product, onOpen }: ProductCardProps) {
  const riskCount = product.risk_flags.length;

  return (
    <article className="product-card result-card">
      <button className="card-hit-area" type="button" onClick={() => onOpen(product.product_id)}>
        {product.thumbnail_url ? (
          <img className="product-image" src={product.thumbnail_url} alt="" />
        ) : (
          <div
            className={`product-thumb tone-${((product.rank - 1) % 3) + 1}`}
            aria-hidden="true"
          />
        )}

        <div className="product-body">
          <p className="eyebrow">{product.brand}</p>
          <h3 className="product-name">{product.name}</h3>
          <p className="ingredients">{product.key_ingredients.join(" · ")}</p>
          <p className="reason-summary">{product.reason_summary}</p>

          <div className="badges">
            {product.evidence_tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
            {riskCount > 0 ? (
              <Badge tone="risk">주의 성분 {riskCount}개</Badge>
            ) : (
              <Badge tone="notice">주의 성분 없음</Badge>
            )}
          </div>

          <div className="card-foot">
            <div>
              <span className="score-label">추천점수</span>
              <strong className="score">{product.total_score}</strong>
            </div>
            <div className="price-block">
              <span className="score-label">최저가</span>
              <strong className="price-text">{formatPrice(product.lowest_price)}</strong>
            </div>
          </div>
        </div>
      </button>
    </article>
  );
}

export default ProductCard;
