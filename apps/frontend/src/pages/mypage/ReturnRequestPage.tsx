import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { createOrderClaim, getClaimEligibility } from "../../lib/claimApi";
import { clearAgentClaimDraft, readAgentClaimDraft } from "../../lib/agentDrafts";
import { getOrderDetail } from "../../lib/orderApi";
import type {
  OrderClaimEligibilityResponse,
  OrderClaimResponse,
  OrderClaimType
} from "../../types/claim";
import type { OrderDetailResponse } from "../../types/order";
import { MyPageLayout, PageTitle } from "./MyPageShell";

type RequestType = OrderClaimType;

const requestTypeLabels: Record<RequestType, string> = {
  RETURN: "반품",
  EXCHANGE: "교환",
  REFUND: "환불"
};

const claimErrorMessages: Record<string, string> = {
  CLAIM_NOT_ELIGIBLE: "배송 완료된 주문만 신청할 수 있습니다.",
  CLAIM_WINDOW_EXPIRED: "반품·교환·환불 신청 기간이 지났습니다.",
  CLAIM_QUANTITY_EXCEEDED: "이미 신청했거나 신청 가능한 수량을 초과했습니다.",
  ORDER_ITEM_NOT_FOUND: "신청할 주문 상품을 찾지 못했습니다.",
  ORDER_NOT_FOUND: "주문 정보를 찾지 못했습니다."
};

const formatClaimWindow = (value?: string | null) => {
  if (!value) return null;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
};

