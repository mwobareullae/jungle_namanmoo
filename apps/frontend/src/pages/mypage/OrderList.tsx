import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getProductImageUrl } from "../../lib/imageUrls";
import { getOrders } from "../../lib/orderApi";
import type { OrderListItem } from "../../types/order";
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

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
};

export default function OrderList() {
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const loadOrders = useCallback(async (cursor?: string | null) => {
    const isFirstPage = !cursor;
    if (isFirstPage) {
      setIsLoading(true);
    } else {
      setIsLoadingMore(true);
    }
    setErrorMessage("");

    try {
      const response = await getOrders({ limit: 20, cursor });
      setOrders((current) => (isFirstPage ? response.items : [...current, ...response.items]));
      setNextCursor(response.next_cursor ?? null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "주문내역을 불러오지 못했습니다.");
      if (isFirstPage) {
        setOrders([]);
        setNextCursor(null);
      }
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void loadOrders();
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [loadOrders]);

  return (
    <MyPageLayout activePath="/mypage/orders">
      <PageTitle title="주문내역" />
      <section style={styles.card} aria-label="주문내역 목록">
        {isLoading ? (
          <div style={styles.stateBox}>주문내역을 불러오는 중입니다.</div>
        ) : errorMessage ? (
          <div style={styles.stateBox} role="alert">
            <strong style={styles.stateTitle}>주문내역을 불러오지 못했어요</strong>
            <p style={styles.stateText}>{errorMessage}</p>
            <button type="button" style={styles.retryButton} onClick={() => void loadOrders()}>
              다시 불러오기
            </button>
          </div>
        ) : orders.length === 0 ? (
          <div style={styles.stateBox}>
            <strong style={styles.stateTitle}>아직 주문내역이 없어요</strong>
            <p style={styles.stateText}>추천받은 상품을 장바구니에 담고 첫 주문을 진행해보세요.</p>
            <Link to="/" style={styles.primaryLink}>추천 상품 보러가기</Link>
          </div>
        ) : (
          <>
            <div style={styles.list}>
              {orders.map((order) => {
                const thumbnailUrl = getProductImageUrl(order.thumbnail_storage_key, "w400");
                return (
                  <article style={styles.item} key={order.order_code}>
                    <div style={styles.thumbnail}>
                      {thumbnailUrl ? (
                        <img src={thumbnailUrl} alt="" style={styles.thumbnailImage} />
                      ) : (
                        <span style={styles.thumbnailEmpty}>이미지 준비중</span>
                      )}
                    </div>
                    <div style={styles.itemBody}>
                      <div style={styles.itemMeta}>
                        <span>{formatDate(order.ordered_at)}</span>
                        <span>{order.order_code}</span>
                      </div>
                      <h2 style={styles.itemTitle}>{order.title}</h2>
                      <p style={styles.itemDescription}>
                        상품 {order.item_count}개 · {statusLabelMap[order.status] ?? order.status}
                      </p>
                    </div>
                    <div style={styles.itemAside}>
                      <strong style={styles.price}>{formatWon(order.total)}</strong>
                      <Link
                        to={`/mypage/orders/${encodeURIComponent(order.order_code)}`}
                        style={styles.detailLink}
                      >
                        상세보기
                      </Link>
                    </div>
                  </article>
                );
              })}
            </div>
            {nextCursor ? (
              <button
                type="button"
                style={styles.moreButton}
                onClick={() => void loadOrders(nextCursor)}
                disabled={isLoadingMore}
              >
                {isLoadingMore ? "불러오는 중" : "더 보기"}
              </button>
            ) : null}
          </>
        )}
      </section>
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  card: {
    border: "1px solid #eeeeee",
    borderRadius: 18,
    background: "#ffffff",
    overflow: "hidden"
  },
  stateBox: {
    display: "grid",
    gap: 12,
    justifyItems: "center",
    padding: "72px 24px",
    color: "#6b7280",
    fontSize: 15,
    textAlign: "center"
  },
  stateTitle: {
    color: "#1a1a1a",
    fontSize: 20,
    fontWeight: 800
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
    background: "#ffffff",
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer"
  },
  primaryLink: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    padding: "0 20px",
    borderRadius: 12,
    background: "#0C1117",
    color: "#ffffff",
    fontSize: 14,
    fontWeight: 800,
    textDecoration: "none"
  },
  list: {
    display: "grid"
  },
  item: {
    display: "grid",
    gridTemplateColumns: "88px minmax(0, 1fr) auto",
    gap: 18,
    alignItems: "center",
    padding: "22px 24px",
    borderBottom: "1px solid #eeeeee"
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
  itemMeta: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 8,
    color: "#9ca3af",
    fontSize: 12,
    fontWeight: 700
  },
  itemTitle: {
    margin: 0,
    color: "#1a1a1a",
    fontSize: 17,
    fontWeight: 800,
    lineHeight: 1.45
  },
  itemDescription: {
    margin: "8px 0 0",
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 700
  },
  itemAside: {
    display: "grid",
    gap: 12,
    justifyItems: "end"
  },
  price: {
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 900
  },
  detailLink: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 36,
    padding: "0 14px",
    border: "1px solid #dddddd",
    borderRadius: 10,
    color: "#1a1a1a",
    fontSize: 13,
    fontWeight: 800,
    textDecoration: "none"
  },
  moreButton: {
    width: "calc(100% - 48px)",
    minHeight: 46,
    margin: "20px 24px 24px",
    border: "1px solid #dddddd",
    borderRadius: 12,
    background: "#ffffff",
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 800,
    cursor: "pointer"
  }
};
