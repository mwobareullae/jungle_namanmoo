import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CartResponse, CheckoutPreviewResponse } from "../types/cart";
import { AGENT_SHOW_CART_EVENT, AGENT_SHOW_CHECKOUT_EVENT } from "../lib/agentUiEvents";

type OverlayState =
  | { kind: "cart"; cart: CartResponse; highlightProductId?: string | null }
  | { kind: "checkout"; preview: CheckoutPreviewResponse }
  | null;

function formatPrice(value: number, currency = "KRW") {
  return currency === "KRW" ? `${value.toLocaleString("ko-KR")}원` : `${value.toLocaleString()} ${currency}`;
}

function AgentCommerceOverlay() {
  const navigate = useNavigate();
  const [state, setState] = useState<OverlayState>(null);

  useEffect(() => {
    const showCart = (event: Event) => {
      const detail = (event as CustomEvent<{ cart?: CartResponse; highlightProductId?: string | null }>).detail;
      if (!detail?.cart) return;
      setState({ kind: "cart", cart: detail.cart, highlightProductId: detail.highlightProductId });
      window.dispatchEvent(new Event("cart:updated"));
    };
    const showCheckout = (event: Event) => {
      const detail = (event as CustomEvent<{ preview?: CheckoutPreviewResponse }>).detail;
      if (!detail?.preview) return;
      setState({ kind: "checkout", preview: detail.preview });
    };

    window.addEventListener(AGENT_SHOW_CART_EVENT, showCart);
    window.addEventListener(AGENT_SHOW_CHECKOUT_EVENT, showCheckout);
    return () => {
      window.removeEventListener(AGENT_SHOW_CART_EVENT, showCart);
      window.removeEventListener(AGENT_SHOW_CHECKOUT_EVENT, showCheckout);
    };
  }, []);

  if (!state) return null;

  const close = () => setState(null);
  const items = state.kind === "cart" ? state.cart.items : state.preview.items;
  const total = state.kind === "cart" ? state.cart.subtotal : state.preview.total;
  const currency = state.kind === "cart" ? state.cart.currency : state.preview.currency;
  const destination = (() => {
    if (state.kind === "cart") return "/cart";
    const params = new URLSearchParams();
    state.preview.items.forEach((item) => params.append("cart_item_ids", String(item.id)));
    return `/checkout?${params.toString()}`;
  })();

  return (
    <div className="agent-commerce-overlay" role="presentation">
      <button aria-label="에이전트 실행 결과 닫기" className="agent-commerce-overlay__backdrop" onClick={close} type="button" />
      <aside aria-label={state.kind === "cart" ? "에이전트 장바구니 결과" : "에이전트 결제 미리보기"} className="agent-commerce-drawer">
        <div className="agent-commerce-drawer__header">
          <div>
            <span className="agent-commerce-drawer__eyebrow">AI가 화면에 반영했어요</span>
            <h2>{state.kind === "cart" ? "장바구니" : "결제 예정 금액"}</h2>
          </div>
          <button aria-label="닫기" onClick={close} type="button">×</button>
        </div>
        <div className="agent-commerce-drawer__timeline" aria-label="에이전트 실행 완료 단계">
          <span className="is-done">상품 확인</span>
          <span className="is-done">재고·가격 확인</span>
          <span className="is-done">화면 반영 완료</span>
        </div>
        <div className="agent-commerce-drawer__items">
          {items.map((item) => {
            const highlighted = state.kind === "cart" && item.product_id === state.highlightProductId;
            return (
              <article className={highlighted ? "is-agent-added" : ""} key={item.id}>
                {item.product.thumbnail_url ? <img alt="" src={item.product.thumbnail_url} /> : <span className="agent-commerce-drawer__image-fallback" />}
                <div>
                  <small>{item.product.brand}</small>
                  <strong>{item.product.name}</strong>
                  <span>{item.quantity}개 · {formatPrice(item.line_subtotal, item.currency)}</span>
                </div>
                {highlighted ? <b>방금 담음</b> : null}
              </article>
            );
          })}
        </div>
        <div className="agent-commerce-drawer__footer">
          {state.kind === "checkout" ? <span>배송비 {formatPrice(state.preview.shipping_fee, currency)}</span> : <span>상품 {state.cart.total_quantity}개</span>}
          <strong>총 {formatPrice(total, currency)}</strong>
          <button onClick={() => { close(); navigate(destination); }} type="button">
            {state.kind === "cart" ? "장바구니 보기" : "주문서 보기"}
          </button>
        </div>
      </aside>
    </div>
  );
}

export default AgentCommerceOverlay;
