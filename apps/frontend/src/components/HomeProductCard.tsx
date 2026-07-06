import type { ProductCardItem } from "../types/recommendation";
import { trackEvent } from "../lib/appSignals/client";
import ProductThumbnail from "./ProductThumbnail";

type HomeProductCardProps = {
  product: ProductCardItem;
  recommendationId?: string;
  showScore?: boolean;
};

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const hasUsableImageUrl = (url: string | null) =>
  Boolean(url && !/(^|\/)(noimg|no-image|no_image|placeholder)[^/]*\.(gif|png|jpe?g|webp)(\?|$)/i.test(url));

function HomeProductCard({ product, recommendationId, showScore = false }: HomeProductCardProps) {
  const searchParams = new URLSearchParams({ id: product.product_id });
  if (recommendationId) searchParams.set("recommendation_id", recommendationId);
  const currentParams = new URLSearchParams(window.location.search);
  const skinType = currentParams.get("skin_type");
  const sensitivity = currentParams.get("sensitivity");
  if (skinType) searchParams.set("skin_type", skinType);
  if (sensitivity) searchParams.set("sensitivity", sensitivity);
  const detailUrl = `/product-detail?${searchParams.toString()}`;
  const hasImage = hasUsableImageUrl(product.thumbnail_url);

  const openDetail = () => {
    if (recommendationId) {
      trackEvent("recommendation_product_click", {
        recommendationId,
        productId: product.product_id,
        rank: product.rank,
        source: "recommendation_result",
        page: showScore ? "search" : "home",
        metadata: {
          score_bucket: `${Math.floor(product.total_score / 10) * 10}_${Math.floor(product.total_score / 10) * 10 + 10}`
        }
      });
    }
    window.location.href = detailUrl;
  };

  return (
    <article
      aria-label={`${product.brand} ${product.name} 상세 보기`}
      className={`product-card product-card-hit${showScore ? " search-product-card" : ""}${hasImage ? "" : " is-missing-image"}`}
      onClick={openDetail}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail();
        }
      }}
      role="link"
      tabIndex={0}
    >
      <div className="product-img">
        <ProductThumbnail className="product-photo" src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
        <div className="product-labels">
          {showScore && product.rank && product.rank <= 10 ? (
            <span className="label label-ai">{product.rank}위</span>
          ) : null}
        </div>
        {showScore ? (
          <div className="match-score">
            <span className="score-val">{product.total_score}</span>
            <span className="score-label">점</span>
          </div>
        ) : null}
      </div>
      <div className="product-info">
        <div className="product-brand">{product.brand}</div>
        <div className="product-name">{product.name}</div>
        <div className={`key-ingredients${product.key_ingredients.length ? "" : " empty"}`}>
          {product.key_ingredients.length ? (
            product.key_ingredients.slice(0, 3).map((ingredient) => (
              <span className="ingr-tag" key={ingredient}>
                {ingredient}
              </span>
            ))
          ) : (
            <span className="ingr-tag missing">대표 성분 정보 없음</span>
          )}
        </div>
        {!showScore ? (
          <div className="product-price-row">
            <div>
              <div>
                <span className={`sale-price${product.lowest_price === null ? " price-missing" : ""}`}>
                  {formatPrice(product.lowest_price)}
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>
      {showScore ? (
        <div className="search-result-side">
          <div className="search-result-note">성분 근거 기준</div>
          <div className="product-price-row">
            <div>
              <div>
                <span className={`sale-price${product.lowest_price === null ? " price-missing" : ""}`}>
                  {formatPrice(product.lowest_price)}
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export default HomeProductCard;