function ReturnRequestPage() {
  const { orderCode = "" } = useParams();
  const [order, setOrder] = useState<OrderDetailResponse | null>(null);
  const [eligibility, setEligibility] = useState<OrderClaimEligibilityResponse | null>(null);
  const [selectedItemId, setSelectedItemId] = useState("");
  const [selectedQuantity, setSelectedQuantity] = useState(1);
  const [requestType, setRequestType] = useState<RequestType>("RETURN");
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [claimResult, setClaimResult] = useState<OrderClaimResponse | null>(null);

  useEffect(() => {
    if (!orderCode) return;
    const agentDraft = readAgentClaimDraft();
    Promise.all([getOrderDetail(orderCode), getClaimEligibility(orderCode)])
      .then(([response, claimEligibility]) => {
        setOrder(response);
        setEligibility(claimEligibility);
        const firstEligibleItem = claimEligibility.items.find((item) => item.claimable_quantity > 0);
        const draftItem = agentDraft?.order_code === orderCode
          ? claimEligibility.items.find((item) => (
            item.order_item_id === agentDraft.order_item_id && item.claimable_quantity > 0
          ))
          : null;
        setSelectedItemId(String(draftItem?.order_item_id ?? firstEligibleItem?.order_item_id ?? ""));
        if (agentDraft?.order_code === orderCode && draftItem && claimEligibility.eligible) {
          setRequestType(agentDraft.claim_type);
          setReason(agentDraft.reason_code);
          setDetail(agentDraft.reason_detail);
        }
        if (agentDraft?.order_code === orderCode) {
          clearAgentClaimDraft();
        }
      })
      .catch(() => setNotice("주문 정보를 불러오지 못했습니다."))
      .finally(() => setIsLoading(false));
  }, [orderCode]);

  const submitRequest = async (event: FormEvent) => {
    event.preventDefault();
    const itemId = Number(selectedItemId);
    const eligibleItem = eligibility?.items.find((item) => item.order_item_id === itemId);
    if (!order || !eligibleItem || eligibleItem.claimable_quantity < 1) {
      setNotice("신청 가능한 상품을 선택해 주세요.");
      return;
    }

    try {
      setIsSubmitting(true);
      setNotice("");
      const response = await createOrderClaim({
        order_code: order.order_code,
        claim_type: requestType,
        reason_code: reason,
        reason_detail: detail.trim() || null,
        items: [{ order_item_id: itemId, quantity: selectedQuantity }]
      });
      setClaimResult(response);
      setNotice(`신청이 접수되었습니다. 신청번호 ${response.claim_code}`);
    } catch (error) {
      const apiError = error as { code?: string; message?: string };
      setNotice(
        (apiError.code && claimErrorMessages[apiError.code])
        || apiError.message
        || "신청을 접수하지 못했습니다. 주문 상태와 신청 가능 기간을 확인해 주세요."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedEligibilityItem = eligibility?.items.find(
    (item) => item.order_item_id === Number(selectedItemId)
  );
  const hasClaimableItems = eligibility?.items.some((item) => item.claimable_quantity > 0) ?? false;
  const claimWindowText = formatClaimWindow(eligibility?.claim_window_ends_at);

  return (
    <MyPageLayout activePath="/mypage/orders">
      <PageTitle
        rightSlot={<Link className="return-request-back" to={`/mypage/orders/${orderCode}`}>주문 상세로</Link>}
        title="반품·교환·환불 신청"
      />

      {isLoading ? <section className="return-request-card">주문 정보를 불러오는 중입니다.</section> : null}
      {!isLoading && order && order.status !== "DELIVERED" ? (
        <section className="return-request-card">
          배송 완료된 주문만 반품·교환·환불을 신청할 수 있습니다.
        </section>
      ) : null}
      {!isLoading && order && order.status === "DELIVERED" && eligibility && (!eligibility.eligible || !hasClaimableItems) ? (
        <section className="return-request-card">
          {eligibility.reason_code === "CLAIM_WINDOW_EXPIRED"
            ? "반품·교환·환불 신청 기간이 지났습니다."
            : hasClaimableItems
              ? "현재 이 주문은 반품·교환·환불 신청 대상이 아닙니다."
              : "모든 상품의 신청 가능한 수량이 이미 접수되었습니다."}
        </section>
      ) : null}
      {claimResult ? (
        <section className="return-request-card return-request-success" role="status">
          <span className="return-request-success__badge">접수 완료</span>
          <h2>{requestTypeLabels[claimResult.claim_type]} 신청이 접수되었습니다.</h2>
          <dl>
            <div><dt>신청번호</dt><dd>{claimResult.claim_code}</dd></div>
            <div><dt>처리상태</dt><dd>{claimResult.status === "REQUESTED" ? "접수됨" : claimResult.status}</dd></div>
          </dl>
          <Link className="return-request-success__link" to={`/mypage/claims/${encodeURIComponent(claimResult.claim_code)}`}>클레임 상세 보기</Link>
          <Link className="return-request-success__link" to={`/mypage/orders/${orderCode}`}>주문 상세로 이동</Link>
        </section>
      ) : null}
      {!claimResult && !isLoading && order && order.status === "DELIVERED" && eligibility?.eligible && hasClaimableItems ? (
        <form className="return-request-card return-request-form" onSubmit={submitRequest}>
          <div className="return-request-order-summary">
            <span>주문번호</span>
            <strong>{order.order_code}</strong>
          </div>

          <label>
            <span>신청 상품</span>
            <select
              disabled={isSubmitting}
              value={selectedItemId}
              onChange={(event) => {
                setSelectedItemId(event.target.value);
                setSelectedQuantity(1);
              }}
            >
              {order.items.map((item) => {
                const itemEligibility = eligibility?.items.find((candidate) => candidate.order_item_id === item.id);
                if (!itemEligibility || itemEligibility.claimable_quantity < 1) return null;
                return (
                  <option key={item.id} value={item.id}>
                    {item.brand_name} · {item.product_name} · 주문 {item.quantity}개 · 신청 가능 {itemEligibility.claimable_quantity}개
                  </option>
                );
              })}
            </select>
          </label>

          <label>
            <span>신청 수량</span>
            <select
              disabled={isSubmitting}
              value={selectedQuantity}
              onChange={(event) => setSelectedQuantity(Number(event.target.value))}
            >
              {Array.from({ length: selectedEligibilityItem?.claimable_quantity ?? 0 }, (_, index) => (
                <option key={index + 1} value={index + 1}>{index + 1}개</option>
              ))}
            </select>
          </label>

          <fieldset>
            <legend>신청 유형</legend>
            <div className="return-request-type-list">
              {(Object.keys(requestTypeLabels) as RequestType[]).map((type) => (
                <label className={requestType === type ? "active" : ""} key={type}>
                  <input checked={requestType === type} disabled={isSubmitting} name="request-type" onChange={() => setRequestType(type)} type="radio" />
                  {requestTypeLabels[type]}
                </label>
              ))}
            </div>
          </fieldset>

          <label>
            <span>사유</span>
            <select disabled={isSubmitting} required value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">사유를 선택해 주세요</option>
              <option value="CHANGE_OF_MIND">단순 변심</option>
              <option value="DEFECTIVE">상품 하자</option>
              <option value="WRONG_ITEM">오배송·상품 누락</option>
              <option value="OTHER">기타</option>
            </select>
          </label>

          <label>
            <span>상세 내용 <small>(선택)</small></span>
            <textarea disabled={isSubmitting} maxLength={2000} onChange={(event) => setDetail(event.target.value)} placeholder="상세 사유를 입력해 주세요." value={detail} />
          </label>

          <div className="return-request-api-note">
            배송 완료 후 7일 이내에 상품별 남은 수량만 신청할 수 있습니다.
            {claimWindowText ? <><br />신청 가능 기한: {claimWindowText}</> : null}
          </div>
          {notice ? <p className="return-request-notice" role="status">{notice}</p> : null}
          <button
            className="return-request-submit"
            disabled={!selectedItemId || !reason || selectedQuantity < 1 || isSubmitting}
            type="submit"
          >
            {isSubmitting ? "접수 중..." : `${requestTypeLabels[requestType]} 신청 접수하기`}
          </button>
        </form>
      ) : null}
    </MyPageLayout>
  );
}

export default ReturnRequestPage;
