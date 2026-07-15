import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CommercePageHeader from "../components/CommercePageHeader";
import HomeHeader from "../components/HomeHeader";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { cancelOrder, confirmTossPayment, getOrderDetail } from "../lib/orderApi";
import type { OrderDetailItem, OrderDetailResponse } from "../types/order";
import type { ProductDetail } from "../types/recommendation";

type CompleteProduct = {
  id: string;
  brand: string;
  name: string;
  image: string;
  price?: number;
  quantity?: number;
  option?: string;
};

type PaymentCompleteSnapshot = {
  orderCode?: string;
  product: CompleteProduct;
  products?: CompleteProduct[];
  total: number;
  count: number;
  paymentMethod: string;
  shippingAddress?: string;
  createdAt: number;
};

type TossConfirmStatus = "idle" | "confirming" | "approved" | "failed";

const PAYMENT_COMPLETE_SNAPSHOT_KEY = "payment_complete_snapshot";
const PAYMENT_COMPLETE_SNAPSHOT_MAX_AGE_MS = 10 * 60 * 1000;
const ORDER_DETAIL_MAX_RETRIES = 2;
const ORDER_DETAIL_RETRY_DELAY_MS = 1_500;

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

const mapOrderItemToCompleteProduct = (item: OrderDetailItem): CompleteProduct => ({
  id: item.product_id,
  brand: item.brand_name,
  name: item.product_name,
  image: getProductImageUrl(item.thumbnail_storage_key, "w400"),
  price: item.line_total,
  quantity: item.quantity,
});

const formatPaymentProvider = (provider?: string) => {
  switch (provider) {
    case "TOSS":
      return "토스페이먼츠";
    case "MOCK":
      return "mock 결제";
    case "KAKAO_PAY":
      return "카카오페이";
    case "NAVER_PAY":
      return "네이버페이";
    default:
      return "간편결제";
  }
};

