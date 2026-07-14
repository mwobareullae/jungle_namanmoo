import type { OrderCancelReasonCode } from "../../types/order";

export const CANCEL_REASON_DETAIL_MAX_LENGTH = 1000;
export const CANCEL_REASON_OPTIONS = [
  { id: "CHANGE_OF_MIND", label: "단순 변심" },
  { id: "ORDER_MISTAKE", label: "옵션·수량 선택 실수" },
  { id: "ORDER_INFO_CHANGE", label: "배송지·주문정보 변경" },
  { id: "DELIVERY_DELAY", label: "배송 지연" },
  { id: "OTHER", label: "기타" }
] as const;

export type CancelReasonDraft = {
  optionId: string;
  reasonCode: OrderCancelReasonCode;
  optionLabel: string;
  detail: string;
};
