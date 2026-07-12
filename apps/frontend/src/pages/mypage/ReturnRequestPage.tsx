import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getOrderDetail } from "../../lib/orderApi";
import type { OrderDetailResponse } from "../../types/order";
import { MyPageLayout, PageTitle } from "./MyPageShell";

type RequestType = "RETURN" | "EXCHANGE" | "REFUND";

const requestTypeLabels: Record<RequestType, string> = {
  RETURN: "반품",
  EXCHANGE: "교환",
  REFUND: "환불"
};

function ReturnRequestPage() {
  const { orderCode = "" } = useParams();
  const [order, setOrder] = useState<OrderDetailResponse | null>(null);
  const [selectedItemId, setSelectedItemId] = useState("");
  const [requestType, setRequestType] = useState<RequestType>("RETURN");
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  const [selectedImages, setSelectedImages] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!orderCode) return;
    getOrderDetail(orderCode)
      .then((response) => {
        setOrder(response);
        setSelectedItemId(String(response.items[0]?.id ?? ""));
      })
      .catch(() => setNotice("주문 정보를 불러오지 못했습니다."))
      .finally(() => setIsLoading(false));
  }, [orderCode]);

  const submitRequest = (event: FormEvent) => {
    event.preventDefault();
    setNotice("신청 API 연결 후 접수할 수 있습니다. 입력한 내용은 아직 전송되지 않았습니다.");
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
      {!isLoading && order && order.status === "DELIVERED" ? (
        <form className="return-request-card return-request-form" onSubmit={submitRequest}>
          <div className="return-request-order-summary">
            <span>주문번호</span>
            <strong>{order.order_code}</strong>
          </div>

          <label>
            <span>신청 상품</span>
            <select value={selectedItemId} onChange={(event) => setSelectedItemId(event.target.value)}>
              {order.items.map((item) => (
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

          <div className="return-request-api-note">백엔드 신청 API 연결 전 UI 골격입니다. 사진 첨부와 실제 접수는 API 계약 후 연결됩니다.</div>
          {notice ? <p className="return-request-notice" role="status">{notice}</p> : null}
          <button className="return-request-submit" disabled={!selectedItemId || !reason} type="submit">신청 내용 확인</button>
        </form>
      ) : null}
    </MyPageLayout>
  );
}

export default ReturnRequestPage;