const formatShippingAddress = (address?: OrderDetailResponse["shipping_address"] | null) => {
  if (!address) return "";
  return [address.address1, address.address2].filter(Boolean).join(" ");
};

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
    paymentMethod,
  }] = useState(getCompleteParams);
  const { user } = useAuth();
  const [storedSnapshot] = useState(getStoredPaymentCompleteSnapshot);
  const detailOrderCode = orderCode || tossOrderId || storedSnapshot?.orderCode || "";
  const productId = storedSnapshot?.product.id ?? id;
  const [orderDetail, setOrderDetail] = useState<OrderDetailResponse | null>(null);
  const [isOrderDetailLoading, setIsOrderDetailLoading] = useState(false);
  const [orderDetailErrorMessage, setOrderDetailErrorMessage] = useState("");
  const displayTotal = orderDetail?.total ?? storedSnapshot?.total ?? (total > 0 ? total : tossAmount);
  const displayPaymentMethod = orderDetail
    ? formatPaymentProvider(orderDetail.payment.provider)
    : storedSnapshot?.paymentMethod ?? paymentMethod;
  const hasPaymentInfo = Boolean(detailOrderCode) || Boolean(storedSnapshot) || Boolean(id && total > 0 && count > 0) || Boolean(tossPaymentKey && tossOrderId && tossAmount > 0);
  const shouldConfirmTossPayment = Boolean(tossPaymentKey && tossOrderId && tossAmount > 0);
  const [apiProduct, setApiProduct] = useState<CompleteProduct | null>(null);
  const [isProductListOpen, setIsProductListOpen] = useState(false);
  const [generatedFallbackOrderNo] = useState(() => `MWB-${String(Date.now()).slice(-8)}`);
  const fallbackOrderNo = storedSnapshot?.orderCode || tossOrderId || orderCode || generatedFallbackOrderNo;
  const [tossConfirmStatus, setTossConfirmStatus] = useState<TossConfirmStatus>(() =>
    shouldConfirmTossPayment ? "confirming" : "idle",
  );
  const [tossConfirmErrorMessage, setTossConfirmErrorMessage] = useState("");
  const [failedPaymentCancelMessage, setFailedPaymentCancelMessage] = useState("");

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
    if (!detailOrderCode || paymentFailed) {
      return;
    }

    if (shouldConfirmTossPayment && tossConfirmStatus === "confirming") {
      return;
    }

    let isMounted = true;
    let retryTimerId: number | null = null;

    const loadOrderDetail = async (retryCount = 0): Promise<void> => {
      try {
        const detail = await getOrderDetail(detailOrderCode);
        if (!isMounted) return;
        setOrderDetail(detail);
        setIsOrderDetailLoading(false);
      } catch (error) {
        if (!isMounted) return;

        if (retryCount < ORDER_DETAIL_MAX_RETRIES) {
          retryTimerId = window.setTimeout(
            () => void loadOrderDetail(retryCount + 1),
            ORDER_DETAIL_RETRY_DELAY_MS,
          );
          return;
        }

        setOrderDetail(null);
        setOrderDetailErrorMessage(
          error instanceof Error ? error.message : "주문 상세 정보를 불러오지 못했습니다.",
        );
        setIsOrderDetailLoading(false);
      }
    };

    const initialTimerId = window.setTimeout(() => {
      setIsOrderDetailLoading(true);
      setOrderDetailErrorMessage("");
      void loadOrderDetail();
    }, 0);

    return () => {
      isMounted = false;
      window.clearTimeout(initialTimerId);
      if (retryTimerId !== null) {
        window.clearTimeout(retryTimerId);
      }
    };
  }, [detailOrderCode, paymentFailed, shouldConfirmTossPayment, tossConfirmStatus]);

  useEffect(() => {
    if (!tossPaymentKey || !tossOrderId || tossAmount <= 0) {
      return;
    }

    let isMounted = true;
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

  useEffect(() => {
    const failedOrderCode = orderCode || tossOrderId;
    if (!paymentFailed || !failedOrderCode) {
      return;
    }

    let isMounted = true;
    cancelOrder(failedOrderCode)
      .then(() => {
        if (!isMounted) return;
        sessionStorage.removeItem(PAYMENT_COMPLETE_SNAPSHOT_KEY);
        window.dispatchEvent(new Event("cart:updated"));
        setFailedPaymentCancelMessage("주문을 취소하고 장바구니로 되돌렸습니다.");
        navigateWithinApp("/cart");
      })
      .catch((error) => {
        if (!isMounted) return;
        setFailedPaymentCancelMessage(
          error instanceof Error
            ? error.message
            : "주문 취소 상태를 확인하지 못했습니다. 장바구니를 다시 확인해주세요.",
        );
      });

    return () => {
      isMounted = false;
    };
  }, [orderCode, paymentFailed, tossOrderId]);

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
              {failedPaymentCancelMessage ? <p>{failedPaymentCancelMessage}</p> : null}
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

  const orderDetailProducts = orderDetail?.items.map(mapOrderItemToCompleteProduct) ?? [];
  const product = apiProduct ?? storedSnapshot?.product ?? orderDetailProducts[0] ?? fallbackProducts[productId] ?? fallbackProducts["10"];
  const completeProducts = orderDetailProducts.length
    ? orderDetailProducts
    : storedSnapshot?.products?.length
    ? storedSnapshot.products
    : [product];
  const productName = completeProducts.length > 1 ? `${completeProducts[0].name} 외 ${completeProducts.length - 1}개` : product.name;
  const expectedPointAmount = Math.floor(displayTotal * 0.01);
  const shippingAddress = formatShippingAddress(orderDetail?.shipping_address) || storedSnapshot?.shippingAddress || "배송지는 주문 내역에서 확인해주세요.";
  const displayNickname = user?.nickname || "고객";
  const displayOrderNo = orderDetail?.order_code || fallbackOrderNo;

  return (
    <>
      <HomeHeader />
      <main className="complete-page">
        <section className="complete-shell">
          <CommercePageHeader currentStep="complete" title="주문완료" />

          <section className="complete-receipt-card">
            <div className="complete-mark">
              <span>✓</span>
            </div>

            <h1>주문이 완료되었어요</h1>
            <p className="complete-subcopy">{displayNickname}님, 주문해주셔서 감사합니다.</p>

            {tossConfirmStatus === "confirming" ? (
              <p className="complete-status-message" role="status">토스 결제 승인 정보를 확인하고 있습니다.</p>
            ) : null}
            {tossConfirmStatus === "failed" ? (
              <p className="complete-status-message error" role="alert">결제 승인 확인이 필요합니다. {tossConfirmErrorMessage}</p>
            ) : null}
            {isOrderDetailLoading ? (
              <p className="complete-status-message" role="status">주문 상세 정보를 불러오고 있습니다.</p>
            ) : null}
            {orderDetailErrorMessage ? (
              <p className="complete-status-message error" role="alert">
                주문 상세 조회에 실패해 결제 직후 정보를 표시합니다. {orderDetailErrorMessage}
              </p>
            ) : null}

            <section className="complete-info-box" aria-labelledby="completeOrderInfoTitle">
              <h2 id="completeOrderInfoTitle">주문 정보</h2>
              <div className="complete-row">
                <span>주문번호</span>
                <strong id="orderNo">{displayOrderNo}</strong>
              </div>
              <div className="complete-row">
                <span>도착예정</span>
                <strong className="accent">내일 오전 도착</strong>
              </div>
              <div className="complete-row">
                <span>배송지</span>
                <strong>{shippingAddress}</strong>
              </div>
            </section>

            <section className="complete-info-box" aria-labelledby="completePaymentInfoTitle">
              <h2 id="completePaymentInfoTitle">결제 정보</h2>
              <div className="complete-row">
                <span>결제금액</span>
                <strong id="paidTotal">{formatWon(displayTotal)}</strong>
              </div>
              <div className="complete-row">
                <span>결제수단</span>
                <strong>{displayPaymentMethod}</strong>
              </div>
            </section>

            <section className="complete-product-toggle">
              <button
                type="button"
                aria-controls="completeProductList"
                aria-expanded={isProductListOpen}
                onClick={() => setIsProductListOpen((current) => !current)}
              >
                <span>주문 상품</span>
                <strong>{productName}</strong>
                <i>{isProductListOpen ? "접기" : `${completeProducts.length}개 보기`}</i>
              </button>

              {isProductListOpen ? (
                <div className="complete-product-list" id="completeProductList">
                  {completeProducts.map((completeProduct) => (
                    <article className="complete-product" key={`${completeProduct.id}-${completeProduct.name}`}>
                      <Link className="complete-product__link" to={`/product-detail?id=${encodeURIComponent(completeProduct.id)}`}>
                        {completeProduct.image ? (
                          <img
                            src={completeProduct.image}
                            alt={`${completeProduct.brand} ${completeProduct.name}`}
                          />
                        ) : (
                          <div className="complete-image-empty">이미지 준비중</div>
                        )}
                        <div>
                          <div className="complete-brand">{completeProduct.brand}</div>
                          <div className="complete-name">{completeProduct.name}</div>
                          <div className="complete-meta">
                            {completeProduct.option ? <span>{completeProduct.option}</span> : null}
                            <span>수량 {completeProduct.quantity ?? 1}개</span>
                            {completeProduct.price ? <span>{formatWon(completeProduct.price)}</span> : null}
                          </div>
                        </div>
                      </Link>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>

            <div className="complete-point-note">
              <span aria-hidden="true">✨</span>
              <span>결제 후 최대 {expectedPointAmount.toLocaleString("ko-KR")}원 적립 예정</span>
            </div>

            <div className="complete-actions">
              <Link className="complete-btn" to={`/mypage/orders/${displayOrderNo}`}>주문 상세보기</Link>
              <a className="complete-btn primary" href="/">쇼핑 계속하기</a>
            </div>
          </section>
        </section>
      </main>
    </>
  );
}

export default PaymentCompletePage;
