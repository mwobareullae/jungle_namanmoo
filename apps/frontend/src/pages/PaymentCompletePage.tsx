import { useEffect, useState } from "react";
import CommercePageHeader from "../components/CommercePageHeader";
import HomeHeader from "../components/HomeHeader";
import { api } from "../lib/api";
import { confirmTossPayment } from "../lib/orderApi";
import type { ProductDetail } from "../types/recommendation";

type CompleteProduct = {
  id: string;
  brand: string;
  name: string;
  image: string;
};

type PaymentCompleteSnapshot = {
  orderCode?: string;
  product: CompleteProduct;
  total: number;
  count: number;
  paymentMethod: string;
  createdAt: number;
};

type TossConfirmStatus = "idle" | "confirming" | "approved" | "failed";

const PAYMENT_COMPLETE_SNAPSHOT_KEY = "payment_complete_snapshot";
const PAYMENT_COMPLETE_SNAPSHOT_MAX_AGE_MS = 10 * 60 * 1000;

const fallbackProducts: Record<string, CompleteProduct> = {
  "10": {
    id: "10",
    brand: "라로슈포제",
    name: "라로슈포제 시카플라스트 밤 B5+ 100ml 기획 (+3ml 추가증정)",
    image: "",
  },
  "12": {
    id: "12",
    brand: "웰라쥬",
    name: "[속건조필수템] 웰라쥬 리얼 히알루로닉 블루 100 앰플 75ml 2입 기획",
    image: "",
  },
  "15": {
    id: "15",
    brand: "라운드랩",
    name: "[6월올영픽/총200ml] 라운드랩 자작나무 수분 크림 80ml+80ml 더블 기획 (+40ml)",
    image: "",
  },
};

const formatWon = (value: number) =>
  value > 0 ? `${value.toLocaleString("ko-KR")}원` : "결제금액 확인 중";
const getCompleteParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    id: params.get("id") ?? "",
    total: Number(params.get("total") ?? 0),
    count: Number(params.get("count") ?? 0),
    orderCode: params.get("order_code") ?? "",
    tossOrderId: params.get("orderId") ?? "",
    tossAmount: Number(params.get("amount") ?? 0),
    tossPaymentKey: params.get("paymentKey") ?? "",
    paymentFailed: params.get("payment_failed") === "1" || params.has("code"),
    paymentFailCode: params.get("code") ?? "",
    paymentFailMessage: params.get("message") ?? "",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
    paymentMethod: params.get("payment_method") ?? "간편결제",
  };
};

const mapDetailToCompleteProduct = (product: ProductDetail): CompleteProduct => ({
  id: product.product_id,
  brand: product.brand,
  name: product.name,
  image: product.thumbnail_url ?? product.image_urls[0] ?? "",
});

const getStoredPaymentCompleteSnapshot = (): PaymentCompleteSnapshot | null => {
  try {
    const rawSnapshot = sessionStorage.getItem(PAYMENT_COMPLETE_SNAPSHOT_KEY);
    if (!rawSnapshot) return null;

    const snapshot = JSON.parse(rawSnapshot) as PaymentCompleteSnapshot;
    if (!snapshot.product?.id || !snapshot.product.brand || !snapshot.product.name) return null;
    if (!Number.isFinite(snapshot.total) || !Number.isFinite(snapshot.count)) return null;
    if (!snapshot.paymentMethod) return null;
    if (!Number.isFinite(snapshot.createdAt)) return null;
    if (Date.now() - snapshot.createdAt > PAYMENT_COMPLETE_SNAPSHOT_MAX_AGE_MS) {
      sessionStorage.removeItem(PAYMENT_COMPLETE_SNAPSHOT_KEY);
      return null;
    }

    return snapshot;
  } catch {
    return null;
  }
};

