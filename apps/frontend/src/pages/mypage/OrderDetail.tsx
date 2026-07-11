import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getProductImageUrl } from "../../lib/imageUrls";
import { getOrderDetail } from "../../lib/orderApi";
import type { OrderDetailResponse } from "../../types/order";
import { MyPageLayout, PageTitle } from "./MyPageShell";

const statusLabelMap: Record<string, string> = {
  PENDING_PAYMENT: "주문접수",
  PAID: "결제완료",
  PAYMENT_FAILED: "결제실패",
  EXPIRED: "결제만료",
  CANCELED: "주문취소",
  PREPARING_SHIPMENT: "배송준비중",
  SHIPPED: "배송중",
  DELIVERED: "배송완료",
  CANCEL_REQUESTED: "취소요청"
};

const paymentProviderLabelMap: Record<string, string> = {
  MOCK: "mock 결제",
  TOSS: "토스페이먼츠",
  KAKAO_PAY: "카카오페이",
  NAVER_PAY: "네이버페이"
};

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;

const formatDateTime = (value?: string | null) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
};

const formatAddress = (order: OrderDetailResponse) => {
  const address = order.shipping_address;
  if (!address) return "배송지 정보가 없습니다.";
  return [address.address1, address.address2].filter(Boolean).join(" ");
};

const buildProductDetailPath = (item: OrderDetailResponse["items"][number]) => {
  const params = new URLSearchParams({ id: item.product_id });
  if (item.recommendation_id) {
    params.set("recommendation_id", item.recommendation_id);
  }
  return `/product-detail?${params.toString()}`;
};

