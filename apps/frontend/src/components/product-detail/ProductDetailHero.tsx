import { Link } from "react-router-dom";
import ProductDetailActionButtons from "./ProductDetailActionButtons";
import ProductPurchasePanel from "./ProductPurchasePanel";
import RecommendationCriteriaPanel from "./RecommendationCriteriaPanel";
import type { ProductDetailHeroProps } from "./types";

function ProductDetailHero({
  aiNarrativeCautionText,
  aiNarrativeDetailItems,
  aiNarrativeProfileChips,
  aiNarrativeReason,
  aiNarrativeTitle,
  brandPagePath,
  cartErrorMessage,
  cartMessage,
  displayedIsWished,
  isAddingToCart,
  isNarrativeDetailOpen,
  isNarrativeLoading,
  isProductSoldOut,
  isWishlistPending,
  mainImageUrl,
  onAddToCart,
  onBuyNow,
  onRestockNotify,
  onToggleNarrativeDetail,
  onToggleWishlist,
  priceLabel,
  product,
}: ProductDetailHeroProps) {
  return (
    <div className="detail-hero">
      <div className="detail-media">
        <div className={`detail-image-box${isProductSoldOut ? " is-sold-out" : ""}`}>
          {mainImageUrl ? (
            <img id="productImage" src={mainImageUrl} alt={product.name} />
          ) : null}
          {!mainImageUrl ? (
            <div className="detail-image-empty" id="productImageEmpty">이미지 준비중</div>
          ) : null}
          {isProductSoldOut ? (
            <span className="detail-sold-out-overlay">일시품절</span>
          ) : null}
        </div>
      </div>

      <div className="detail-summary">
        <div className="detail-brand-row">
          {brandPagePath ? (
            <Link className="detail-brand detail-brand-link" id="productBrand" to={brandPagePath}>
              {product.brand}
              <span aria-hidden="true">&gt;</span>
            </Link>
          ) : (
            <div className="detail-brand" id="productBrand">{product.brand}</div>
          )}
          <ProductDetailActionButtons
            displayedIsWished={displayedIsWished}
            isWishlistPending={isWishlistPending}
            onToggleWishlist={onToggleWishlist}
          />
        </div>
        <h1 className="detail-title" id="productName">{product.name}</h1>
        <div className="detail-price-panel">
          <div className="detail-price-row">
            <span className="detail-price" id="productPrice">{priceLabel}</span>
          </div>
        </div>
        <div className="detail-tags" id="productTags">
          {product.evidence_tags.map((tag) => (
            <span className="detail-tag" key={tag}>{tag}</span>
          ))}
        </div>
        <div className={`detail-match ai-narrative-card${isNarrativeLoading ? " loading" : ""}`}>
          <div className="ai-narrative-head">
            <span className="ai-narrative-head-icon" aria-hidden="true">
              <svg height="18" viewBox="0 0 18 18" width="18">
                <defs>
                  <filter
                    colorInterpolationFilters="sRGB"
                    filterUnits="userSpaceOnUse"
                    height="18"
                    id="aiRecommendationIconTint"
                    width="18"
                    x="0"
                    y="0"
                  >
                    <feColorMatrix
                      type="matrix"
                      values="0 0 0 0 0.290196 0 0 0 0 0.65098 0 0 0 0 0.721569 0 0 0 1 0"
                    />
                  </filter>
                </defs>
                <image
                  filter="url(#aiRecommendationIconTint)"
                  height="18"
                  href="/spa-assets/ai-recommendation-summary-icon.png"
                  width="18"
                />
              </svg>
            </span>
            <strong>AI 추천 요약</strong>
          </div>
          <div className="ai-narrative-body">
            <div className="ai-narrative-title-row">
              <strong>{isNarrativeLoading ? "추천 문구를 정리하는 중입니다." : aiNarrativeTitle}</strong>
              <span className="ai-narrative-score" id="matchScore">
                <strong>{Math.round(product.total_score)}</strong>점
              </span>
            </div>
            <p className="ai-narrative-reason" id="matchReason">{aiNarrativeReason}</p>
            {aiNarrativeProfileChips.length > 0 ? (
              <div className="ai-narrative-profile-chips">
                {aiNarrativeProfileChips.map((chip) => (
                  <span key={chip}>{chip}</span>
                ))}
              </div>
            ) : null}
            <div className="ai-narrative-caution-row">
              <span className="ai-narrative-caution-icon" aria-hidden="true">i</span>
              <span>{aiNarrativeCautionText}</span>
            </div>
            <button
              className="ai-narrative-detail-toggle"
              type="button"
              aria-expanded={isNarrativeDetailOpen}
              aria-controls="aiNarrativeDetailList"
              onClick={onToggleNarrativeDetail}
            >
              {isNarrativeDetailOpen ? "왜 추천했는지 접기" : "왜 추천했는지 보기"}
            </button>
            {isNarrativeDetailOpen ? (
              <div className="ai-narrative-detail-list" id="aiNarrativeDetailList">
                {aiNarrativeDetailItems.map((section) => (
                  <div className="ai-narrative-detail-item" key={section.title}>
                    <strong>{section.title}</strong>
                    <p>{section.body}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <RecommendationCriteriaPanel product={product} />
        <ProductPurchasePanel
          cartErrorMessage={cartErrorMessage}
          cartMessage={cartMessage}
          isAddingToCart={isAddingToCart}
          isProductSoldOut={isProductSoldOut}
          onAddToCart={onAddToCart}
          onBuyNow={onBuyNow}
          onRestockNotify={onRestockNotify}
        />
      </div>
    </div>
  );
}

export default ProductDetailHero;
