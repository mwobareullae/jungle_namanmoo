import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
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
  CANCEL_REQUESTED: "취소요청",
  REFUND_REQUESTED: "환불요청",
  REFUNDED: "환불완료",
  RETURN_REQUESTED: "반품요청",
  RETURNED: "반품완료",
  EXCHANGE_REQUESTED: "교환요청",
  EXCHANGED: "교환완료"
};

const statusFilterItems = [
  { value: null, label: "전체" },
  { value: "PENDING_PAYMENT", label: "주문접수" },
  { value: "PAID", label: "결제완료" },
  { value: "PREPARING_SHIPMENT", label: "배송준비중" },
  { value: "SHIPPED", label: "배송중" },
  { value: "DELIVERED", label: "배송완료" }
] as const;

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;
const removeAdditionalItemSuffix = (title: string) => title.replace(/\s+and\s+\d+\s+more\s*$/i, "").trim();

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
};

export default function OrderList() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const loadOrders = useCallback(async (cursor?: string | null) => {
    const isFirstPage = !cursor;
    if (isFirstPage) {
      setIsLoading(true);
    } else {
      setIsLoadingMore(true);
    }
    setErrorMessage("");

    try {
      const response = await getOrders({ limit: 15, cursor, status: statusFilter });
      setOrders((current) => (isFirstPage ? response.items : [...current, ...response.items]));
      setNextCursor(response.next_cursor ?? null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "주문/배송 조회를 불러오지 못했습니다.");
      if (isFirstPage) {
        setOrders([]);
        setNextCursor(null);
      }
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void loadOrders();
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [loadOrders]);

  return (
    <MyPageLayout activePath="/mypage/orders">
      <PageTitle title="주문/배송 조회" />
      <section style={styles.card} aria-label="주문/배송 조회 목록">
        <div aria-label="주문 상태 필터" role="tablist" style={styles.statusFilters}>
          {statusFilterItems.map((item) => (
            <button
              aria-selected={statusFilter === item.value}
              className="mypage-order-status-filter"
              key={item.value ?? "all"}
              onMouseDown={(event) => event.currentTarget.blur()}
              onClick={() => setStatusFilter(item.value)}
              role="tab"
              style={{
                ...styles.statusFilter,
                ...(statusFilter === item.value ? styles.statusFilterActive : {}),
                outline: "none",
                boxShadow: "none"
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        {isLoading ? (
          <div style={styles.stateBox}>주문/배송 조회를 불러오는 중입니다.</div>
        ) : errorMessage ? (
          <div style={styles.stateBox} role="alert">
            <strong style={styles.stateTitle}>주문/배송 조회를 불러오지 못했어요</strong>
            <p style={styles.stateText}>{errorMessage}</p>
            <button
              className="bg-white hover:bg-[#FAFAFA]"
              onClick={() => void loadOrders()}
              style={styles.retryButton}
              type="button"
            >
              다시 불러오기
            </button>
          </div>
        ) : orders.length === 0 ? (
          <div style={styles.stateBox}>
            <strong style={styles.stateTitle}>아직 주문/배송 조회 내역이 없어요</strong>
            <p style={styles.stateText}>추천받은 상품을 장바구니에 담고 첫 주문을 진행해보세요.</p>
            <Link className="bg-[#0C1117] hover:bg-[#1A1A1A]" style={styles.primaryLink} to="/">
              추천 상품 보러가기
            </Link>
          </div>
        ) : (
          <>
            <div style={styles.list}>
              {orders.map((order) => {
                const thumbnailUrl = getProductImageUrl(order.thumbnail_storage_key, "w400");
                const displayTitle = removeAdditionalItemSuffix(order.title);
                return (
                  <article
                    aria-label={`${displayTitle} 주문 상세 보기`}
                    className="mypage-order-card"
                    key={order.order_code}
                    onMouseDown={(event) => event.currentTarget.blur()}
                    onClick={() => navigate(`/mypage/orders/${encodeURIComponent(order.order_code)}`)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        navigate(`/mypage/orders/${encodeURIComponent(order.order_code)}`);
                      }
                    }}
                    role="link"
                    style={styles.orderCard}
                    tabIndex={0}
                  >
                    <div style={styles.orderCardMenu} aria-hidden="true">⋮</div>
                    <div style={styles.orderCardMain}>
                    <div style={styles.thumbnail}>
                      {thumbnailUrl ? (
                        <img src={thumbnailUrl} alt="" style={styles.thumbnailImage} />
                      ) : (
                        <span style={styles.thumbnailEmpty}>N</span>
                      )}
                    </div>
                    <div style={styles.itemBody}>
                    <div style={styles.orderCardHeader}>
                      <strong style={styles.orderStatus}>{statusLabelMap[order.status] ?? order.status}</strong>
                    </div>
                    <Link
                      className="no-underline hover:text-[#555555]"
                      style={styles.itemTitleLink}
                      to={`/mypage/orders/${encodeURIComponent(order.order_code)}`}
                    >
                      <h2 style={styles.itemTitle}>{displayTitle}</h2>
                      {order.item_count > 1 ? (
                        <span style={styles.itemCountLabel}>
                          포함 <strong style={styles.itemCountAccent}>총 {order.item_count}건</strong>
                        </span>
                      ) : null}
                      <svg
                        aria-hidden="true"
                        fill="none"
                        height="14"
                        role="presentation"
                        style={styles.itemArrow}
                        viewBox="0 0 256 256"
                        width="14"
                      >
                        <path
                          d="m96 48 80 80-80 80"
                          stroke="currentColor"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="16"
                        />
                      </svg>
                    </Link>
                    <div style={styles.itemMetaLine}>
                      <strong style={styles.price}>{formatWon(order.total)}</strong>
                      <span style={styles.itemMetaDivider}>|</span>
                      <span style={styles.paymentDate}>{formatDate(order.ordered_at)} 결제</span>
                    </div>
                    </div>
                    </div>
                  </article>
                );
              })}
            </div>
            <div style={styles.paginationBar}>
              <span aria-current="page" style={styles.currentPage}>1</span>
              {nextCursor ? (
              <button
                className="bg-white text-[#1a1a1a] hover:bg-[#FAFAFA] disabled:cursor-not-allowed disabled:bg-[#F5F5F5] disabled:text-[#9CA3AF]"
                disabled={isLoadingMore}
                onClick={() => void loadOrders(nextCursor)}
                style={styles.moreButton}
                type="button"
              >
                {isLoadingMore ? "불러오는 중" : "더 보기"}
              </button>
              ) : null}
            </div>
          </>
        )}
      </section>
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  card: {
    background: "transparent"
  },
  statusFilters: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 20
  },
  statusFilter: {
    minHeight: 40,
    padding: "0 18px",
    border: "1px solid #eeeeee",
    borderRadius: 999,
    background: "#f5f5f5",
    color: "#555555",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer"
  },
  statusFilterActive: {
    borderColor: "#1a1a1a",
    background: "#1a1a1a",
    color: "#ffffff",
    fontWeight: 600
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
  primaryLink: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    padding: "0 20px",
    borderRadius: 12,
    color: "#ffffff",
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none"
  },
  list: {
    display: "grid",
    gap: 14
  },
  orderCard: {
    position: "relative",
    padding: "26px 28px",
    border: "1px solid #edf0f2",
    borderRadius: 18,
    background: "#ffffff"
  },
  orderCardMenu: {
    position: "absolute",
    top: 24,
    right: 28,
    color: "#9ca3af",
    fontSize: 24,
    lineHeight: 1
  },
  orderCardHeader: {
    display: "flex",
    alignItems: "baseline",
    marginBottom: 10
  },
  orderStatus: {
    color: "#1a1a1a",
    fontSize: 15,
    fontWeight: 600
  },
  orderCardMain: {
    display: "grid",
    gridTemplateColumns: "92px minmax(0, 1fr) auto",
    gap: 16,
    alignItems: "center"
  },
  thumbnail: {
    width: 92,
    height: 92,
    borderRadius: 6,
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
    fontWeight: 500
  },
  itemTitle: {
    margin: 0,
    color: "#1a1a1a",
    fontSize: 15,
    fontWeight: 500,
    lineHeight: 1.35
  },
  itemTitleLink: {
    display: "inline-flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 6,
    maxWidth: "100%",
    color: "#1a1a1a"
  },
  itemCountLabel: {
    color: "#1a1a1a",
    fontSize: 15,
    fontWeight: 500
  },
  itemCountAccent: {
    color: "#2aa6d1",
    fontSize: 15,
    fontWeight: 600
  },
  itemArrow: {
    display: "block",
    flexShrink: 0
  },
  itemMetaLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 8,
    marginTop: 8,
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: 500
  },
  itemMetaDivider: {
    color: "#d5d9dd",
    fontSize: 13,
    fontWeight: 300
  },
  paymentDate: {
    fontSize: 13,
    fontWeight: 400
  },
  itemDescription: {
    margin: "8px 0 0",
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 500
  },
  itemAside: {
    display: "grid",
    gap: 12,
    justifyItems: "end"
  },
  price: {
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 700
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
    fontWeight: 600,
    textDecoration: "none"
  },
  moreButton: {
    minWidth: 120,
    minHeight: 46,
    margin: 0,
    border: "1px solid #dddddd",
    borderRadius: 12,
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer"
  },
  paginationBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    marginTop: 20
  },
  currentPage: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 36,
    height: 36,
    borderRadius: 10,
    background: "#1a1a1a",
    color: "#ffffff",
    fontSize: 14,
    fontWeight: 600
  }
};
