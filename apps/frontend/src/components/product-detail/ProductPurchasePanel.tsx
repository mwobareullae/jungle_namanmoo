import type { ProductPurchasePanelProps } from "./types";

function ProductPurchasePanel({
  cartErrorMessage,
  cartMessage,
  isAddingToCart,
  isProductSoldOut,
  onAddToCart,
  onBuyNow,
  onRestockNotify,
}: ProductPurchasePanelProps) {
  return (
    <>
      <div data-commerce-only className="detail-cta-row">
        <button className="detail-btn" data-agent-cart-target disabled={isAddingToCart || isProductSoldOut} type="button" onClick={onAddToCart}>
          {isProductSoldOut ? "일시품절" : isAddingToCart ? "담는 중..." : "장바구니"}
        </button>
        <button
          className="detail-btn primary"
          disabled={isAddingToCart}
          type="button"
          onClick={isProductSoldOut ? onRestockNotify : onBuyNow}
        >
          {isProductSoldOut ? "재입고 알림 받기" : "구매하기"}
        </button>
      </div>
      {cartMessage ? <p className="detail-cart-message">{cartMessage}</p> : null}
      {cartErrorMessage ? <p className="detail-cart-message error">{cartErrorMessage}</p> : null}
    </>
  );
}

export default ProductPurchasePanel;
