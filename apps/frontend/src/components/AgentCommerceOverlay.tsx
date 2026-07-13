import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CartResponse } from "../types/cart";
import { AGENT_SHOW_CART_EVENT } from "../lib/agentUiEvents";

type CartToastState = { productName?: string; totalQuantity: number } | null;

function AgentCommerceOverlay() {
  const navigate = useNavigate();
  const [cartToast, setCartToast] = useState<CartToastState>(null);
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
    window.addEventListener(AGENT_SHOW_CART_EVENT, showCart);
    return () => {
      window.removeEventListener(AGENT_SHOW_CART_EVENT, showCart);
      if (cartToastTimerRef.current !== null) window.clearTimeout(cartToastTimerRef.current);
    };
  }, []);

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
    </>
  );
}

export default AgentCommerceOverlay;
