import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { createOrderClaim, getClaimEligibility } from "../../lib/claimApi";
import { clearAgentClaimDraft, readAgentClaimDraft } from "../../lib/agentDrafts";
import { getOrderDetail } from "../../lib/orderApi";
import type { OrderClaimEligibilityResponse, OrderClaimType } from "../../types/claim";
import type { OrderDetailResponse } from "../../types/order";
import { MyPageLayout, PageTitle } from "./MyPageShell";

type RequestType = OrderClaimType;

const requestTypeLabels: Record<RequestType, string> = {
  RETURN: "반품",
  EXCHANGE: "교환",
  REFUND: "환불"
};

function ReturnRequestPage() {
  const { orderCode = "" } = useParams();
  const [order, setOrder] = useState<OrderDetailResponse | null>(null);
  const [eligibility, setEligibility] = useState<OrderClaimEligibilityResponse | null>(null);
  const [selectedItemId, setSelectedItemId] = useState("");
  const [requestType, setRequestType] = useState<RequestType>("RETURN");
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [selectedImages, setSelectedImages] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notice, setNotice] = useState("");

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
      const response = await createOrderClaim({
        order_code: order.order_code,
        claim_type: requestType,
        reason_code: reason,
        reason_detail: detail.trim() || null,
        items: [{ order_item_id: itemId, quantity: 1 }]
      });
      setNotice(`신청이 접수되었습니다. 신청번호 ${response.claim_code}`);
    } catch {
      setNotice("신청을 접수하지 못했습니다. 주문 상태와 신청 가능 기간을 확인해 주세요.");
    }
  };

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
      {!isLoading && order && order.status === "DELIVERED" && eligibility && !eligibility.eligible ? (
        <section className="return-request-card">
          현재 이 주문은 반품·교환·환불 신청 대상이 아닙니다.
        </section>
      ) : null}
      {!isLoading && order && order.status === "DELIVERED" && eligibility?.eligible ? (
        <form className="return-request-card return-request-form" onSubmit={submitRequest}>
          <div className="return-request-order-summary">
            <span>주문번호</span>
            <strong>{order.order_code}</strong>
          </div>

          <label>
            <span>신청 상품</span>
            <select value={selectedItemId} onChange={(event) => setSelectedItemId(event.target.value)}>
              {order.items.filter((item) => (eligibility?.items.find((candidate) => candidate.order_item_id === item.id)?.claimable_quantity ?? 0) > 0).map((item) => (
                <option key={item.id} value={item.id}>{item.brand_name} · {item.product_name} · {item.quantity}개</option>
              ))}
            </select>
          </label>

          <fieldset>
            <legend>신청 유형</legend>
            <div className="return-request-type-list">
              {(Object.keys(requestTypeLabels) as RequestType[]).map((type) => (
                <label className={requestType === type ? "active" : ""} key={type}>
                  <input checked={requestType === type} name="request-type" onChange={() => setRequestType(type)} type="radio" />
                  {requestTypeLabels[type]}
                </label>
              ))}
            </div>
          </fieldset>

          <label>
            <span>사유</span>
            <select required value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">사유를 선택해 주세요</option>
              <option value="CHANGE_OF_MIND">단순 변심</option>
              <option value="DEFECTIVE">상품 하자</option>
              <option value="WRONG_ITEM">오배송·상품 누락</option>
              <option value="OTHER">기타</option>
            </select>
          </label>

          <label>
            <span>상세 내용 <small>(선택)</small></span>
            <textarea maxLength={1000} onChange={(event) => setDetail(event.target.value)} placeholder="상세 사유를 입력해 주세요." value={detail} />
          </label>

          <label>
            <span>사진 첨부 <small>(선택)</small></span>
            <input
              accept="image/*"
              multiple
              onChange={(event) => setSelectedImages(Array.from(event.target.files ?? []))}
              type="file"
            />
            {selectedImages.length ? (
              <small className="return-request-file-summary">{selectedImages.map((file) => file.name).join(", ")}</small>
            ) : null}
          </label>

          <div className="return-request-api-note">배송 완료 후 신청 가능 기간과 상품별 잔여 수량을 확인해 접수합니다. 사진 첨부는 현재 API 계약에 포함되지 않습니다.</div>
          {notice ? <p className="return-request-notice" role="status">{notice}</p> : null}
          <button className="return-request-submit" disabled={!selectedItemId || !reason} type="submit">신청 내용 확인</button>
        </form>
      ) : null}
    </MyPageLayout>
  );
}

export default ReturnRequestPage;
