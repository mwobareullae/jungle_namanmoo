import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import CancelReasonForm from "../../components/order/CancelReasonForm";
import type { CancelReasonDraft } from "../../components/order/cancelReasonOptions";
import ActivityToast from "../../components/ui/ActivityToast";
import ConfirmModal from "../../components/ui/ConfirmModal";
import Skeleton from "../../components/ui/Skeleton";
import { addCartItem } from "../../lib/cartApi";
import { getProductImageUrl } from "../../lib/imageUrls";
import { cancelOrder, getOrderDetail, getOrders } from "../../lib/orderApi";
import type { OrderDetailItem, OrderListItem } from "../../types/order";
import { useActivityToast } from "../../hooks/useActivityToast";
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

const orderPeriodItems = [
  { value: 1, label: "최근 1개월" },
  { value: 3, label: "최근 3개월" },
  { value: 6, label: "최근 6개월" },
  { value: 12, label: "최근 1년" }
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

function OrderListSkeleton() {
  return (
    <div style={styles.skeletonList}>
      {Array.from({ length: 10 }, (_, index) => (
        <div key={index} style={styles.skeletonCard}>
          <Skeleton style={styles.skeletonImage} />
          <div style={styles.skeletonBody}>
            <Skeleton style={styles.skeletonStatus} />
            <Skeleton style={styles.skeletonTitle} />
            <Skeleton style={styles.skeletonMeta} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function OrderList() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [periodMonths, setPeriodMonths] = useState(12);
  const [expandedOrderCodes, setExpandedOrderCodes] = useState<Set<string>>(() => new Set());
  const [orderDetailItems, setOrderDetailItems] = useState<Record<string, OrderDetailItem[]>>({});
  const [loadingDetailOrderCodes, setLoadingDetailOrderCodes] = useState<Set<string>>(() => new Set());
  const { message: toastMessage, showToast } = useActivityToast();
  const [deleteTargetOrderCode, setDeleteTargetOrderCode] = useState<string | null>(null);
  const [cancelTargetOrder, setCancelTargetOrder] = useState<OrderListItem | null>(null);
  const [cancelReasonDraft, setCancelReasonDraft] = useState<CancelReasonDraft | null>(null);
  const [isCancelReasonFormOpen, setIsCancelReasonFormOpen] = useState(false);
  const [isCancelConfirmOpen, setIsCancelConfirmOpen] = useState(false);
  const [cancelSubmittedOrderCode, setCancelSubmittedOrderCode] = useState<string | null>(null);
  const [isCanceling, setIsCanceling] = useState(false);
  const [cancelErrorMessage, setCancelErrorMessage] = useState("");
  const filteredOrders = useMemo(() => {
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - periodMonths);
    return orders.filter((order) => {
      const orderedAt = new Date(order.ordered_at);
      return Number.isNaN(orderedAt.getTime()) || orderedAt >= cutoff;
    });
  }, [orders, periodMonths]);

  const loadOrders = useCallback(async (cursor?: string | null) => {
    const startedAt = Date.now();
    const isFirstPage = !cursor;
    if (isFirstPage) {
      setIsLoading(true);
    } else {
      setIsLoadingMore(true);
    }
    setErrorMessage("");

    try {
      const response = await getOrders({ limit: 10, cursor, status: statusFilter });
      setOrders((current) => (isFirstPage ? response.items : [...current, ...response.items]));
      setNextCursor(response.next_cursor ?? null);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "주문/배송내역을 불러오지 못했습니다.");
      if (isFirstPage) {
        setOrders([]);
        setNextCursor(null);
      }
    } finally {
      const finishLoading = () => setIsLoading(false);
      const remaining = Math.max(0, 600 - (Date.now() - startedAt));
      if (isFirstPage && remaining > 0) window.setTimeout(finishLoading, remaining);
      else finishLoading();
      setIsLoadingMore(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void loadOrders();
    }, 0);

    return () => window.clearTimeout(timerId);
  }, [loadOrders]);

  const toggleOrderItems = async (order: OrderListItem) => {
    const isExpanded = expandedOrderCodes.has(order.order_code);
    if (isExpanded) {
      setExpandedOrderCodes((current) => {
        const next = new Set(current);
        next.delete(order.order_code);
        return next;
      });
      return;
    }

    if (!orderDetailItems[order.order_code]) {
      setLoadingDetailOrderCodes((current) => new Set(current).add(order.order_code));
      try {
        const detail = await getOrderDetail(order.order_code);
        setOrderDetailItems((current) => ({ ...current, [order.order_code]: detail.items }));
      } finally {
        setLoadingDetailOrderCodes((current) => {
          const next = new Set(current);
          next.delete(order.order_code);
          return next;
        });
      }
    }

    setExpandedOrderCodes((current) => new Set(current).add(order.order_code));
  };

  const handleReview = (orderCode: string) => navigate(`/mypage/reviews?order_code=${encodeURIComponent(orderCode)}`);
  const handleUnavailableAction = () => showToast("준비 중입니다.");
  const handleDeleteConfirm = () => {
    setDeleteTargetOrderCode(null);
    showToast("주문 내역 삭제 기능은 준비 중입니다.");
  };

  const canCancelOrder = (order: OrderListItem) => order.status === "PENDING_PAYMENT" || order.status === "PAID";

  const openCancelForm = (order: OrderListItem) => {
    setCancelTargetOrder(order);
    setCancelReasonDraft(null);
    setCancelSubmittedOrderCode(null);
    setCancelErrorMessage("");
    if (order.status === "PENDING_PAYMENT") {
      setIsCancelConfirmOpen(true);
    } else {
      setIsCancelReasonFormOpen(true);
    }
  };

  const handleCancelReasonSubmit = (draft: CancelReasonDraft) => {
    setCancelReasonDraft(draft);
    setIsCancelReasonFormOpen(false);
    setIsCancelConfirmOpen(true);
  };

  const handleCancelConfirm = async () => {
    if (!cancelTargetOrder || isCanceling) return;
    if (cancelTargetOrder.status === "PAID" && !cancelReasonDraft) return;
    setIsCanceling(true);
    setCancelErrorMessage("");
    try {
      await cancelOrder(
        cancelTargetOrder.order_code,
        cancelTargetOrder.status === "PAID" && cancelReasonDraft
          ? { reason_code: cancelReasonDraft.reasonCode, reason_detail: cancelReasonDraft.detail || null }
          : undefined
      );
      setIsCancelConfirmOpen(false);
      setCancelSubmittedOrderCode(cancelTargetOrder.order_code);
      await loadOrders();
    } catch (error) {
      setCancelErrorMessage(error instanceof Error ? error.message : "주문 취소에 실패했습니다.");
    } finally {
      setIsCanceling(false);
    }
  };

  const handleReorder = async (order: OrderListItem) => {
    try {
      const detail = await getOrderDetail(order.order_code);
      await Promise.all(
        detail.items.map((item) => addCartItem({ product_id: item.product_id, quantity: item.quantity }))
      );
      navigate("/cart");
    } catch {
      navigate(`/mypage/orders/${encodeURIComponent(order.order_code)}`);
    }
  };

  const handleItemReorder = async (item: OrderDetailItem) => {
    try {
      await addCartItem({ product_id: item.product_id, quantity: item.quantity });
      navigate("/cart");
    } catch {
      showToast("다시 담기에 실패했습니다.");
    }
  };

  const handleItemBuyNow = async (item: OrderDetailItem) => {
    try {
      const cart = await addCartItem({ product_id: item.product_id, quantity: item.quantity });
      const cartItem = cart.items.find((cartItem) => cartItem.product_id === item.product_id);
      if (!cartItem) throw new Error("장바구니 상품을 찾지 못했습니다.");
      navigate(`/checkout?cart_item_ids=${cartItem.id}`);
    } catch {
      showToast("바로 구매에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  const handleOrderBuyNow = async (order: OrderListItem) => {
    try {
      const detail = await getOrderDetail(order.order_code);
      const item = detail.items[0];
      if (!item) throw new Error("주문 상품을 찾지 못했습니다.");
      await handleItemBuyNow(item);
    } catch {
      showToast("바로 구매에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  return (
    <MyPageLayout activePath="/mypage/orders">
      <PageTitle title="주문/배송내역" />
      <section style={styles.card} aria-label="주문/배송내역 목록">
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
        <div aria-label="주문 조회 기간" role="tablist" style={styles.statusFilters}>
          {orderPeriodItems.map((item) => (
            <button
              aria-selected={periodMonths === item.value}
              key={item.value}
              onClick={() => setPeriodMonths(item.value)}
              role="tab"
              style={{
                ...styles.statusFilter,
                ...(periodMonths === item.value ? styles.statusFilterActive : {})
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        {isLoading ? (
          <OrderListSkeleton />
        ) : errorMessage ? (
          <div style={styles.stateBox} role="alert">
            <strong style={styles.stateTitle}>주문/배송내역을 불러오지 못했어요</strong>
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
        ) : filteredOrders.length === 0 ? (
          <div style={styles.stateBox}>
            <strong style={styles.stateTitle}>아직 주문/배송내역이 없어요</strong>
            <p style={styles.stateText}>추천받은 상품을 장바구니에 담고 첫 주문을 진행해보세요.</p>
            <Link className="bg-[#0C1117] hover:bg-[#1A1A1A]" style={styles.primaryLink} to="/">
              추천 상품 보러가기
            </Link>
          </div>
        ) : (
          <>
            <div style={styles.list}>
              {filteredOrders.map((order) => {
                const thumbnailUrl = getProductImageUrl(order.thumbnail_storage_key, "w400");
                const displayTitle = removeAdditionalItemSuffix(order.title);
                const isCompletedOrder = order.status === "PAID" || order.status === "DELIVERED";
                const canWriteReview = order.status === "DELIVERED";
                const isShippingOrder = order.status === "PREPARING_SHIPMENT" || order.status === "SHIPPED";
                const isExpiredOrder = order.status === "EXPIRED";
                const isCancelableOrder = canCancelOrder(order);
                const orderActionCount = 1
                  + (canWriteReview || isShippingOrder ? 1 : 0)
                  + (isCompletedOrder || isExpiredOrder ? 1 : 0);
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
                    {!(order.item_count > 1 && expandedOrderCodes.has(order.order_code)) ? (
                      <div style={styles.orderCardControls}>
                        {isCancelableOrder ? (
                          <button
                            className="bg-white hover:bg-[#FAFAFA]"
                            onClick={(event) => {
                              event.stopPropagation();
                              openCancelForm(order);
                            }}
                            style={styles.orderCardCancel}
                            type="button"
                          >
                            주문 취소
                          </button>
                        ) : null}
                        <button
                          aria-label="주문 내역 삭제"
                          className="bg-transparent hover:bg-[#FAFAFA]"
                          onClick={(event) => {
                            event.stopPropagation();
                            setDeleteTargetOrderCode(order.order_code);
                          }}
                          style={styles.orderCardMenu}
                          type="button"
                        >
                          <svg fill="none" height="21" viewBox="0 0 32 32" width="21">
                            <path d="m9 9 14 14M23 9 9 23" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
                          </svg>
                        </button>
                      </div>
                    ) : null}
                    {!(order.item_count > 1 && expandedOrderCodes.has(order.order_code)) ? (
                    <div style={styles.orderCardMain}>
                    <div style={styles.thumbnail}>
                      {thumbnailUrl ? (
                        <img src={thumbnailUrl} alt="" style={styles.thumbnailImage} />
                      ) : (
                        <span style={styles.thumbnailEmpty}>N</span>
                      )}
                      {order.item_count > 1 ? (
                        <span style={styles.itemCountBadge}>{order.item_count}</span>
                      ) : null}
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
                    ) : null}
                    {order.item_count > 1 ? (
                      <>
                        {expandedOrderCodes.has(order.order_code) ? (
                          <div style={styles.detailItemList}>
                            {(orderDetailItems[order.order_code] ?? []).map((item, index) => (
                              <div
                                key={item.id}
                                style={{
                                  ...styles.detailItemCard,
                                  ...(index > 0 ? styles.detailItemCardSeparated : {})
                                }}
                              >
                                <button
                                  aria-label="상품 닫기"
                                  className="bg-transparent hover:bg-[#FAFAFA]"
                                  onClick={(event) => event.stopPropagation()}
                                  style={{
                                    ...styles.detailItemClose,
                                    ...(index === 0 ? styles.detailItemCloseFirst : {})
                                  }}
                                  type="button"
                                >
                                  <svg fill="none" height="21" viewBox="0 0 32 32" width="21">
                                    <path d="m9 9 14 14M23 9 9 23" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
                                  </svg>
                                </button>
                                <div style={styles.detailItemMain}>
                                <div style={styles.detailItemThumbnail}>
                                  {getProductImageUrl(item.thumbnail_storage_key, "w400") ? (
                                    <img
                                      alt=""
                                      src={getProductImageUrl(item.thumbnail_storage_key, "w400")}
                                      style={styles.thumbnailImage}
                                    />
                                  ) : null}
                                </div>
                                <div style={styles.detailItemBody}>
                                  <strong style={styles.detailItemStatus}>{statusLabelMap[order.status] ?? order.status}</strong>
                                  <span style={styles.detailItemName}>{item.product_name}</span>
                                  <div style={styles.detailItemMeta}>
                                    <strong style={styles.detailItemPrice}>{formatWon(item.line_total)}</strong>
                                    <span>{item.quantity}개</span>
                                  </div>
                                </div>
                                </div>
                                <div style={styles.detailItemActions}>
                                  <button
                                    className="mypage-order-action-button mypage-order-action-button--neutral bg-white"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void handleItemReorder(item);
                                    }}
                                    style={styles.reorderButton}
                                    type="button"
                                  >
                                    다시 담기
                                  </button>
                                  <button
                                    className="mypage-order-action-button mypage-order-action-button--neutral bg-white"
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void handleItemBuyNow(item);
                                    }}
                                    style={styles.reorderButton}
                                    type="button"
                                  >
                                    바로 구매하기
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                        <button
                          className={expandedOrderCodes.has(order.order_code) ? "mypage-expand-button-expanded bg-white hover:bg-[#FAFAFA]" : "bg-white hover:bg-[#FAFAFA]"}
                          onClick={(event) => {
                            event.stopPropagation();
                            void toggleOrderItems(order);
                          }}
                          style={styles.expandButton}
                          type="button"
                        >
                          {loadingDetailOrderCodes.has(order.order_code)
                            ? "불러오는 중"
                            : expandedOrderCodes.has(order.order_code)
                              ? `총 ${order.item_count}건 접기`
                              : `총 ${order.item_count}건 펼쳐보기`}
                        </button>
                      </>
                    ) : (
                      <div
                        style={{
                          ...styles.orderActions,
                          ...(orderActionCount === 1 ? styles.orderActionsSingle : {}),
                          ...(canWriteReview ? styles.orderActionsThree : {})
                        }}
                      >
                        {canWriteReview ? (
                          <button
                            className="mypage-order-action-button mypage-order-action-button--accent bg-white"
                            onClick={(event) => {
                              event.stopPropagation();
                              handleReview(order.order_code);
                            }}
                            style={styles.reviewButton}
                            type="button"
                          >
                            리뷰쓰기
                          </button>
                        ) : isShippingOrder ? (
                          <button
                            className="mypage-order-action-button mypage-order-action-button--accent bg-white"
                            onClick={(event) => {
                              event.stopPropagation();
                              handleUnavailableAction();
                            }}
                            style={styles.reviewButton}
                            type="button"
                          >
                            배송 조회
                          </button>
                        ) : null}
                        <button
                          className="mypage-order-action-button mypage-order-action-button--neutral bg-white"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleReorder(order);
                          }}
                          style={styles.reorderButton}
                          type="button"
                        >
                          다시 담기
                        </button>
                        {isCompletedOrder || isExpiredOrder ? (
                          <button
                            className="mypage-order-action-button mypage-order-action-button--neutral bg-white"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleOrderBuyNow(order);
                            }}
                            style={styles.reorderButton}
                            type="button"
                          >
                            바로 구매하기
                          </button>
                        ) : null}
                      </div>
                    )}
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
      <CancelReasonForm
        onCancel={() => setIsCancelReasonFormOpen(false)}
        onSubmit={handleCancelReasonSubmit}
        open={isCancelReasonFormOpen}
        orderStatus={cancelTargetOrder?.status === "PAID" ? "PAID" : "PENDING_PAYMENT"}
        submitting={isCanceling}
      />
      <ConfirmModal
        cancelLabel="돌아가기"
        confirmLabel={isCanceling ? "처리 중" : cancelTargetOrder?.status === "PAID" ? "취소 요청" : "주문 취소"}
        message={
          cancelErrorMessage
            ? cancelErrorMessage
            : cancelReasonDraft && cancelTargetOrder
            ? `${cancelReasonDraft.optionLabel} 사유로 ${cancelTargetOrder.status === "PAID" ? "취소 요청을 접수" : "주문을 취소"}할까요?`
            : "결제 전 주문이라 즉시 취소됩니다. 진행할까요?"
        }
        onCancel={() => { if (!isCanceling) setIsCancelConfirmOpen(false); }}
        onConfirm={() => void handleCancelConfirm()}
        open={isCancelConfirmOpen}
        title="최종 확인"
      />
      {cancelSubmittedOrderCode ? (
        <p role="status" style={styles.cancelNotice}>
          취소 사유를 확인했습니다. 백엔드 계약이 확정되면 취소 요청 API와 연결됩니다.
        </p>
      ) : null}
      {cancelErrorMessage ? <p role="alert" style={styles.cancelError}>{cancelErrorMessage}</p> : null}
      <ActivityToast message={toastMessage} />
      <ConfirmModal
        compact
        message="함께 주문한 전체 상품의 주문/배송내역이 삭제되어 복구할 수 없습니다. 정말 삭제하시겠습니까?"
        onCancel={() => setDeleteTargetOrderCode(null)}
        onConfirm={handleDeleteConfirm}
        open={Boolean(deleteTargetOrderCode)}
      />
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
  skeletonList: {
    display: "grid",
    gap: 14
  },
  skeletonCard: {
    display: "grid",
    gridTemplateColumns: "92px minmax(0, 1fr)",
    gap: 16,
    minHeight: 144,
    padding: "26px 28px",
    border: "1px solid #edf0f2",
    borderRadius: 18
  },
  skeletonImage: {
    width: 92,
    height: 92,
    borderRadius: 8
  },
  skeletonBody: {
    display: "grid",
    alignContent: "center",
    gap: 10
  },
  skeletonStatus: {
    width: 80,
    height: 16,
    borderRadius: 5
  },
  skeletonTitle: {
    width: "min(70%, 420px)",
    height: 20,
    borderRadius: 5
  },
  skeletonMeta: {
    width: 180,
    height: 18,
    borderRadius: 5
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
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 0,
    border: 0,
    color: "#9ca3af",
    width: 21,
    height: 21,
    cursor: "pointer"
  },
  orderCardControls: {
    position: "absolute",
    top: 18,
    right: 24,
    display: "flex",
    alignItems: "center",
    gap: 10
  },
  orderCardCancel: {
    minHeight: 30,
    padding: "0 10px",
    border: "1px solid #d5d9dd",
    borderRadius: 8,
    color: "#6b7280",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer"
  },
  orderCardHeader: {
    display: "flex",
    alignItems: "baseline",
    marginBottom: 6
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
    position: "relative",
    width: 92,
    height: 92,
    borderRadius: 8,
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
  itemCountBadge: {
    position: "absolute",
    right: 0,
    bottom: 0,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 24,
    height: 24,
    borderRadius: "6px 0 0 0",
    background: "#9ca3af",
    color: "#ffffff",
    fontSize: 14,
    fontWeight: 700
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
  expandButton: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "100%",
    minHeight: 48,
    marginTop: 18,
    border: "1px solid #d9dde1",
    borderRadius: 10,
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 400,
    cursor: "pointer"
  },
  detailItemList: {
    display: "grid",
    marginTop: 0,
    marginLeft: -28,
    marginRight: -28,
    padding: 0,
    background: "transparent"
  },
  detailItemCard: {
    position: "relative",
    display: "grid",
    gap: 16,
    padding: "0 28px 26px"
  },
  detailItemCardSeparated: {
    borderTop: "2px dotted #e8edf0",
    paddingTop: 26
  },
  detailItemThumbnail: {
    width: 92,
    height: 92,
    borderRadius: 8,
    background: "#f7f8f9",
    overflow: "hidden"
  },
  detailItemMain: {
    display: "grid",
    gridTemplateColumns: "92px minmax(0, 1fr)",
    gap: 16,
    paddingRight: 28
  },
  detailItemClose: {
    position: "absolute",
    top: 20,
    right: 24,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 26,
    height: 26,
    padding: 0,
    border: 0,
    color: "#9ca3af",
    cursor: "pointer"
  },
  detailItemCloseFirst: {
    top: -6
  },
  detailItemBody: {
    display: "grid",
    alignContent: "center",
    gap: 6,
    minWidth: 0
  },
  detailItemStatus: {
    color: "#1a1a1a",
    fontSize: 15,
    fontWeight: 600
  },
  detailItemName: {
    overflow: "hidden",
    color: "#1a1a1a",
    fontSize: 15,
    fontWeight: 500,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  },
  detailItemMeta: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 500
  },
  detailItemPrice: {
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 700
  },
  detailItemActions: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 14,
    marginTop: 16
  },
  orderActions: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 14,
    marginTop: 18
  },
  orderActionsThree: {
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))"
  },
  orderActionsSingle: {
    gridTemplateColumns: "minmax(0, 1fr)"
  },
  reviewButton: {
    minHeight: 48,
    border: "1px solid #2aa6d1",
    borderRadius: 10,
    color: "#2aa6d1",
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer"
  },
  reorderButton: {
    minHeight: 48,
    border: "1px solid #d5d9dd",
    borderRadius: 10,
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 400,
    cursor: "pointer"
  },
  cancelNotice: {
    margin: "14px 0 0",
    padding: "12px 14px",
    borderRadius: 10,
    background: "#f1fbfe",
    color: "#2f7188",
    fontSize: 14,
    lineHeight: 1.5
  },
  cancelError: {
    margin: "14px 0 0",
    color: "#c44747",
    fontSize: 14,
    lineHeight: 1.5
  },
  itemArrow: {
    display: "block",
    flexShrink: 0
  },
  itemMetaLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 8,
    marginTop: 6,
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
  },
};
