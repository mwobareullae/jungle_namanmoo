import { useLayoutEffect, useRef, useState } from "react";
import type { ProductCardItem } from "../types/recommendation";
import { trackEvent } from "../lib/appSignals/client";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import ProductSoldOutOverlay from "./ProductSoldOutOverlay";
import ProductThumbnail from "./ProductThumbnail";

type HomeProductCardProps = {
  displayRank?: number;
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

type ProductIngredientTagsProps = {
  className: string;
  tags: string[];
};

export function ProductIngredientTags({ className, tags }: ProductIngredientTagsProps) {
  const maxVisibleRows = 1;
  const wrapperRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const [visibleTagCount, setVisibleTagCount] = useState(tags.length);
  const tagsKey = tags.join("\u0001");
  const hiddenTagCount = tags.length - visibleTagCount;

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    const measure = measureRef.current;
    if (!wrapper || !measure || tags.length < 2) {
      setVisibleTagCount(tags.length);
      return;
    }

    const updateVisibleTagCount = () => {
      const availableWidth = wrapper.clientWidth;
      const tagElements = Array.from(measure.querySelectorAll<HTMLElement>("[data-ingredient-tag]"));
      const moreElement = measure.querySelector<HTMLElement>("[data-ingredient-more]");
      if (!availableWidth || tagElements.length !== tags.length || !moreElement) return;

      const gap = Number.parseFloat(window.getComputedStyle(measure).columnGap) || 6;
      const tagWidths = tagElements.map((element) => element.offsetWidth);
      const moreWidth = moreElement.offsetWidth;
      const rowCount = (widths: number[]) => widths.reduce(
        (state, width) => {
          if (state.rowWidth === 0) return { rowCount: 1, rowWidth: width };
          if (state.rowWidth + gap + width <= availableWidth) {
            return { rowCount: state.rowCount, rowWidth: state.rowWidth + gap + width };
          }
          return { rowCount: state.rowCount + 1, rowWidth: width };
        },
        { rowCount: 0, rowWidth: 0 },
      ).rowCount;

      let nextVisibleTagCount = tags.length;
      if (rowCount(tagWidths) > maxVisibleRows) {
        for (let count = tags.length - 1; count >= 0; count -= 1) {
          if (rowCount([...tagWidths.slice(0, count), moreWidth]) <= maxVisibleRows) {
            nextVisibleTagCount = count;
            break;
          }
        }
      }
      setVisibleTagCount((current) => current === nextVisibleTagCount ? current : nextVisibleTagCount);
    };

    const animationFrame = window.requestAnimationFrame(updateVisibleTagCount);
    const resizeObserver = new ResizeObserver(updateVisibleTagCount);
    resizeObserver.observe(wrapper);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
    };
  }, [tags.length, tagsKey]);

  if (tags.length === 0) {
    return <div className={`${className} empty`}><span className="ingr-tag missing">대표 성분 정보 없음</span></div>;
  }

  return (
    <div className="ingredient-tag-list-wrapper" ref={wrapperRef}>
      <div className={className}>
        {tags.slice(0, visibleTagCount).map((ingredient) => (
          <span className="ingr-tag" key={ingredient}>{ingredient}</span>
        ))}
        {hiddenTagCount > 0 ? <span className="ingr-tag ingredient-tag-list-more" title={tags.slice(visibleTagCount).join(", ")}>+{hiddenTagCount}</span> : null}
      </div>
      <div aria-hidden="true" className={`${className} ingredient-tag-list-measure`} ref={measureRef}>
        {tags.map((ingredient) => (
          <span className="ingr-tag" data-ingredient-tag key={ingredient}>{ingredient}</span>
        ))}
        <span className="ingr-tag ingredient-tag-list-more" data-ingredient-more>+{tags.length}</span>
      </div>
    </div>
  );
}

function HomeProductCard({ displayRank, product, recommendationId, showScore = false, eventContext }: HomeProductCardProps) {
  const searchParams = new URLSearchParams({ id: product.product_id });
  if (recommendationId) {
    searchParams.set("recommendation_id", recommendationId);
    searchParams.set("recommendation_rank", String(product.rank));
  }
  const currentParams = new URLSearchParams(window.location.search);
  const skinType = currentParams.get("skin_type");
  const sensitivity = currentParams.get("sensitivity");
  if (skinType) searchParams.set("skin_type", skinType);
  if (sensitivity) searchParams.set("sensitivity", sensitivity);
  const detailUrl = `/product-detail?${searchParams.toString()}`;
  const hasImage = hasUsableImageUrl(product.thumbnail_url);
  const isSoldOut = isProductSoldOut(product);
  const rankForDisplay = displayRank ?? product.rank;

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
        {isSoldOut ? <ProductSoldOutOverlay /> : null}
        <div className="product-labels">
          {showScore && rankForDisplay ? (
            <span className="label label-ai">{rankForDisplay}위</span>
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
        <ProductIngredientTags className="key-ingredients" tags={product.key_ingredients.slice(0, 3)} />
        {!showScore ? (
          <div className="product-price-row">
            <div>
              <div>
                <span className={`sale-price${product.lowest_price === null ? " price-missing" : ""}${isSoldOut ? " product-price--sold-out" : ""}`}>
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
                <span className={`sale-price${product.lowest_price === null ? " price-missing" : ""}${isSoldOut ? " product-price--sold-out" : ""}`}>
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
