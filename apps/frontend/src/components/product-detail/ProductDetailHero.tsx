import { Link } from "react-router-dom";
import ProductDetailActionButtons from "./ProductDetailActionButtons";
import type { ProductDetailHeroProps } from "./types";

function ProductDetailHero({
  brandPagePath,
  cartErrorMessage,
  cartMessage,
  displayedIsWished,
  isAddingToCart,
  isNarrativeLoading,
  isWishlistPending,
  mainImageUrl,
  narrativeCaution,
  narrativeChips,
  narrativeDetailSections,
  narrativeHeadline,
  narrativeKeyPoints,
  narrativeReason,
  narrativeRole,
  narrativeSelectionGuide,
  narrativeSummaryText,
  onAddToCart,
  onBuyNow,
  onToggleWishlist,
  priceLabel,
  product,
  sensitivity,
  skinType,
}: ProductDetailHeroProps) {
  return (
    <div className="detail-hero">
      <div className="detail-media">
        <div className="detail-image-box">
          {mainImageUrl ? (
            <img id="productImage" src={mainImageUrl} alt={product.name} />
          ) : null}
          {!mainImageUrl ? (
            <div className="detail-image-empty" id="productImageEmpty">이미지 준비중</div>
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
            <strong>AI 추천 요약</strong>
            <span aria-label="추천 문구는 성분 근거와 매칭 점수를 바탕으로 생성됩니다">i</span>
          </div>
          <div className="ai-narrative-body">
            {narrativeRole ? (
              <div className="ai-narrative-role">{narrativeRole}</div>
            ) : null}
            <strong>{isNarrativeLoading ? "추천 문구를 정리하는 중입니다." : narrativeHeadline}</strong>
            <p id="matchReason">
              <span aria-hidden="true">◆</span>
              {narrativeReason}
            </p>
            {narrativeSummaryText ? (
              <p className="ai-narrative-summary">{narrativeSummaryText}</p>
            ) : null}
            <div className="ai-narrative-chip-list">
              {narrativeChips.map((chip) => (
                <span key={chip}>{chip}</span>
              ))}
              <span className="score-chip" id="matchScore">추천 점수 {product.total_score}</span>
            </div>
            {narrativeKeyPoints.length > 0 ? (
              <div className="ai-narrative-keypoints">
                {narrativeKeyPoints.slice(0, 3).map((point) => (
                  <span key={point}>{point}</span>
                ))}
              </div>
            ) : null}
            <div className="ai-narrative-detail-list">
              {narrativeDetailSections.map((section) => (
                <div className="ai-narrative-detail-item" key={section.title}>
                  <strong>{section.title}</strong>
                  <p>{section.body}</p>
                </div>
              ))}
            </div>
            {narrativeCaution ? (
              <div className="ai-narrative-caution">{narrativeCaution}</div>
            ) : null}
            {narrativeSelectionGuide ? (
              <div className="ai-narrative-guide">{narrativeSelectionGuide}</div>
            ) : null}
          </div>
        </div>
        <div
          className="detail-selectors"
          id="profileSelectors"
          style={{ display: skinType || sensitivity ? undefined : "none" }}
        >
          <div className="detail-select-row" id="skinTypeRow" style={{ display: skinType ? undefined : "none" }}>
            <span>피부 타입</span>
            <strong id="skinTypeValue">{skinType}</strong>
          </div>
          <div className="detail-select-row" id="sensitivityRow" style={{ display: sensitivity ? undefined : "none" }}>
            <span>민감성</span>
            <strong id="sensitivityValue">{sensitivity}</strong>
          </div>
        </div>
        <div data-commerce-only className="detail-cta-row">
          <button className="detail-btn" disabled={isAddingToCart} type="button" onClick={onAddToCart}>
            {isAddingToCart ? "담는 중..." : "장바구니"}
          </button>
          <button className="detail-btn primary" disabled={isAddingToCart} type="button" onClick={onBuyNow}>
            구매하기
          </button>
        </div>
        {cartMessage ? <p className="detail-cart-message">{cartMessage}</p> : null}
        {cartErrorMessage ? <p className="detail-cart-message error">{cartErrorMessage}</p> : null}
      </div>
    </div>
  );
}

export default ProductDetailHero;