function PaymentCompletePage() {
  const [{
    id,
    total,
    count,
    orderCode,
    tossOrderId,
    tossAmount,
    tossPaymentKey,
    paymentFailed,
    paymentFailCode,
    paymentFailMessage,
    recommendationId,
    skinType,
    sensitivity,
    paymentMethod,
  }] = useState(getCompleteParams);
  const [storedSnapshot] = useState(getStoredPaymentCompleteSnapshot);
  const productId = storedSnapshot?.product.id ?? id;
  const displayTotal = storedSnapshot?.total ?? (total > 0 ? total : tossAmount);
  const displayCount = storedSnapshot?.count ?? (count > 0 ? count : 1);
  const displayPaymentMethod = storedSnapshot?.paymentMethod ?? paymentMethod;
  const hasPaymentInfo = Boolean(storedSnapshot) || Boolean(id && total > 0 && count > 0) || Boolean(tossPaymentKey && tossOrderId && tossAmount > 0);
  const [apiProduct, setApiProduct] = useState<CompleteProduct | null>(null);
  const [orderNo] = useState(() => storedSnapshot?.orderCode || tossOrderId || orderCode || `MWB-${String(Date.now()).slice(-8)}`);
  const [tossConfirmStatus, setTossConfirmStatus] = useState<TossConfirmStatus>("idle");
  const [tossConfirmErrorMessage, setTossConfirmErrorMessage] = useState("");

  useEffect(() => {
    if (!productId) {
      return;
    }

    let isMounted = true;
    api.getProduct(productId, recommendationId)
      .then((product) => {
        if (isMounted) setApiProduct(mapDetailToCompleteProduct(product));
      })
      .catch(() => {
        if (isMounted) setApiProduct(null);
      });

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  useEffect(() => {
    if (!tossPaymentKey || !tossOrderId || tossAmount <= 0) {
      return;
    }

    let isMounted = true;
    setTossConfirmStatus("confirming");
    setTossConfirmErrorMessage("");

    confirmTossPayment({
      payment_key: tossPaymentKey,
      order_code: tossOrderId,
      amount: tossAmount,
    })
      .then(() => {
        if (!isMounted) return;
        setTossConfirmStatus("approved");
        window.dispatchEvent(new Event("cart:updated"));
      })
      .catch((error) => {
        if (!isMounted) return;
        setTossConfirmStatus("failed");
        setTossConfirmErrorMessage(error instanceof Error ? error.message : "토스 결제 승인 확인에 실패했습니다.");
      });

    return () => {
      isMounted = false;
    };
  }, [tossAmount, tossOrderId, tossPaymentKey]);

  if (paymentFailed) {
    return (
      <>
        <HomeHeader />
        <main className="complete-page">
          <section className="complete-shell">
            <CommercePageHeader
              currentStep="complete"
              description="결제가 완료되지 않았습니다. 주문서에서 결제 수단과 금액을 다시 확인해주세요."
              title="결제 실패"
            />

            <div className="complete-hero">
              <h1>결제를 완료하지 못했습니다</h1>
              <p>{paymentFailMessage || "결제창에서 결제가 취소되었거나 실패했습니다."}</p>
              {paymentFailCode ? <p>오류 코드: {paymentFailCode}</p> : null}
            </div>

            <div className="complete-actions">
              <a className="complete-btn" href="/cart">장바구니로 이동</a>
              <a className="complete-btn primary" href="/checkout">주문서 다시 보기</a>
            </div>
          </section>
        </main>
      </>
    );
  }

  if (!hasPaymentInfo) {
    return (
      <>
        <HomeHeader />
        <main className="complete-page">
          <section className="complete-shell">
            <CommercePageHeader
              currentStep="complete"
              description="결제 완료 정보는 주문서에서 결제를 진행한 직후에만 확인할 수 있습니다."
              title="결제 정보 없음"
            />

            <div className="complete-hero">
              <h1>확인할 결제 정보가 없습니다</h1>
              <p>결제 완료 화면은 결제 직후 10분 동안만 유지됩니다. 장바구니에서 주문서를 다시 확인해주세요.</p>
            </div>

            <div className="complete-actions">
              <a className="complete-btn" href="/">쇼핑 계속하기</a>
              <a className="complete-btn primary" href="/cart">장바구니로 이동</a>
            </div>
          </section>
        </main>
      </>
    );
  }

  const product = apiProduct ?? storedSnapshot?.product ?? fallbackProducts[productId] ?? fallbackProducts["10"];
  const productName = displayCount > 1 ? `${product.name} 외 ${displayCount - 1}개` : product.name;
  const detailParams = new URLSearchParams({ id: product.id });
  if (recommendationId) detailParams.set("recommendation_id", recommendationId);
  if (skinType) detailParams.set("skin_type", skinType);
  if (sensitivity) detailParams.set("sensitivity", sensitivity);

  return (
    <>
      <HomeHeader />
      <main className="complete-page">
        <section className="complete-shell">
          <CommercePageHeader
            currentStep="complete"
            description="주문 접수 결과와 결제 정보를 확인해주세요."
            title="결제 완료"
          />

          <div className="complete-hero">
            <div className="complete-mark">
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
            <h1>결제가 완료되었습니다</h1>
            <p>피부 고민에 맞춰 고른 상품 주문이 접수되었어요. 주문 정보와 배송 진행 상황은 마이페이지에서 확인할 수 있습니다.</p>
            {tossConfirmStatus === "confirming" ? (
              <p role="status">토스 결제 승인 정보를 확인하고 있습니다.</p>
            ) : null}
            {tossConfirmStatus === "failed" ? (
              <p role="alert">결제 승인 확인이 필요합니다. {tossConfirmErrorMessage}</p>
            ) : null}
          </div>

          <div className="complete-grid">
            <section className="complete-card">
              <h2>주문 정보</h2>
              <div className="complete-row">
                <span>주문번호</span>
                <strong id="orderNo">{orderNo}</strong>
              </div>
              <div className="complete-row">
                <span>결제금액</span>
                <strong id="paidTotal">{formatWon(displayTotal)}</strong>
              </div>
              <div className="complete-row">
                <span>결제수단</span>
                <strong>{displayPaymentMethod}</strong>
              </div>
              <div className="complete-row">
                <span>배송 예정</span>
                <strong>내일 출고 예정</strong>
              </div>
            </section>

            <section className="complete-card">
              <h2>주문 상품</h2>
              <div className="complete-product">
                {product.image ? (
                  <img
                    id="productImage"
                    src={product.image}
                    alt={`${product.brand} ${product.name}`}
                  />
                ) : (
                  <div className="complete-image-empty" id="productImage">
                    이미지 준비중
                  </div>
                )}
                <div>
                  <div className="complete-brand" id="productBrand">{product.brand}</div>
                  <div className="complete-name" id="productName">{productName}</div>
                </div>
              </div>
            </section>
          </div>

          <div className="complete-actions">
            <a className="complete-btn" href="/">쇼핑 계속하기</a>
            <a className="complete-btn primary" href={`/product-detail?${detailParams.toString()}`}>상품 다시 보기</a>
          </div>
        </section>
      </main>
    </>
  );
}

export default PaymentCompletePage;
