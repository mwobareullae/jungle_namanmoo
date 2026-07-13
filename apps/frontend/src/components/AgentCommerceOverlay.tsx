import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CartResponse, CheckoutPreviewResponse } from "../types/cart";
import { AGENT_SHOW_CART_EVENT, AGENT_SHOW_CHECKOUT_EVENT } from "../lib/agentUiEvents";

type CartToastState = { productName?: string; totalQuantity: number } | null;

function formatPrice(value: number, currency = "KRW") {
  return currency === "KRW" ? `${value.toLocaleString("ko-KR")}원` : `${value.toLocaleString()} ${currency}`;
}

function AgentCommerceOverlay() {
  const navigate = useNavigate();
  const [cartToast, setCartToast] = useState<CartToastState>(null);
  const [checkoutPreview, setCheckoutPreview] = useState<CheckoutPreviewResponse | null>(null);
  const cartToastTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const showCart = (event: Event) => {
      const detail = (event as CustomEvent<{ cart?: CartResponse; highlightProductId?: string | null }>).detail;
      if (!detail?.cart) return;
      const addedItem = detail.cart.items.find((item) => item.product_id === detail.highlightProductId);
      setCartToast({ productName: addedItem?.product.name, totalQuantity: detail.cart.total_quantity });
      if (cartToastTimerRef.current !== null) window.clearTimeout(cartToastTimerRef.current);
      cartToastTimerRef.current = window.setTimeout(() => setCartToast(null), 5000);
      window.dispatchEvent(new Event("cart:updated"));
    };
    const showCheckout = (event: Event) => {
      const detail = (event as CustomEvent<{ preview?: CheckoutPreviewResponse }>).detail;
      if (!detail?.preview) return;
      setCheckoutPreview(detail.preview);
    };

    window.addEventListener(AGENT_SHOW_CART_EVENT, showCart);
    window.addEventListener(AGENT_SHOW_CHECKOUT_EVENT, showCheckout);
    return () => {
      window.removeEventListener(AGENT_SHOW_CART_EVENT, showCart);
      window.removeEventListener(AGENT_SHOW_CHECKOUT_EVENT, showCheckout);
      if (cartToastTimerRef.current !== null) window.clearTimeout(cartToastTimerRef.current);
    };
  }, []);

  const checkoutDestination = (() => {
    if (!checkoutPreview) return "/checkout";
    const params = new URLSearchParams();
    checkoutPreview.items.forEach((item) => params.append("cart_item_ids", String(item.id)));
    return `/checkout?${params.toString()}`;
  })();

  return (
    <>
      {cartToast ? (
        <div className="agent-cart-toast" role="status" aria-live="polite">
          <span aria-hidden="true">✓</span>
          <div>
            <strong>장바구니에 담았어요</strong>
            <small>{cartToast.productName ?? `현재 장바구니 상품 ${cartToast.totalQuantity}개`}</small>
          </div>
          <button onClick={() => { setCartToast(null); navigate("/cart"); }} type="button">장바구니 보기</button>
          <button aria-label="알림 닫기" className="agent-cart-toast__close" onClick={() => setCartToast(null)} type="button">×</button>
        </div>
      ) : null}
      {checkoutPreview ? (
        <div className="agent-commerce-overlay" role="presentation">
          <button aria-label="에이전트 실행 결과 닫기" className="agent-commerce-overlay__backdrop" onClick={() => setCheckoutPreview(null)} type="button" />
          <aside aria-label="에이전트 결제 미리보기" className="agent-commerce-drawer">
            <div className="agent-commerce-drawer__header">
              <div>
                <span className="agent-commerce-drawer__eyebrow">AI가 화면에 반영했어요</span>
                <h2>결제 예정 금액</h2>
              </div>
              <button aria-label="닫기" onClick={() => setCheckoutPreview(null)} type="button">×</button>
            </div>
            <div className="agent-commerce-drawer__timeline" aria-label="에이전트 실행 완료 단계">
              <span className="is-done">상품 확인</span>
              <span className="is-done">재고·가격 확인</span>
              <span className="is-done">화면 반영 완료</span>
            </div>
            <div className="agent-commerce-drawer__items">
              {checkoutPreview.items.map((item) => (
                <article key={item.id}>
                  {item.product.thumbnail_url ? <img alt="" src={item.product.thumbnail_url} /> : <span className="agent-commerce-drawer__image-fallback" />}
                  <div>
                    <small>{item.product.brand}</small>
                    <strong>{item.product.name}</strong>
                    <span>{item.quantity}개 · {formatPrice(item.line_subtotal, item.currency)}</span>
                  </div>
                </article>
              ))}
            </div>
            <div className="agent-commerce-drawer__footer">
              <span>배송비 {formatPrice(checkoutPreview.shipping_fee, checkoutPreview.currency)}</span>
              <strong>총 {formatPrice(checkoutPreview.total, checkoutPreview.currency)}</strong>
              <button onClick={() => { setCheckoutPreview(null); navigate(checkoutDestination); }} type="button">
                주문서 보기
              </button>
            </div>
          </aside>
          </div>
      ) : null}
    </>
  );
}

export default AgentCommerceOverlay;
