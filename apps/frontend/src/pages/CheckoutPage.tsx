import { useEffect, useMemo, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import { api } from "../lib/api";
import type { ProductDetail } from "../types/recommendation";

type OrderProduct = {
  id: string;
  brand: string;
  name: string;
  image: string;
  price: number;
  original: number;
  chips: string[];
};

const fallbackProducts: OrderProduct[] = [
  {
    id: "10",
    brand: "라로슈포제",
    name: "라로슈포제 시카플라스트 밤 B5+ 100ml 기획 (+3ml 추가증정)",
    image: "",
    price: 34850,
    original: 41000,
    chips: ["판테놀", "마데카소사이드", "글리세린"],
  },
  {
    id: "12",
    brand: "웰라쥬",
    name: "[속건조필수템] 웰라쥬 리얼 히알루로닉 블루 100 앰플 75ml 2입 기획",
    image: "",
    price: 29800,
    original: 50000,
    chips: ["판테놀", "히알루론산", "글리세린"],
  },
  {
    id: "15",
    brand: "라운드랩",
    name: "[6월올영픽/총200ml] 라운드랩 자작나무 수분 크림 80ml+80ml 더블 기획 (+40ml)",
    image: "",
    price: 24600,
    original: 44000,
    chips: ["판테놀", "히알루론산", "글리세린"],
  },
];

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;
const getCheckoutParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    selectedId: params.get("id") ?? "",
    mode: params.get("mode") ?? "cart",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
  };
};

const mapDetailToOrderProduct = (product: ProductDetail): OrderProduct => ({
  id: product.product_id,
  brand: product.brand,
  name: product.name,
  image: product.thumbnail_url ?? product.image_urls[0] ?? "",
  price: product.lowest_price ?? product.prices[0]?.price ?? 0,
  original: product.lowest_price ?? product.prices[0]?.price ?? 0,
  chips: product.evidence_tags.length > 0 ? product.evidence_tags.slice(0, 3) : product.key_ingredients.slice(0, 3),
});

