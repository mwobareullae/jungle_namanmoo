import type { ProductPurchasePanelProps } from "./types";

function ProductPurchasePanel({
  cartErrorMessage,
  cartMessage,
  isAddingToCart,
  isProductSoldOut,
  onAddToCart,
  onBuyNow,
}: ProductPurchasePanelProps) {
  return (
    <>
      <div data-commerce-only className="detail-cta-row">
        <button className="detail-btn" disabled={isAddingToCart || isProductSoldOut} type="button" onClick={onAddToCart}>
          {isAddingToCart ? "담는 중..." : "장바구니"}
        </button>
        <button className="detail-btn primary" disabled={isAddingToCart || isProductSoldOut} type="button" onClick={onBuyNow}>
          {isProductSoldOut ? "일시품절" : "구매하기"}
        </button>
      </div>
      {cartMessage ? <p className="detail-cart-message">{cartMessage}</p> : null}
      {cartErrorMessage ? <p className="detail-cart-message error">{cartErrorMessage}</p> : null}
    </>
  );
}

export default ProductPurchasePanel;
