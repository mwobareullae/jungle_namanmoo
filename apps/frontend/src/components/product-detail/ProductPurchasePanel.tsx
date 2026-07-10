import type { ProductPurchasePanelProps } from "./types";

function ProductPurchasePanel({
  cartErrorMessage,
  cartMessage,
  isAddingToCart,
  onAddToCart,
  onBuyNow,
}: ProductPurchasePanelProps) {
  return (
    <>
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
    </>
  );
}

export default ProductPurchasePanel;