function CheckoutPage() {
  const [{ selectedId, mode, recommendationId, skinType, sensitivity }] = useState(getCheckoutParams);
  const [apiProduct, setApiProduct] = useState<OrderProduct | null>(null);
  const [paymentMethod, setPaymentMethod] = useState("간편결제");

  useEffect(() => {
    if (!selectedId || fallbackProducts.some((product) => product.id === selectedId)) return;

    let isMounted = true;
    api.getProduct(selectedId, recommendationId)
      .then((product) => {
        if (isMounted) setApiProduct(mapDetailToOrderProduct(product));
      })
      .catch(() => {
        if (isMounted) setApiProduct(null);
      });

    return () => {
      isMounted = false;
    };
  }, [recommendationId, selectedId]);

  const items = useMemo(() => {
    if (selectedId) {
      const fallback = fallbackProducts.find((product) => product.id === selectedId);
      return [apiProduct ?? fallback ?? fallbackProducts[0]];
    }
    return fallbackProducts;
  }, [apiProduct, selectedId]);

  const subtotal = items.reduce((sum, item) => sum + item.original, 0);
  const total = items.reduce((sum, item) => sum + item.price, 0);
  const discount = subtotal - total;
  const title = mode === "buy" ? "바로 구매 주문서" : "장바구니 주문서";

  const handlePayment = () => {
    const representative = items[0] ?? fallbackProducts[0];
    const params = new URLSearchParams({
      id: representative.id,
      total: String(total),
      count: String(items.length),
    });
    if (recommendationId) params.set("recommendation_id", recommendationId);
    if (skinType) params.set("skin_type", skinType);
    if (sensitivity) params.set("sensitivity", sensitivity);
    window.location.href = `/payment-complete?${params.toString()}`;
  };

  return (
    <>
      <HomeHeader />
      <main className="checkout-page">
        <section className="checkout-shell">
          <div className="checkout-title-row">
            <div>
              <h1>{title}</h1>
              <p>성분 근거로 고른 상품을 확인하고 배송·결제 정보를 입력해주세요.</p>
            </div>
            <div className="checkout-steps">
              <strong>장바구니</strong>
              <span>›</span>
              <strong>주문서</strong>
              <span>›</span>
              <span>결제완료</span>
            </div>
          </div>

          <div className="checkout-layout">
            <div className="checkout-main">
              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>주문 상품</h2>
                  <span id="cartCountLabel">상품 {items.length}개</span>
                </div>
                <div id="cartItems">
                  {items.map((item) => (
                    <div className="cart-line" key={item.id}>
                      {item.image ? (
                        <img src={item.image} alt={`${item.brand} ${item.name}`} />
                      ) : (
                        <div className="cart-image-empty" aria-label={`${item.brand} ${item.name} 이미지 준비중`}>
                          이미지 준비중
                        </div>
                      )}
                      <div>
                        <div className="cart-brand">{item.brand}</div>
                        <div className="cart-name">{item.name}</div>
                        <div className="cart-meta">
                          {item.chips.map((chip) => <span className="cart-chip" key={chip}>{chip}</span>)}
                        </div>
                      </div>
                      <div>
                        <div className="cart-price">{formatWon(item.price)}</div>
                        <div className="cart-qty">수량 1개</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>배송 정보</h2>
                  <span>필수 입력</span>
                </div>
                <div className="form-grid">
                  <div className="form-field">
                    <label htmlFor="receiverName">받는 분</label>
                    <input id="receiverName" defaultValue="나코" autoComplete="name" />
                  </div>
                  <div className="form-field">
                    <label htmlFor="receiverPhone">연락처</label>
                    <input id="receiverPhone" defaultValue="010-0000-0000" autoComplete="tel" />
                  </div>
                  <div className="form-field full">
                    <label htmlFor="address">주소</label>
                    <input id="address" defaultValue="서울특별시 성분구 피부로 12" autoComplete="street-address" />
                  </div>
                  <div className="form-field full">
                    <label htmlFor="memo">배송 요청사항</label>
                    <select id="memo" defaultValue="문 앞에 놓아주세요">
                      <option>문 앞에 놓아주세요</option>
                      <option>경비실에 맡겨주세요</option>
                      <option>배송 전 연락주세요</option>
                    </select>
                  </div>
                </div>
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>결제 수단</h2>
                  <span>선택 1개</span>
                </div>
                <div className="payment-options">
                  {["간편결제", "신용카드", "무통장입금"].map((method) => (
                    <button
                      className={`payment-option${paymentMethod === method ? " active" : ""}`}
                      onClick={() => setPaymentMethod(method)}
                      type="button"
                      key={method}
                    >
                      {method}
                    </button>
                  ))}
                </div>
              </section>
            </div>

            <aside className="order-summary">
              <h2>결제 금액</h2>
              <div className="summary-row">
                <span>상품 금액</span>
                <strong id="summarySubtotal">{formatWon(subtotal)}</strong>
              </div>
              <div className="summary-row">
                <span>상품 할인</span>
                <strong id="summaryDiscount">-{formatWon(discount)}</strong>
              </div>
              <div className="summary-row">
                <span>배송비</span>
                <strong>무료</strong>
              </div>
              <div className="summary-divider" />
              <div className="summary-total">
                <span>총 결제금액</span>
                <strong id="summaryTotal">{formatWon(total)}</strong>
              </div>
              <button className="checkout-btn-main" type="button" onClick={handlePayment}>결제하기</button>
              <p className="summary-note">결제하기를 누르면 주문 내용을 확인한 것으로 간주됩니다. 실제 결제는 연결되지 않은 시안 화면입니다.</p>
            </aside>
          </div>
        </section>
      </main>

      <div className="mobile-pay-bar">
        <div className="mobile-pay-total">
          <span>총 결제금액</span>
          <strong id="mobileTotal">{formatWon(total)}</strong>
        </div>
        <button className="checkout-btn-main" type="button" onClick={handlePayment}>결제하기</button>
      </div>
    </>
  );
}

export default CheckoutPage;