export default function OrderDetail() {
  const { orderCode = "" } = useParams();
  const [order, setOrder] = useState<OrderDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const loadOrderDetail = useCallback(async () => {
    if (!orderCode) {
      setErrorMessage("주문번호가 없습니다.");
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setErrorMessage("");

    try {
      const response = await getOrderDetail(orderCode);
      setOrder(response);
    } catch (error) {
      setOrder(null);
      setErrorMessage(error instanceof Error ? error.message : "주문 상세를 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [orderCode]);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void loadOrderDetail();
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [loadOrderDetail]);

  return (
    <MyPageLayout activePath="/mypage/orders">
      <PageTitle
        rightSlot={
          <Link className="text-[#2aa6d1] hover:text-[#1A1A1A]" style={styles.backLink} to="/mypage/orders">
            목록으로
          </Link>
        }
        title="주문 상세"
      />

      {isLoading ? (
        <section style={styles.stateCard}>주문 상세를 불러오는 중입니다.</section>
      ) : errorMessage ? (
        <section style={styles.stateCard} role="alert">
          <strong style={styles.stateTitle}>주문 상세를 불러오지 못했어요</strong>
          <p style={styles.stateText}>{errorMessage}</p>
          <button
            className="bg-white hover:bg-[#FAFAFA]"
            onClick={() => void loadOrderDetail()}
            style={styles.retryButton}
            type="button"
          >
            다시 불러오기
          </button>
        </section>
      ) : order ? (
        <div style={styles.detailGrid}>
          <section style={styles.card} aria-labelledby="orderInfoTitle">
            <h2 id="orderInfoTitle" style={styles.cardTitle}>주문 정보</h2>
            <div style={styles.infoRows}>
              <InfoRow label="주문번호" value={order.order_code} />
              <InfoRow label="주문상태" value={statusLabelMap[order.status] ?? order.status} accent />
              <InfoRow label="주문일시" value={formatDateTime(order.ordered_at)} />
              <InfoRow label="결제일시" value={formatDateTime(order.paid_at)} />
            </div>
          </section>

          <section style={styles.card} aria-labelledby="paymentInfoTitle">
            <h2 id="paymentInfoTitle" style={styles.cardTitle}>결제 정보</h2>
            <div style={styles.infoRows}>
              <InfoRow label="상품금액" value={formatWon(order.subtotal)} />
              <InfoRow label="배송비" value={formatWon(order.shipping_fee)} />
              <InfoRow label="할인금액" value={formatWon(order.discount_total)} />
              <InfoRow label="총 결제금액" value={formatWon(order.total)} strong />
              <InfoRow
                label="결제수단"
                value={paymentProviderLabelMap[order.payment.provider] ?? order.payment.provider}
              />
              <InfoRow label="결제상태" value={order.payment.status} />
            </div>
          </section>

          <section style={styles.card} aria-labelledby="shippingInfoTitle">
            <h2 id="shippingInfoTitle" style={styles.cardTitle}>배송 정보</h2>
            <div style={styles.infoRows}>
              <InfoRow label="받는 분" value={order.shipping_address?.recipient_name ?? "-"} />
              <InfoRow label="연락처" value={order.shipping_address?.phone ?? "-"} />
              <InfoRow label="주소" value={formatAddress(order)} />
              <InfoRow label="요청사항" value={order.shipping_address?.delivery_memo || "-"} />
            </div>
          </section>

          <section style={styles.card} aria-labelledby="orderedItemsTitle">
            <div style={styles.cardHeader}>
              <h2 id="orderedItemsTitle" style={styles.cardTitle}>주문 상품</h2>
              <span style={styles.cardCount}>상품 {order.items.length}개</span>
            </div>
            <div style={styles.itemList}>
              {order.items.map((item) => {
                const thumbnailUrl = getProductImageUrl(item.thumbnail_storage_key, "w400");
                const productDetailPath = buildProductDetailPath(item);
                return (
                  <Link
                    aria-label={`${item.product_name} 상품 상세 보기`}
                    className="hover:bg-[#FAFAFA]"
                    key={item.id}
                    style={styles.itemLink}
                    to={productDetailPath}
                  >
                    <article style={styles.item}>
                    <div style={styles.thumbnail}>
                      {thumbnailUrl ? (
                        <img src={thumbnailUrl} alt="" style={styles.thumbnailImage} />
                      ) : (
                        <span style={styles.thumbnailEmpty}>이미지 준비중</span>
                      )}
                    </div>
                    <div style={styles.itemBody}>
                      <p style={styles.brand}>{item.brand_name}</p>
                      <h3 style={styles.itemTitle}>{item.product_name}</h3>
                      <p style={styles.itemMeta}>
                        {item.seller_name} · 수량 {item.quantity}개 · {item.status}
                      </p>
                    </div>
                    <strong style={styles.itemPrice}>{formatWon(item.line_total)}</strong>
                    </article>
                  </Link>
                );
              })}
            </div>
          </section>
        </div>
      ) : null}
    </MyPageLayout>
  );
}

function InfoRow({
  accent = false,
  label,
  strong = false,
  value
}: {
  accent?: boolean;
  label: string;
  strong?: boolean;
  value: string;
}) {
  return (
    <div style={styles.infoRow}>
      <span style={styles.infoLabel}>{label}</span>
      <strong style={{ ...styles.infoValue, ...(accent ? styles.infoValueAccent : {}), ...(strong ? styles.infoValueStrong : {}) }}>
        {value}
      </strong>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  backLink: {
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none"
  },
  stateCard: {
    display: "grid",
    gap: 12,
    justifyItems: "center",
    padding: "72px 24px",
    border: "1px solid #eeeeee",
    borderRadius: 18,
    background: "#ffffff",
    color: "#6b7280",
    fontSize: 15,
    textAlign: "center"
  },
  stateTitle: {
    color: "#1a1a1a",
    fontSize: 20,
    fontWeight: 700
  },
  stateText: {
    margin: 0,
    color: "#6b7280",
    fontSize: 14,
    lineHeight: 1.6
  },
  retryButton: {
    minHeight: 42,
    padding: "0 18px",
    border: "1px solid #dddddd",
    borderRadius: 10,
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer"
  },
  detailGrid: {
    display: "grid",
    gap: 18
  },
  card: {
    padding: 24,
    border: "1px solid #eeeeee",
    borderRadius: 18,
    background: "#ffffff"
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 18
  },
  cardTitle: {
    margin: 0,
    color: "#1a1a1a",
    fontSize: 20,
    fontWeight: 700,
    lineHeight: 1.35
  },
  cardCount: {
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 600
  },
  infoRows: {
    display: "grid",
    gap: 12,
    marginTop: 18
  },
  infoRow: {
    display: "grid",
    gridTemplateColumns: "120px minmax(0, 1fr)",
    gap: 16,
    alignItems: "start"
  },
  infoLabel: {
    color: "#6b7280",
    fontSize: 14,
    fontWeight: 600
  },
  infoValue: {
    minWidth: 0,
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 600,
    lineHeight: 1.45,
    overflowWrap: "anywhere"
  },
  infoValueAccent: {
    color: "#2aa6d1"
  },
  infoValueStrong: {
    fontSize: 17,
    fontWeight: 700
  },
  itemList: {
    display: "grid"
  },
  itemLink: {
    display: "block",
    color: "inherit",
    textDecoration: "none"
  },
  item: {
    display: "grid",
    gridTemplateColumns: "88px minmax(0, 1fr) auto",
    gap: 18,
    alignItems: "center",
    padding: "18px 0",
    borderTop: "1px solid #eeeeee"
  },
  thumbnail: {
    width: 88,
    height: 88,
    borderRadius: 14,
    background: "#f7f8f9",
    overflow: "hidden"
  },
  thumbnailImage: {
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "cover"
  },
  thumbnailEmpty: {
    display: "grid",
    placeItems: "center",
    width: "100%",
    height: "100%",
    color: "#9ca3af",
    fontSize: 12,
    fontWeight: 700,
    textAlign: "center"
  },
  itemBody: {
    minWidth: 0
  },
  brand: {
    margin: "0 0 5px",
    color: "#2aa6d1",
    fontSize: 13,
    fontWeight: 600
  },
  itemTitle: {
    margin: 0,
    color: "#1a1a1a",
    fontSize: 17,
    fontWeight: 700,
    lineHeight: 1.45
  },
  itemMeta: {
    margin: "8px 0 0",
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 500
  },
  itemPrice: {
    color: "#1a1a1a",
    fontSize: 17,
    fontWeight: 700
  }
};
