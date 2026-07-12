// 관리자 주문 화면 mock 데이터·타입.
// Chunk 2(동작 보존 추출) 단계: 부모(AdminDashboardPage)의 orders 초기값과
// 주문 섹션이 둘 다 여기서 가져다 쓴다. Chunk 3에서 주문 섹션은 실 API 로 교체되지만,
// 대시보드·재고(M4/M5) 화면은 계속 이 mock 을 쓰므로 별도 파일로 유지한다.

export type MockOrderStatus =
  | "결제대기"
  | "결제완료"
  | "배송준비"
  | "배송중"
  | "취소요청"
  | "취소완료"
  | "만료";

export type MockPaymentStatus = "승인완료" | "승인대기" | "실패" | "취소완료";

export type MockOrderRow = {
  id: string;
  orderCode: string;
  customer: string;
  productSummary: string;
  itemCount: number;
  totalAmount: number;
  status: MockOrderStatus;
  paymentStatus: MockPaymentStatus;
  stockReserved: number;
  recommendationId: string;
  updatedAt: string;
};

export type MockOrderExceptionRow = {
  time: string;
  orderCode: string;
  issue: string;
  action: string;
};

export const mockOrderRows: MockOrderRow[] = [
  {
    id: "order_1",
    orderCode: "ord_20260706_1031",
    customer: "guest_9182",
    productSummary: "토리든 다이브인 저분자 히알루론산 세럼",
    itemCount: 2,
    totalAmount: 43600,
    status: "결제완료",
    paymentStatus: "승인완료",
    stockReserved: 2,
    recommendationId: "rec_8f34",
    updatedAt: "2026-07-06 16:42"
  },
  {
    id: "order_2",
    orderCode: "ord_20260706_1028",
    customer: "user_1204",
    productSummary: "한율 달빛유자C 세럼 외 1개",
    itemCount: 2,
    totalAmount: 60800,
    status: "결제대기",
    paymentStatus: "승인대기",
    stockReserved: 2,
    recommendationId: "rec_3c92",
    updatedAt: "2026-07-06 16:31"
  },
  {
    id: "order_3",
    orderCode: "ord_20260706_0997",
    customer: "user_0991",
    productSummary: "닥터지 레드 블레미쉬 클리어 수딩 크림",
    itemCount: 1,
    totalAmount: 18900,
    status: "배송준비",
    paymentStatus: "승인완료",
    stockReserved: 1,
    recommendationId: "rec_7701",
    updatedAt: "2026-07-06 15:18"
  },
  {
    id: "order_4",
    orderCode: "ord_20260706_0942",
    customer: "guest_7741",
    productSummary: "라운드랩 자작나무 수분 크림",
    itemCount: 1,
    totalAmount: 24000,
    status: "취소요청",
    paymentStatus: "취소완료",
    stockReserved: 0,
    recommendationId: "-",
    updatedAt: "2026-07-06 14:04"
  },
  {
    id: "order_5",
    orderCode: "ord_20260706_0872",
    customer: "user_0208",
    productSummary: "차앤박 핑크토닝 딥인샷 앰플",
    itemCount: 1,
    totalAmount: 29800,
    status: "만료",
    paymentStatus: "실패",
    stockReserved: 0,
    recommendationId: "rec_c191",
    updatedAt: "2026-07-06 12:45"
  }
];

export const mockOrderExceptionRows: MockOrderExceptionRow[] = [
  {
    time: "16:31",
    orderCode: "ord_20260706_1028",
    issue: "결제 승인 대기 14분",
    action: "만료 job 확인"
  },
  {
    time: "14:04",
    orderCode: "ord_20260706_0942",
    issue: "취소 요청",
    action: "재고 복원 완료"
  },
  {
    time: "12:45",
    orderCode: "ord_20260706_0872",
    issue: "mock 결제 실패",
    action: "사용자 재시도 가능"
  }
];
