import type { ProductCardItem } from "../types/recommendation";
import { trackEvent } from "../lib/appSignals/client";
import { navigateWithinApp } from "../lib/navigation";
import ProductThumbnail from "./ProductThumbnail";

type HomeProductCardProps = {
  product: ProductCardItem;
  recommendationId?: string;
  showScore?: boolean;
  eventContext?: {
    sectionId: string;
    page: string;
    source: string;
    clickEvent: "home_product_click" | "search_result_click";
    impressionEvent: "home_product_impression" | "search_result_impression";
  };
};

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const hasUsableImageUrl = (url: string | null) =>
  Boolean(url && !/(^|\/)(noimg|no-image|no_image|placeholder)[^/]*\.(gif|png|jpe?g|webp)(\?|$)/i.test(url));

function HomeProductCard({ product, recommendationId, showScore = false, eventContext }: HomeProductCardProps) {
  const searchParams = new URLSearchParams({ id: product.product_id });
  if (recommendationId) searchParams.set("recommendation_id", recommendationId);
  const currentParams = new URLSearchParams(window.location.search);
  const skinType = currentParams.get("skin_type");
  const sensitivity = currentParams.get("sensitivity");
  if (skinType) searchParams.set("skin_type", skinType);
  if (sensitivity) searchParams.set("sensitivity", sensitivity);
  const detailUrl = `/product-detail?${searchParams.toString()}`;
  const hasImage = hasUsableImageUrl(product.thumbnail_url);
  const isSoldOut = product.in_stock === false || (product.sales_status !== undefined && product.sales_status !== "ON_SALE");

  const openDetail = () => {
    if (eventContext) {
      trackEvent(eventContext.clickEvent, {
        recommendationId,
        productId: product.product_id,
        rank: product.rank,
        source: eventContext.source,
        page: eventContext.page,
        metadata: { section_id: eventContext.sectionId }
      });
    } else if (recommendationId) {
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
    void navigateWithinApp(detailUrl);
  };

  return (
    <article
      aria-label={`${product.brand} ${product.name} 상세 보기`}
      className={`product-card product-card-hit${showScore ? " search-product-card" : ""}${hasImage ? "" : " is-missing-image"}${isSoldOut ? " is-sold-out" : ""}`}
      data-agent-product-id={product.product_id}
      data-event-page={eventContext?.page}
      data-event-source={eventContext?.source}
      data-impression-event={eventContext?.impressionEvent}
      data-product-id={eventContext ? product.product_id : undefined}
      data-rank={eventContext ? product.rank : undefined}
      data-recommendation-id={eventContext ? recommendationId : undefined}
      data-section-id={eventContext?.sectionId}
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
          {isSoldOut ? <span className="product-card-sold-out-badge">일시품절</span> : null}
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
