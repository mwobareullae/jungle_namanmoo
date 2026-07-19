import { Fragment, useMemo, useRef, useState } from "react";
import EvidenceCandidateReviewPanel from "../components/admin/EvidenceCandidateReviewPanel";
import { AdminOrderStatusSection } from "../features/admin/orders/AdminOrderStatusSection";
import { AdminCancelClaimSection } from "../features/admin/cancelClaims/AdminCancelClaimSection";
import { AdminIngredientMappingSection } from "../features/admin/ingredientMappings/AdminIngredientMappingSection";
import { AdminInventoryPriceSection } from "../features/admin/inventoryPrice/AdminInventoryPriceSection";
import { AdminImageBulkLinkSection } from "../features/admin/imageBulkLink/AdminImageBulkLinkSection";
import { AdminProductFormSection } from "../features/admin/products/AdminProductFormSection";
import { AdminProductSection } from "../features/admin/products/AdminProductSection";
import type { AdminBulkImportRowInput } from "../features/admin/api/adminBulkImportApi";
import { useAdminBulkImport } from "../features/admin/bulkImport/useAdminBulkImport";
import { mockOrderRows, MockOrderRow } from "../features/admin/orders/adminOrderMock";
import { AdminAccessNotice } from "../features/admin/AdminAccessNotice";
import { useAdminAccess } from "../features/admin/hooks/useAdminAccess";

type AdminView =
  | "dashboard"
  | "products"
  | "productForm"
  | "excelUpload"
  | "imageUpload"
  | "ingredientReview"
  | "evidenceReview"
  | "stockPrice"
  | "orderStatus"
  | "cancelClaims"
  | "sellers"
  | "sellerInspection"
  | "sellerSettlement";
type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type ExcelImportState = "idle" | "preview" | "submitting" | "done";
type OperationLogRow = {
  id: string;
  time: string;
  area: string;
  title: string;
  detail: string;
  tone: BadgeTone;
};

type AdminToast = {
  message: string;
  tone: BadgeTone;
} | null;

type CsvValue = string | number;
type ExcelSummaryRow = { label: string; value: string; tone: BadgeTone };
type ExcelClientIssue = {
  row: number;
  importSku: string;
  field: string;
  value: string;
  reason: string;
};
type ExcelDisplayRow = ExcelClientIssue & {
  status: "형식 통과" | "형식 오류" | "CREATED" | "SKIPPED" | "FAILED";
};
type PendingAction = "ingredient" | "duplicateProduct" | "excelFailure" | "imageFailure" | "embedding";

type PendingItem = {
  label: string;
  note: string;
  status: string;
  tone: BadgeTone;
  action: PendingAction;
};

const navItems: Array<{ label: string; view: AdminView }> = [
  { label: "대시보드", view: "dashboard" },
  { label: "상품 조회/상태 확인", view: "products" },
  { label: "상품 등록/수정", view: "productForm" },
  { label: "엑셀 상품 대량 등록", view: "excelUpload" },
  { label: "이미지 대량 연결", view: "imageUpload" },
  { label: "성분 매핑 검수", view: "ingredientReview" },
  { label: "논문 근거 관리", view: "evidenceReview" },
  { label: "재고/가격 확인", view: "stockPrice" },
  { label: "주문 상태 확인", view: "orderStatus" },
  { label: "취소·클레임 관리", view: "cancelClaims" },
  { label: "셀러 관리", view: "sellers" },
  { label: "셀러별 상품 검수", view: "sellerInspection" },
  { label: "셀러별 정산", view: "sellerSettlement" }
];

const navGroupHeadings: Partial<Record<AdminView, string>> = {
  products: "상품 운영",
  evidenceReview: "추천 운영",
  orderStatus: "주문 운영",
  sellers: "셀러 운영"
};

type SellerStatus = "입점중" | "심사중" | "정지";
type SellerRow = {
  id: string;
  name: string;
  bizNo: string;
  owner: string;
  manager: string;
  contact: string;
  status: SellerStatus;
  joinedAt: string;
  productCount: number;
  pendingCount: number;
  monthlySales: number;
  lastActive: string;
};

const MOCK_SELLERS: SellerRow[] = [
  { id: "sel_torriden", name: "토리든", bizNo: "000-00-00000", owner: "대표자 1", manager: "담당자 A", contact: "010-0000-0000", status: "입점중", joinedAt: "2025-11-02", productCount: 42, pendingCount: 0, monthlySales: 18_400_000, lastActive: "2026-07-08" },
  { id: "sel_roundlab", name: "라운드랩", bizNo: "000-00-00000", owner: "대표자 2", manager: "담당자 B", contact: "010-0000-0000", status: "입점중", joinedAt: "2025-11-15", productCount: 38, pendingCount: 2, monthlySales: 22_950_000, lastActive: "2026-07-09" },
  { id: "sel_numbuzin", name: "넘버즈인", bizNo: "000-00-00000", owner: "대표자 3", manager: "담당자 C", contact: "010-0000-0000", status: "입점중", joinedAt: "2025-12-01", productCount: 27, pendingCount: 1, monthlySales: 15_300_000, lastActive: "2026-07-09" },
  { id: "sel_layerlab", name: "레이어랩", bizNo: "000-00-00000", owner: "대표자 4", manager: "담당자 D", contact: "010-0000-0000", status: "심사중", joinedAt: "2026-07-05", productCount: 0, pendingCount: 12, monthlySales: 0, lastActive: "2026-07-08" },
  { id: "sel_dearcia", name: "닥터엘시아", bizNo: "000-00-00000", owner: "대표자 5", manager: "담당자 E", contact: "010-0000-0000", status: "입점중", joinedAt: "2026-01-10", productCount: 19, pendingCount: 0, monthlySales: 8_700_000, lastActive: "2026-07-07" },
  { id: "sel_partion", name: "파티온", bizNo: "000-00-00000", owner: "대표자 6", manager: "담당자 F", contact: "010-0000-0000", status: "심사중", joinedAt: "2026-07-06", productCount: 0, pendingCount: 8, monthlySales: 0, lastActive: "2026-07-06" },
  { id: "sel_itsskin", name: "잇츠스킨", bizNo: "000-00-00000", owner: "대표자 7", manager: "담당자 G", contact: "010-0000-0000", status: "정지", joinedAt: "2025-10-20", productCount: 14, pendingCount: 0, monthlySales: 0, lastActive: "2026-06-14" },
  { id: "sel_naturep", name: "네이처리퍼블릭", bizNo: "000-00-00000", owner: "대표자 8", manager: "담당자 H", contact: "010-0000-0000", status: "입점중", joinedAt: "2025-12-18", productCount: 51, pendingCount: 3, monthlySales: 27_600_000, lastActive: "2026-07-09" }
];

const MOCK_SELLER_STATS = {
  total: MOCK_SELLERS.length,
  active: MOCK_SELLERS.filter((s) => s.status === "입점중").length,
  review: MOCK_SELLERS.filter((s) => s.status === "심사중").length,
  suspended: MOCK_SELLERS.filter((s) => s.status === "정지").length
};

type InspectionState = "검수대기" | "보류" | "반려" | "검수통과";
type InspectionRow = {
  id: string;
  seller: string;
  importJob: string;
  productName: string;
  sellerSku: string;
  reviewState: InspectionState;
  failReason: string;
  imageState: "정상" | "대기";
  recommendable: "가능" | "불가" | "—";
  ingredientPending: string;
  imageMatch: string;
  duplicateCandidate: string;
};

const MOCK_INSPECTIONS: InspectionRow[] = [
  { id: "insp_1024", seller: "토리든", importJob: "job_1024", productName: "다이브인 시카 세럼", sellerSku: "sku_torriden_01", reviewState: "검수통과", failReason: "—", imageState: "정상", recommendable: "가능", ingredientPending: "없음", imageMatch: "정상", duplicateCandidate: "없음" },
  { id: "insp_1025", seller: "라운드랩", importJob: "job_1025", productName: "자작나무 수분 크림", sellerSku: "sku_roundlab_01", reviewState: "검수대기", failReason: "이미지 미매칭", imageState: "대기", recommendable: "—", ingredientPending: "없음", imageMatch: "미매칭 (1)", duplicateCandidate: "없음" },
  { id: "insp_1026", seller: "넘버즈인", importJob: "job_1026", productName: "5번 글루타치온 앰플", sellerSku: "sku_numbuzin_05", reviewState: "보류", failReason: "성분 pending 2", imageState: "정상", recommendable: "—", ingredientPending: "2건", imageMatch: "정상", duplicateCandidate: "없음" },
  { id: "insp_1027", seller: "레이어랩", importJob: "job_1027", productName: "니오좀 판테놀 세럼", sellerSku: "sku_layerlab_01", reviewState: "검수대기", failReason: "성분 pending 5", imageState: "대기", recommendable: "—", ingredientPending: "5건", imageMatch: "대기", duplicateCandidate: "없음" },
  { id: "insp_1028", seller: "파티온", importJob: "job_1028", productName: "노스카나인 흔적 앰플", sellerSku: "sku_partion_09", reviewState: "반려", failReason: "중복 상품 후보", imageState: "정상", recommendable: "불가", ingredientPending: "없음", imageMatch: "정상", duplicateCandidate: "후보 1건" },
  { id: "insp_1029", seller: "닥터엘시아", importJob: "job_1029", productName: "비타민C 부스팅 세럼", sellerSku: "sku_dearcia_02", reviewState: "검수통과", failReason: "—", imageState: "정상", recommendable: "가능", ingredientPending: "없음", imageMatch: "정상", duplicateCandidate: "없음" }
];

const MOCK_INSPECTION_STATS = {
  waiting: 3,
  held: 2,
  ingredientPending: 7,
  imageUnmatched: 1
};

type SettlementState = "정산대기" | "정산예정" | "정산완료" | "보류";
type SettlementRow = {
  id: string;
  seller: string;
  sales: number;
  refunds: number;
  fee: number;
  payout: number;
  state: SettlementState;
  scheduledAt: string;
  completedAt: string;
  accountVerified: "확인" | "미확인";
};

const MOCK_SETTLEMENTS: SettlementRow[] = [
  { id: "stl_torriden", seller: "토리든", sales: 18_400_000, refunds: 620_000, fee: 1_778_000, payout: 16_002_000, state: "정산완료", scheduledAt: "2026-07-05", completedAt: "2026-07-05", accountVerified: "확인" },
  { id: "stl_roundlab", seller: "라운드랩", sales: 22_950_000, refunds: 950_000, fee: 2_200_000, payout: 19_800_000, state: "정산예정", scheduledAt: "2026-07-15", completedAt: "—", accountVerified: "확인" },
  { id: "stl_numbuzin", seller: "넘버즈인", sales: 15_300_000, refunds: 300_000, fee: 1_500_000, payout: 13_500_000, state: "정산예정", scheduledAt: "2026-07-15", completedAt: "—", accountVerified: "확인" },
  { id: "stl_dearcia", seller: "닥터엘시아", sales: 8_700_000, refunds: 200_000, fee: 850_000, payout: 7_650_000, state: "정산완료", scheduledAt: "2026-07-05", completedAt: "2026-07-05", accountVerified: "확인" },
  { id: "stl_naturep", seller: "네이처리퍼블릭", sales: 27_600_000, refunds: 1_100_000, fee: 2_650_000, payout: 23_850_000, state: "정산대기", scheduledAt: "2026-07-25", completedAt: "—", accountVerified: "확인" },
  { id: "stl_itsskin", seller: "잇츠스킨", sales: 4_200_000, refunds: 180_000, fee: 402_000, payout: 3_618_000, state: "보류", scheduledAt: "—", completedAt: "—", accountVerified: "미확인" }
];

const navPendingGroups: Array<{ heading: string; items: string[] }> = [
  {
    heading: "운영 설정",
    items: [
      "카테고리·브랜드 관리",
      "성분 사전 관리",
      "이미지 파일명 규칙",
      "엑셀 업로드 양식",
      "관리자 권한/작업 로그"
    ]
  }
];

const now = new Date();
const pad2 = (n: number) => String(n).padStart(2, "0");
const todayIso = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
const todayLabel = `${todayIso} ${["일", "월", "화", "수", "목", "금", "토"][now.getDay()]}`;

const stats = [
  { label: "전체 상품", value: "24,585" },
  { label: "추천 가능", value: "10,167" },
  { label: "전성분 원문", value: "24,585" },
  { label: "인덱스 대기", value: "0" }
];

// 화면 검토용 예시값(mock). 실제 API 연동 시 이 상수만 교체하면 된다.
const MOCK_STATUS_BREAKDOWN = [
  { label: "판매중", value: 9812, color: "#3aa6d1" },
  { label: "검수 필요", value: 1204, color: "#f0b429" },
  { label: "이미지 누락", value: 342, color: "#e57373" },
  { label: "품절 임박", value: 87, color: "#9575cd" },
  { label: "정상", value: 13140, color: "#e2e8ee" }
];
const MOCK_STATUS_TOTAL = MOCK_STATUS_BREAKDOWN.reduce((sum, seg) => sum + seg.value, 0);
const DONUT_CIRC = 2 * Math.PI * 52;
const MOCK_STATUS_SEGMENTS = (() => {
  let acc = 0;
  return MOCK_STATUS_BREAKDOWN.map((seg) => {
    const dash = (seg.value / MOCK_STATUS_TOTAL) * DONUT_CIRC;
    const segment = { ...seg, dash, offset: -acc };
    acc += dash;
    return segment;
  });
})();
const MOCK_PENDING_QUEUE = [
  { label: "성분 검수", value: 27243, color: "#f0b429" },
  { label: "상품명 중복", value: 2590, color: "#3aa6d1" },
  { label: "import 실패", value: 12, color: "#e57373" },
  { label: "이미지 실패", value: 4, color: "#e57373" },
  { label: "임베딩 대기", value: 1, color: "#9575cd" }
];
const MOCK_PENDING_MAX = Math.max(...MOCK_PENDING_QUEUE.map((bar) => bar.value));

const pendingItems: PendingItem[] = [
  {
    label: "성분 매핑 검수 대기",
    note: "pending 27,243종 · 연결 665,304건",
    status: "검수 필요",
    tone: "warning",
    action: "ingredient"
  },
  {
    label: "상품명 중복 후보",
    note: "2,590그룹 · 6,450개 상품",
    status: "확인 대기",
    tone: "neutral",
    action: "duplicateProduct"
  },
  {
    label: "import 실패 행",
    note: "products_0706.xlsx · 12행",
    status: "실패 파일",
    tone: "danger",
    action: "excelFailure"
  },
  {
    label: "이미지 자동 연결 실패",
    note: "image_batch_01.zip · 4개 파일",
    status: "매칭 실패",
    tone: "warning",
    action: "imageFailure"
  },
  {
    label: "임베딩 자동 반영",
    note: "서버 OPENAI_API_KEY 준비 전 일배치",
    status: "키 대기",
    tone: "neutral",
    action: "embedding"
  }
];

const importRows = [
  {
    time: "14:02",
    file: "products_0706.xlsx",
    success: 118,
    failed: 12,
    status: "부분 실패",
    tone: "danger"
  },
  {
    time: "10:31",
    file: "brand_a_products.xlsx",
    success: 42,
    failed: 0,
    status: "완료",
    tone: "success"
  },
  {
    time: "어제",
    file: "image_batch_01.zip",
    success: 310,
    failed: 4,
    status: "매칭 실패",
    tone: "warning"
  }
];

const indexSummary = [
  { label: "조인 문서", value: "24,585" },
  { label: "임베딩 반영", value: "24,585 / 24,585" },
  { label: "마지막 rebuild", value: "09:12 · 13.3초" }
];

const excelTemplateColumns = [
  { label: "import_sku", required: "필수", note: "대문자 영문·숫자·._- 1~64자, 재업로드 식별값" },
  { label: "product_name", required: "필수", note: "상품명" },
  { label: "brand_name", required: "필수", note: "등록된 브랜드명 또는 별칭" },
  { label: "category_name", required: "필수", note: "등록된 카테고리명 또는 별칭" },
  { label: "price", required: "필수", note: "양의 정수 판매가" },
  { label: "stock_quantity", required: "필수", note: "0 이상의 정수 초기 재고" },
  { label: "ingredients_raw", required: "필수", note: "전성분을 | 기호로 구분" }
];
const BULK_IMPORT_REQUIRED_HEADERS = excelTemplateColumns.map((column) => column.label);
const IMPORT_SKU_PATTERN = /^[A-Z0-9][A-Z0-9._-]{0,63}$/;

const getBulkImportFieldValue = (row: AdminBulkImportRowInput, field: string | null): string => {
  if (field === "import_sku") return row.importSku;
  if (field === "product_name") return row.productName;
  if (field === "brand_name") return row.brandName;
  if (field === "category_name") return row.categoryName;
  if (field === "price") return String(row.price);
  if (field === "stock_quantity") return String(row.stockQuantity);
  if (field === "ingredients_raw") return row.ingredientsRaw;
  return "-";
};

type ExcelGrid = string[][];
type DeflateStream = { readable: ReadableStream<Uint8Array>; writable: WritableStream<Uint8Array> };

const decodeXmlEntities = (text: string): string =>
  text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&amp;/g, "&");

const parseCsvText = (text: string): ExcelGrid => {
  const rows: ExcelGrid = [];
  let cell = "";
  let row: string[] = [];
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell);
      cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell);
  if (row.some((value) => value !== "")) rows.push(row);
  return rows;
};

const inflateRawBytes = async (bytes: Uint8Array): Promise<Uint8Array | null> => {
  const Ctor = (globalThis as { DecompressionStream?: new (format: string) => DeflateStream }).DecompressionStream;
  if (!Ctor) return null;
  const safeBytes = new Uint8Array(bytes);
  const stream = new Blob([safeBytes.buffer as ArrayBuffer]).stream().pipeThrough(new Ctor("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
};

const readZipEntries = async (buffer: ArrayBuffer): Promise<Map<string, Uint8Array>> => {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const entries = new Map<string, Uint8Array>();
  let eocd = -1;
  for (let i = buffer.byteLength - 22; i >= Math.max(0, buffer.byteLength - 65558); i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) return entries;
  const count = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  for (let n = 0; n < count; n += 1) {
    if (view.getUint32(offset, true) !== 0x02014b50) break;
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = new TextDecoder().decode(bytes.slice(offset + 46, offset + 46 + nameLength));
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const data = bytes.slice(dataStart, dataStart + compressedSize);
    if (method === 0) {
      entries.set(name, data);
    } else {
      const inflated = await inflateRawBytes(data);
      if (inflated) entries.set(name, inflated);
    }
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
};

const columnLetterToIndex = (letters: string): number =>
  letters.split("").reduce((acc, ch) => acc * 26 + (ch.charCodeAt(0) - 64), 0) - 1;

const parseSheetXml = (sheetXml: string, sharedStrings: string[]): ExcelGrid => {
  const rows: ExcelGrid = [];
  const rowChunks = sheetXml.match(/<row[^>]*>[\s\S]*?<\/row>/g) ?? [];
  for (const chunk of rowChunks) {
    const cells: string[] = [];
    const cellPattern = /<c r="([A-Z]+)\d+"([^>]*)(?:\/>|>([\s\S]*?)<\/c>)/g;
    let match: RegExpExecArray | null = cellPattern.exec(chunk);
    while (match) {
      const inner = match[3] ?? "";
      const rawValue =
        (inner.match(/<v>([\s\S]*?)<\/v>/) ?? [])[1] ??
        (inner.match(/<t[^>]*>([\s\S]*?)<\/t>/) ?? [])[1] ??
        "";
      const isShared = /t="s"/.test(match[2] ?? "");
      cells[columnLetterToIndex(match[1])] = decodeXmlEntities(
        isShared ? sharedStrings[Number(rawValue)] ?? "" : rawValue,
      );
      match = cellPattern.exec(chunk);
    }
    rows.push(Array.from(cells, (value) => value ?? ""));
  }
  return rows;
};

const parseExcelUpload = async (file: File): Promise<ExcelGrid | null> => {
  try {
    if (/\.csv$/i.test(file.name)) {
      return parseCsvText(await file.text());
    }
    const entries = await readZipEntries(await file.arrayBuffer());
    const sheetName =
      [...entries.keys()].find((key) => key === "xl/worksheets/sheet1.xml") ??
      [...entries.keys()].find((key) => key.startsWith("xl/worksheets/"));
    const sheetBytes = sheetName ? entries.get(sheetName) : undefined;
    if (!sheetBytes) return null;
    const decoder = new TextDecoder();
    const sharedXml = entries.has("xl/sharedStrings.xml")
      ? decoder.decode(entries.get("xl/sharedStrings.xml"))
      : "";
    const sharedStrings = (sharedXml.match(/<si>[\s\S]*?<\/si>/g) ?? []).map((si) =>
      decodeXmlEntities(
        (si.match(/<t[^>]*>[\s\S]*?<\/t>/g) ?? []).map((tag) => tag.replace(/<[^>]*>/g, "")).join(""),
      ),
    );
    return parseSheetXml(decoder.decode(sheetBytes), sharedStrings);
  } catch {
    return null;
  }
};

const initialOperationLogs: OperationLogRow[] = [
  {
    id: "log_initial_excel",
    time: "14:02",
    area: "엑셀",
    title: "products_0706.xlsx 검증",
    detail: "118행 등록 가능, 12행 실패 파일 생성",
    tone: "warning"
  },
  {
    id: "log_initial_image",
    time: "어제",
    area: "이미지",
    title: "image_batch_01.zip 매칭",
    detail: "310개 연결, 4개 운영자 확인 필요",
    tone: "success"
  },
  {
    id: "log_initial_embedding",
    time: "09:12",
    area: "검색",
    title: "검색 문서 rebuild 완료",
    detail: "idx_prod_join_* 24,585건 반영",
    tone: "success"
  }
];

function formatCurrentTime() {
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date());
}

function buildCsv(rows: CsvValue[][]) {
  return rows
    .map((row) =>
      row
        .map((cell) => `"${String(cell).replace(/"/g, "\"\"")}"`)
        .join(","),
    )
    .join("\n");
}

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob(["\uFEFF", content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function AdminDashboardPage() {
  const access = useAdminAccess();
  const bulkImport = useAdminBulkImport();
  const [activeView, setActiveView] = useState<AdminView>("dashboard");
  const [selectedSellerId, setSelectedSellerId] = useState(MOCK_SELLERS[0].id);
  const [selectedInspectionId, setSelectedInspectionId] = useState(MOCK_INSPECTIONS[0].id);
  const [selectedSettlementId, setSelectedSettlementId] = useState(MOCK_SETTLEMENTS[0].id);
  const [editingProductCode, setEditingProductCode] = useState<string | null>(null);
  const [excelImportState, setExcelImportState] = useState<ExcelImportState>("idle");
  const [excelFileName, setExcelFileName] = useState("파일을 선택해 주세요");
  const excelFileRef = useRef<File | null>(null);
  const [excelPreviewRows, setExcelPreviewRows] = useState<AdminBulkImportRowInput[]>([]);
  const [excelClientIssues, setExcelClientIssues] = useState<ExcelClientIssue[]>([]);
  const [excelFormError, setExcelFormError] = useState<string | null>(null);
  const [orders] = useState<MockOrderRow[]>(mockOrderRows);
  const [operationLogs, setOperationLogs] = useState<OperationLogRow[]>(initialOperationLogs);
  const [toast, setToast] = useState<AdminToast>(null);

  const excelDisplayRows = useMemo<ExcelDisplayRow[]>(() => {
    if (bulkImport.result) {
      return bulkImport.result.rows.map((resultRow) => {
        const sourceRow = excelPreviewRows[resultRow.rowNumber - 1];
        const importSku = resultRow.importSku ?? sourceRow?.importSku ?? "-";
        if (resultRow.status === "CREATED") {
          const pendingCount = resultRow.ingredientSummary?.pendingCount ?? 0;
          return {
            row: resultRow.rowNumber,
            importSku,
            status: "CREATED",
            field: "product_code",
            value: resultRow.productCode ?? "-",
            reason: pendingCount > 0 ? `등록 완료 · pending 성분 ${pendingCount}개 생성` : "등록 완료",
          };
        }
        if (resultRow.status === "SKIPPED") {
          return {
            row: resultRow.rowNumber,
            importSku,
            status: "SKIPPED",
            field: "import_sku",
            value: resultRow.existingProductCode ?? "-",
            reason: "이미 등록된 import_sku라 기존 상품을 수정하지 않고 건너뛰었습니다.",
          };
        }
        return {
          row: resultRow.rowNumber,
          importSku,
          status: "FAILED",
          field: resultRow.field ?? "product",
          value: sourceRow ? getBulkImportFieldValue(sourceRow, resultRow.field) : "-",
          reason: resultRow.message ?? "이 행을 등록하지 못했습니다.",
        };
      });
    }

    const issuesByRow = new Map(excelClientIssues.map((issue) => [issue.row, issue]));
    return excelPreviewRows.map((row, index) => {
      const issue = issuesByRow.get(index + 1);
      return issue
        ? { ...issue, status: "형식 오류" }
        : {
            row: index + 1,
            importSku: row.importSku,
            status: "형식 통과",
            field: "-",
            value: row.productName,
            reason: "등록할 준비가 됐습니다.",
          };
    });
  }, [bulkImport.result, excelClientIssues, excelPreviewRows]);

  const excelSummaryRows = useMemo<ExcelSummaryRow[]>(() => {
    if (bulkImport.result) {
      const pendingCount = bulkImport.result.rows.reduce(
        (total, row) => total + (row.ingredientSummary?.pendingCount ?? 0),
        0,
      );
      return [
        { label: "총 행", value: String(bulkImport.result.summary.total), tone: "neutral" },
        { label: "등록 완료", value: String(bulkImport.result.summary.created), tone: "success" },
        { label: "이미 존재", value: String(bulkImport.result.summary.skipped), tone: "warning" },
        { label: "실패", value: String(bulkImport.result.summary.failed), tone: "danger" },
        { label: "신규 pending", value: String(pendingCount), tone: "warning" },
      ];
    }

    if (excelPreviewRows.length > 0) {
      return [
        { label: "총 행", value: String(excelPreviewRows.length), tone: "neutral" },
        { label: "형식 통과", value: String(excelPreviewRows.length - excelClientIssues.length), tone: "success" },
        { label: "형식 오류", value: String(excelClientIssues.length), tone: "danger" },
      ];
    }

    return [
      { label: "총 행", value: "-", tone: "neutral" },
      { label: "등록 완료", value: "-", tone: "success" },
      { label: "실패", value: "-", tone: "danger" },
    ];
  }, [bulkImport.result, excelClientIssues.length, excelPreviewRows.length]);

  const liveDashboardOrderSummary = useMemo(
    () => [
      { label: "신규 주문", value: orders.length.toLocaleString("ko-KR") },
      {
        label: "결제 완료",
        value: orders.filter((order) => order.paymentStatus === "승인완료").length.toLocaleString("ko-KR")
      },
      {
        label: "결제 대기",
        value: orders.filter((order) => order.status === "결제대기").length.toLocaleString("ko-KR")
      },
      {
        label: "취소/만료",
        value: orders
          .filter((order) => order.status === "취소완료" || order.status === "만료" || order.paymentStatus === "취소완료")
          .length.toLocaleString("ko-KR")
      }
    ],
    [orders],
  );
  const pushOperationLog = (area: string, title: string, detail: string, tone: BadgeTone = "success") => {
    const time = formatCurrentTime();

    setOperationLogs((currentLogs) => [
      {
        id: `log_local_${currentLogs.length}_${area}_${title}_${time}`,
        time,
        area,
        title,
        detail,
        tone
      },
      ...currentLogs
    ].slice(0, 6));
    setToast({ message: `${title} · ${detail}`, tone });
  };

  const handleExcelPreview = async () => {
    const file = excelFileRef.current;
    if (!file) {
      setExcelFormError("먼저 등록할 xlsx 또는 csv 파일을 선택해 주세요.");
      return;
    }

    const grid = await parseExcelUpload(file);
    if (!grid || grid.length < 2) {
      setExcelFormError("데이터 행이 있는 xlsx 또는 csv 파일만 등록할 수 있습니다.");
      pushOperationLog("엑셀", "엑셀 파싱 실패", `${file.name} · 파일 형식을 확인해 주세요.`, "danger");
      return;
    }
    if (grid.length - 1 > 200) {
      setExcelFormError("한 번에 최대 200행까지 등록할 수 있습니다. 파일을 나누어 다시 시도해 주세요.");
      return;
    }

    const header = grid[0].map((cell) => (cell || "").replace(/^\ufeff/, "").trim());
    const missingHeaders = BULK_IMPORT_REQUIRED_HEADERS.filter((name) => !header.includes(name));
    if (missingHeaders.length > 0) {
      setExcelFormError(`필수 컬럼이 없습니다: ${missingHeaders.join(", ")}`);
      return;
    }

    const columnIndex = (name: string) => header.indexOf(name);
    const rows: AdminBulkImportRowInput[] = [];
    const issues: ExcelClientIssue[] = [];

    grid.slice(1).forEach((cells, index) => {
      const row = index + 1;
      const valueOf = (name: string) => (cells[columnIndex(name)] ?? "").toString().trim();
      const parsedRow: AdminBulkImportRowInput = {
        importSku: valueOf("import_sku"),
        productName: valueOf("product_name"),
        brandName: valueOf("brand_name"),
        categoryName: valueOf("category_name"),
        price: Number(valueOf("price")),
        stockQuantity: Number(valueOf("stock_quantity")),
        ingredientsRaw: valueOf("ingredients_raw"),
      };
      rows.push(parsedRow);

      const fail = (field: string, value: string, reason: string) => {
        if (issues.some((issue) => issue.row === row)) return;
        issues.push({ row, importSku: parsedRow.importSku || "(누락)", field, value, reason });
      };

      if (!parsedRow.importSku) fail("import_sku", "", "필수값이 비어 있습니다.");
      else if (!IMPORT_SKU_PATTERN.test(parsedRow.importSku)) {
        fail("import_sku", parsedRow.importSku, "대문자 영문·숫자·._-만 사용해 1~64자로 입력해 주세요.");
      }
      if (!parsedRow.productName) fail("product_name", "", "필수값이 비어 있습니다.");
      if (!parsedRow.brandName) fail("brand_name", "", "필수값이 비어 있습니다.");
      if (!parsedRow.categoryName) fail("category_name", "", "필수값이 비어 있습니다.");

      const priceRaw = valueOf("price");
      if (!/^\d+$/.test(priceRaw) || parsedRow.price <= 0) {
        fail("price", priceRaw, "0보다 큰 정수로 입력해 주세요.");
      }
      const stockRaw = valueOf("stock_quantity");
      if (!/^\d+$/.test(stockRaw)) {
        fail("stock_quantity", stockRaw, "0 이상의 정수로 입력해 주세요.");
      }

      if (!parsedRow.ingredientsRaw) {
        fail("ingredients_raw", "", "전성분은 비어 있을 수 없습니다.");
      } else if (parsedRow.ingredientsRaw.includes("%")) {
        fail("ingredients_raw", parsedRow.ingredientsRaw, "% 문자는 현재 성분 입력 형식에서 지원하지 않습니다.");
      } else if (parsedRow.ingredientsRaw.split("|").some((ingredient) => !ingredient.trim())) {
        fail(
          "ingredients_raw",
          parsedRow.ingredientsRaw,
          "전성분은 | 기호로 구분해 입력해 주세요. 앞뒤 또는 연속된 | 기호는 사용할 수 없습니다.",
        );
      }
    });

    setExcelPreviewRows(rows);
    setExcelClientIssues(issues);
    setExcelFormError(null);
    bulkImport.reset();
    setExcelImportState("preview");
    pushOperationLog(
      "엑셀",
      "상품 엑셀 미리보기 완료",
      `${file.name} · 총 ${rows.length}행 · 형식 오류 ${issues.length}행`,
      issues.length > 0 ? "warning" : "success",
    );
  };

  const handleExcelSubmit = async () => {
    if (excelPreviewRows.length === 0) {
      setExcelFormError("먼저 파일을 선택하고 미리보기를 실행해 주세요.");
      return;
    }
    if (excelClientIssues.length > 0) {
      setExcelFormError("형식 오류를 수정한 뒤 파일을 다시 선택하고 미리보기를 실행해 주세요.");
      return;
    }

    setExcelFormError(null);
    setExcelImportState("submitting");
    const result = await bulkImport.submit(excelPreviewRows);
    if (!result) {
      setExcelImportState("preview");
      return;
    }

    setExcelImportState("done");
    const tone: BadgeTone = result.summary.failed > 0 || result.reviewRefresh === "FAILED" ? "warning" : "success";
    pushOperationLog(
      "엑셀",
      "상품 대량등록 완료",
      `등록 ${result.summary.created}행 · 기존 상품 ${result.summary.skipped}행 · 실패 ${result.summary.failed}행`,
      tone,
    );
  };

  const handleExcelTemplateDownload = () => {
    downloadTextFile(
      "mwbl_product_import_template.csv",
      buildCsv([
        excelTemplateColumns.map((column) => column.label),
        [
          "IMPORT_TORRIDEN_DIVEIN_SERUM",
          "토리든 다이브인 저분자 히알루론산 세럼",
          "토리든",
          "serum",
          21800,
          142,
          "정제수|부틸렌글라이콜|글리세린|나이아신아마이드|판테놀"
        ]
      ]),
    );
    pushOperationLog("엑셀", "템플릿 다운로드", "상품 대량 등록 CSV 템플릿 생성", "neutral");
  };

  const handleFailureFile = (area: "엑셀" | "import") => {
    downloadTextFile(
      "mwbl_product_import_failures.csv",
      buildCsv([
        ["row", "import_sku", "status", "field", "value", "reason"],
        ...excelDisplayRows.map((row) => [row.row, row.importSku, row.status, row.field, row.value, row.reason])
      ]),
    );

    pushOperationLog(area, "실패 파일 다운로드", "검수 실패 행을 CSV로 생성", "neutral");
  };

  const handlePendingItemClick = (item: PendingItem) => {
    if (item.action === "ingredient") {
      setActiveView("ingredientReview");
      pushOperationLog("대시보드", "성분 검수 화면 이동", item.note, item.tone);
      return;
    }

    if (item.action === "duplicateProduct") {
      setActiveView("products");
      pushOperationLog("대시보드", "상품 중복 후보 확인", item.note, item.tone);
      return;
    }

    if (item.action === "excelFailure") {
      setActiveView("excelUpload");
      pushOperationLog("대시보드", "import 실패 행 확인", item.note, item.tone);
      return;
    }

    if (item.action === "imageFailure") {
      setActiveView("imageUpload");
      pushOperationLog("대시보드", "이미지 연결 화면 이동", item.note, item.tone);
      return;
    }

    setActiveView("dashboard");
    pushOperationLog("대시보드", "임베딩 자동 반영 확인", item.note, item.tone);
  };

  const renderSellerList = () => {
    const seller = MOCK_SELLERS.find((s) => s.id === selectedSellerId) ?? MOCK_SELLERS[0];
    const sellerTone = (status: SellerStatus): BadgeTone =>
      status === "입점중" ? "success" : status === "심사중" ? "warning" : "danger";
    return (
      <section className="admin-seller-layout admin-product-layout">
        <article className="admin-panel admin-product-panel">
          <div className="admin-panel-header">
            <div>
              <p className="admin-panel-eyebrow">셀러 운영</p>
              <h2>입점 셀러 관리</h2>
            </div>
          </div>
          <div className="admin-stats admin-seller-stats">
            <div className="admin-stat"><span>전체 셀러</span><strong>{MOCK_SELLER_STATS.total}</strong></div>
            <div className="admin-stat"><span>입점중</span><strong>{MOCK_SELLER_STATS.active}</strong></div>
            <div className="admin-stat"><span>심사중</span><strong>{MOCK_SELLER_STATS.review}</strong></div>
            <div className="admin-stat"><span>정지</span><strong>{MOCK_SELLER_STATS.suspended}</strong></div>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table admin-seller-table">
              <thead>
                <tr><th>상호</th><th>상태</th><th>등록 상품</th><th>최근 30일 매출</th><th>입점일</th></tr>
              </thead>
              <tbody>
                {MOCK_SELLERS.map((row) => (
                  <tr
                    key={row.id}
                    className={row.id === selectedSellerId ? "is-selected" : ""}
                    tabIndex={0}
                    aria-selected={row.id === selectedSellerId}
                    onClick={() => setSelectedSellerId(row.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedSellerId(row.id);
                      }
                    }}
                  >
                    <td>{row.name}</td>
                    <td><span className={`admin-badge ${sellerTone(row.status)}`}>{row.status}</span></td>
                    <td>{row.productCount.toLocaleString("ko-KR")}개</td>
                    <td>{row.monthlySales > 0 ? `${row.monthlySales.toLocaleString("ko-KR")}원` : "—"}</td>
                    <td>{row.joinedAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <aside className="admin-panel admin-seller-detail">
          <div className="admin-panel-header compact">
            <div>
              <p className="admin-panel-eyebrow">셀러 상세</p>
              <h2>{seller.name}</h2>
            </div>
            <span className={`admin-badge ${sellerTone(seller.status)}`}>{seller.status}</span>
          </div>
          <dl className="admin-detail-list">
            <div><dt>사업자등록번호</dt><dd>{seller.bizNo}</dd></div>
            <div><dt>대표자</dt><dd>{seller.owner}</dd></div>
            <div><dt>담당자</dt><dd>{seller.manager}</dd></div>
            <div><dt>연락처</dt><dd>{seller.contact}</dd></div>
            <div><dt>등록 상품</dt><dd>{seller.productCount.toLocaleString("ko-KR")}개</dd></div>
            <div><dt>검수 대기</dt><dd>{seller.pendingCount > 0 ? `${seller.pendingCount}건` : "없음"}</dd></div>
            <div><dt>최근 30일 매출</dt><dd>{seller.monthlySales > 0 ? `${seller.monthlySales.toLocaleString("ko-KR")}원` : "—"}</dd></div>
            <div><dt>최근 활동</dt><dd>{seller.lastActive}</dd></div>
          </dl>
        </aside>
      </section>
    );
  };
  const renderSellerInspection = () => {
    const inspection =
      MOCK_INSPECTIONS.find((r) => r.id === selectedInspectionId) ?? MOCK_INSPECTIONS[0];
    const inspectionTone = (state: InspectionState): BadgeTone =>
      state === "검수통과"
        ? "success"
        : state === "검수대기"
          ? "warning"
          : state === "보류"
            ? "neutral"
            : "danger";
    return (
      <section className="admin-seller-layout admin-product-layout">
        <article className="admin-panel admin-product-panel">
          <div className="admin-panel-header">
            <div>
              <p className="admin-panel-eyebrow">셀러 운영</p>
              <h2>셀러별 상품 검수</h2>
            </div>
          </div>
          <div className="admin-stats admin-seller-stats">
            <div className="admin-stat"><span>검수 대기 상품</span><strong>{MOCK_INSPECTION_STATS.waiting}</strong></div>
            <div className="admin-stat"><span>보류·반려</span><strong>{MOCK_INSPECTION_STATS.held}</strong></div>
            <div className="admin-stat"><span>성분 pending</span><strong>{MOCK_INSPECTION_STATS.ingredientPending}</strong></div>
            <div className="admin-stat"><span>이미지 미매칭</span><strong>{MOCK_INSPECTION_STATS.imageUnmatched}</strong></div>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table admin-seller-table admin-inspection-table">
              <thead>
                <tr>
                  <th>셀러</th>
                  <th>import job</th>
                  <th>상품명</th>
                  <th>seller_sku</th>
                  <th>검수 상태</th>
                  <th>실패/보류 사유</th>
                  <th>이미지</th>
                  <th>추천</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_INSPECTIONS.map((row) => (
                  <tr
                    key={row.id}
                    className={row.id === selectedInspectionId ? "is-selected" : ""}
                    tabIndex={0}
                    aria-selected={row.id === selectedInspectionId}
                    onClick={() => setSelectedInspectionId(row.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedInspectionId(row.id);
                      }
                    }}
                  >
                    <td>{row.seller}</td>
                    <td>{row.importJob}</td>
                    <td>{row.productName}</td>
                    <td>{row.sellerSku}</td>
                    <td><span className={`admin-badge ${inspectionTone(row.reviewState)}`}>{row.reviewState}</span></td>
                    <td>{row.failReason}</td>
                    <td>{row.imageState}</td>
                    <td>{row.recommendable}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <aside className="admin-panel admin-seller-detail">
          <div className="admin-panel-header compact">
            <div>
              <p className="admin-panel-eyebrow">검수 상세</p>
              <h2>{inspection.seller} · {inspection.productName}</h2>
            </div>
            <span className={`admin-badge ${inspectionTone(inspection.reviewState)}`}>{inspection.reviewState}</span>
          </div>
          <dl className="admin-detail-list">
            <div><dt>seller_sku</dt><dd>{inspection.sellerSku}</dd></div>
            <div><dt>import job</dt><dd>{inspection.importJob}</dd></div>
            <div><dt>성분 pending</dt><dd>{inspection.ingredientPending}</dd></div>
            <div><dt>이미지 매칭</dt><dd>{inspection.imageMatch}</dd></div>
            <div><dt>중복 후보</dt><dd>{inspection.duplicateCandidate}</dd></div>
            <div><dt>is_recommendable</dt><dd>{inspection.recommendable === "가능" ? "가능" : inspection.recommendable === "불가" ? "불가" : "대기"}</dd></div>
          </dl>
          <p className="admin-detail-note">
            검수 통과 전까지 추천·검색 인덱스에 반영되지 않습니다. mock 시안 · API 미확정.
          </p>
        </aside>
      </section>
    );
  };
  const renderSellerSettlement = () => {
    const settlement =
      MOCK_SETTLEMENTS.find((r) => r.id === selectedSettlementId) ?? MOCK_SETTLEMENTS[0];
    const settlementTone = (state: SettlementState): BadgeTone =>
      state === "정산완료"
        ? "success"
        : state === "정산예정"
          ? "warning"
          : state === "정산대기"
            ? "neutral"
            : "danger";
    const scheduledTotal = MOCK_SETTLEMENTS
      .filter((r) => r.state === "정산예정")
      .reduce((sum, r) => sum + r.payout, 0);
    const completedTotal = MOCK_SETTLEMENTS
      .filter((r) => r.state === "정산완료")
      .reduce((sum, r) => sum + r.payout, 0);
    const waitingCount = MOCK_SETTLEMENTS.filter((r) => r.state === "정산대기").length;
    const heldCount = MOCK_SETTLEMENTS.filter((r) => r.state === "보류").length;
    const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
    return (
      <section className="admin-seller-layout admin-product-layout">
        <article className="admin-panel admin-product-panel">
          <div className="admin-panel-header">
            <div>
              <p className="admin-panel-eyebrow">셀러 운영</p>
              <h2>셀러별 정산</h2>
            </div>
          </div>
          <div className="admin-stats admin-seller-stats">
            <div className="admin-stat"><span>정산 예정 총액</span><strong>{won(scheduledTotal)}</strong></div>
            <div className="admin-stat"><span>이번 달 정산 완료</span><strong>{won(completedTotal)}</strong></div>
            <div className="admin-stat"><span>정산 대기 셀러</span><strong>{waitingCount}</strong></div>
            <div className="admin-stat"><span>정산 보류</span><strong>{heldCount}</strong></div>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table admin-seller-table admin-settlement-table">
              <thead>
                <tr>
                  <th>셀러</th>
                  <th>판매액</th>
                  <th>취소/환불</th>
                  <th>수수료</th>
                  <th>정산 예정액</th>
                  <th>정산 상태</th>
                  <th>정산 예정일</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_SETTLEMENTS.map((row) => (
                  <tr
                    key={row.id}
                    className={row.id === selectedSettlementId ? "is-selected" : ""}
                    tabIndex={0}
                    aria-selected={row.id === selectedSettlementId}
                    onClick={() => setSelectedSettlementId(row.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedSettlementId(row.id);
                      }
                    }}
                  >
                    <td>{row.seller}</td>
                    <td>{won(row.sales)}</td>
                    <td>{row.refunds > 0 ? won(row.refunds) : "—"}</td>
                    <td>{won(row.fee)}</td>
                    <td>{won(row.payout)}</td>
                    <td><span className={`admin-badge ${settlementTone(row.state)}`}>{row.state}</span></td>
                    <td>{row.scheduledAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <aside className="admin-panel admin-seller-detail">
          <div className="admin-panel-header compact">
            <div>
              <p className="admin-panel-eyebrow">정산 상세</p>
              <h2>{settlement.seller}</h2>
            </div>
            <span className={`admin-badge ${settlementTone(settlement.state)}`}>{settlement.state}</span>
          </div>
          <dl className="admin-detail-list">
            <div><dt>판매액</dt><dd>{won(settlement.sales)}</dd></div>
            <div><dt>취소/환불액</dt><dd>{settlement.refunds > 0 ? won(settlement.refunds) : "—"}</dd></div>
            <div><dt>수수료</dt><dd>{won(settlement.fee)}</dd></div>
            <div><dt>정산 예정액</dt><dd>{won(settlement.payout)}</dd></div>
            <div><dt>정산 예정일</dt><dd>{settlement.scheduledAt}</dd></div>
            <div><dt>정산 완료일</dt><dd>{settlement.completedAt}</dd></div>
            <div><dt>계좌 확인</dt><dd>{settlement.accountVerified}</dd></div>
          </dl>
          <p className="admin-detail-note">
            읽기 전용 정산 시안입니다. 실제 지급·계좌 검증 연동은 미구현. mock 시안 · API 미확정.
          </p>
        </aside>
      </section>
    );
  };
  const renderDashboard = () => (
    <>
      <section className="admin-stats" aria-label="운영 지표">
        {stats.map((item) => (
          <article className="admin-stat" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </article>
        ))}
      </section>

      <section
        className="admin-dashboard-charts"
        aria-label="상품 구성과 처리 대기"
        style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.5fr)", gap: "16px", margin: "0 0 18px" }}
      >
        <article className="admin-panel">
          <div className="admin-panel-header">
            <div>
              <p>상품 구성</p>
              <h2>상품 상태 구성비</h2>
            </div>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: "22px" }}>
            <svg viewBox="0 0 140 140" role="img" aria-label="상품 상태 구성비 도넛 차트" style={{ width: "126px", height: "126px", flex: "0 0 auto", overflow: "visible" }}>
              {MOCK_STATUS_SEGMENTS.map((seg) => (
                <circle
                  key={seg.label}
                  cx="70"
                  cy="70"
                  r="52"
                  fill="none"
                  stroke={seg.color}
                  strokeWidth="16"
                  strokeDasharray={`${seg.dash} ${DONUT_CIRC - seg.dash}`}
                  strokeDashoffset={seg.offset}
                  transform="rotate(-90 70 70)"
                />
              ))}
              <text x="70" y="68" textAnchor="middle" style={{ fontSize: "20px", fontWeight: 700, fill: "#222" }}>24.6k</text>
              <text x="70" y="86" textAnchor="middle" style={{ fontSize: "10px", fill: "#8a9099" }}>전체 상품</text>
            </svg>
            <ul style={{ flex: "0 1 230px", maxWidth: "230px", listStyle: "none", margin: 0, padding: 0 }}>
              {MOCK_STATUS_BREAKDOWN.map((seg) => (
                <li key={seg.label} style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "11.5px", color: "#55585d", margin: "3px 0" }}>
                  <span style={{ width: "9px", height: "9px", borderRadius: "2px", background: seg.color, flex: "0 0 auto" }} />
                  <span style={{ flex: 1 }}>{seg.label}</span>
                  <b style={{ color: "#222" }}>{seg.value.toLocaleString("ko-KR")}</b>
                </li>
              ))}
            </ul>
          </div>
        </article>
        <article className="admin-panel">
          <div className="admin-panel-header">
            <div>
              <p>처리 대기</p>
              <h2>업무별 대기 건수</h2>
            </div>
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: "0 36px 0 0" }}>
            {MOCK_PENDING_QUEUE.map((bar) => (
              <li key={bar.label} style={{ display: "flex", alignItems: "center", gap: "9px", margin: "8px 0" }}>
                <span style={{ width: "78px", fontSize: "11.5px", color: "#55585d", textAlign: "right", flex: "0 0 auto" }}>{bar.label}</span>
                <span style={{ flex: 1, background: "#eef1f4", borderRadius: "5px", height: "17px", overflow: "hidden" }}>
                  <span style={{ display: "block", width: `${Math.max(1.5, (bar.value / MOCK_PENDING_MAX) * 100)}%`, height: "100%", background: bar.color, borderRadius: "5px" }} />
                </span>
                <b style={{ width: "56px", fontSize: "11.5px", color: "#222", textAlign: "right", flex: "0 0 auto" }}>{bar.value.toLocaleString("ko-KR")}</b>
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="admin-grid">

        <section className="admin-panel admin-pending-panel">
          <div className="admin-panel-header">
            <div>
              <p>처리 대기</p>
              <h2>오늘 확인할 일</h2>
            </div>
          </div>
          <div className="admin-pending-list">
            {pendingItems.map((item) => (
              <button
                className="admin-pending-item"
                key={item.label}
                onClick={() => handlePendingItemClick(item)}
                type="button"
              >
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.note}</small>
                </span>
                <b className={`admin-badge ${item.tone}`}>{item.status}</b>
                <i aria-hidden="true">›</i>
              </button>
            ))}
          </div>
        </section>

        <section className="admin-panel admin-import-panel">
          <div className="admin-panel-header">
            <div>
              <p>최근 import job</p>
              <h2>엑셀·이미지 업로드 결과</h2>
            </div>
            <button className="admin-secondary-button" onClick={() => handleFailureFile("import")} type="button">
              실패 파일
            </button>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table compact">
              <thead>
                <tr>
                  <th scope="col">시간</th>
                  <th scope="col">파일</th>
                  <th scope="col">성공</th>
                  <th scope="col">실패</th>
                  <th scope="col">상태</th>
                </tr>
              </thead>
              <tbody>
                {importRows.map((row) => (
                  <tr key={`${row.time}-${row.file}`}>
                    <td>{row.time}</td>
                    <td className="admin-file-name">{row.file}</td>
                    <td>{row.success}</td>
                    <td className={row.failed > 0 ? "admin-danger-text" : undefined}>{row.failed}</td>
                    <td>
                      <span className={`admin-badge ${row.tone}`}>{row.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel admin-operation-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>운영 액션</p>
              <h2>최근 화면 조작 로그</h2>
            </div>
            <span className="admin-badge neutral">local</span>
          </div>
          <div className="admin-operation-list">
            {operationLogs.map((log) => (
              <article className="admin-operation-item" key={log.id}>
                <span className={`admin-operation-dot ${log.tone}`} />
                <div>
                  <strong>{log.title}</strong>
                  <small>{log.area} · {log.detail}</small>
                </div>
                <time>{log.time}</time>
              </article>
            ))}
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>주문·결제</p>
              <h2>오늘 요약</h2>
            </div>
          </div>
          <dl className="admin-metric-list">
            {liveDashboardOrderSummary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>검색·추천</p>
              <h2>인덱스 상태</h2>
            </div>
            <span className="admin-badge success">정상</span>
          </div>
          <dl className="admin-metric-list">
            {indexSummary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>

      </section>
    </>
  );

  const renderExcelUpload = () => (
    <section className="admin-excel-layout">
      <section className="admin-panel admin-excel-main">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>엑셀 기반 상품 대량 등록</p>
            <h2>파일 미리보기 후 상품·재고·전성분을 등록합니다</h2>
          </div>
          <div className="admin-filter-row">
            <button className="admin-secondary-button" onClick={handleExcelTemplateDownload} type="button">
              템플릿
            </button>
            <button
              className="admin-secondary-button"
              disabled={bulkImport.submitting}
              onClick={() => void handleExcelPreview()}
              type="button"
            >
              미리보기
            </button>
            <button
              className="admin-primary-button"
              disabled={
                bulkImport.submitting ||
                excelPreviewRows.length === 0 ||
                excelClientIssues.length > 0
              }
              onClick={() => void handleExcelSubmit()}
              type="button"
            >
              {bulkImport.submitting ? "등록 중…" : "등록 실행"}
            </button>
          </div>
        </div>

        <div className="admin-upload-zone">
          <div>
            <strong>{excelFileName}</strong>
            <p>
              xlsx/csv 파일을 선택하세요. 전성분은 쉼표가 아닌 | 기호로 구분합니다.
            </p>
          </div>
          <label className="admin-upload-input">
            파일 선택
            <input
              accept=".xlsx,.csv"
              aria-label="상품 엑셀 파일 선택"
              disabled={bulkImport.submitting}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                excelFileRef.current = file;
                setExcelFileName(file.name);
                setExcelPreviewRows([]);
                setExcelClientIssues([]);
                setExcelFormError(null);
                bulkImport.reset();
                setExcelImportState("idle");
              }}
              type="file"
            />
          </label>
        </div>

        {(excelFormError || bulkImport.error) && (
          <div className="admin-state-banner danger" role="alert">
            <strong>등록 전 확인이 필요합니다</strong>
            <span>{excelFormError ?? bulkImport.error}</span>
          </div>
        )}

        {bulkImport.result?.reviewRefresh === "FAILED" && (
          <div className="admin-state-banner warning" role="status">
            <strong>상품 등록은 완료됐지만 검수 목록 갱신에 실패했습니다</strong>
            <span>잠시 후 검수 목록을 다시 확인하거나 운영 담당자에게 문의해 주세요.</span>
          </div>
        )}

        <div className="admin-excel-state-row">
          <span
            className={`admin-badge ${
              excelImportState === "done" && bulkImport.result?.reviewRefresh !== "FAILED"
                ? "success"
                : excelImportState === "submitting" || excelClientIssues.length > 0
                  ? "warning"
                  : excelImportState === "preview"
                    ? "success"
                    : "neutral"
            }`}
          >
            {excelImportState === "done"
              ? "등록 완료"
              : excelImportState === "submitting"
                ? "등록 중"
                : excelImportState === "preview"
                  ? "미리보기 완료"
                  : "파일 선택 전"}
          </span>
          <span>
            {excelImportState === "done"
              ? bulkImport.result?.reviewRefresh === "OK"
                ? "신규 pending 성분을 포함해 검수 목록을 갱신했습니다."
                : bulkImport.result?.reviewRefresh === "NOT_REQUIRED"
                  ? "새 pending 성분이 없어 검수 목록 갱신은 필요하지 않았습니다."
                  : "검수 목록 갱신 상태를 확인해 주세요."
              : excelImportState === "preview"
                ? excelClientIssues.length > 0
                  ? "형식 오류를 수정한 뒤 파일을 다시 선택해 미리보기를 실행해 주세요."
                  : "형식이 확인되었습니다. 등록 실행 시 서버가 브랜드·카테고리·성분을 다시 검증합니다."
                : "파일을 선택한 뒤 미리보기로 형식을 확인하고 등록을 실행하세요."}
          </span>
        </div>
      </section>

      <aside className="admin-panel admin-template-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>템플릿 컬럼</p>
            <h2>필수 입력값</h2>
          </div>
        </div>
        <div className="admin-template-list">
          {excelTemplateColumns.map((column) => (
            <div key={column.label}>
              <span>
                <strong>{column.label}</strong>
                <small>{column.note}</small>
              </span>
              <b className="admin-badge warning">{column.required}</b>
            </div>
          ))}
        </div>
      </aside>

      <section className="admin-panel admin-excel-summary-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>{bulkImport.result ? "등록 결과" : "미리보기"}</p>
            <h2>{bulkImport.result ? "부분 성공 요약" : "파일 형식 요약"}</h2>
          </div>
          <button
            className="admin-secondary-button"
            disabled={excelDisplayRows.length === 0}
            onClick={() => handleFailureFile("엑셀")}
            type="button"
          >
            결과 파일
          </button>
        </div>
        <div className="admin-excel-summary-grid">
          {excelSummaryRows.map((item) => (
            <article className={`admin-excel-summary ${item.tone}`} key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <section className="admin-panel admin-excel-failure-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>{bulkImport.result ? "등록 행" : "파싱 행"}</p>
            <h2>{bulkImport.result ? "CREATED · SKIPPED · FAILED 결과" : "등록 전 미리보기"}</h2>
          </div>
          <span className={`admin-badge ${bulkImport.result ? "neutral" : "warning"}`}>
            {bulkImport.result ? "서버 결과" : "형식 확인"}
          </span>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table admin-excel-table">
            <thead>
              <tr>
                <th scope="col">행</th>
                <th scope="col">import_sku</th>
                <th scope="col">상태</th>
                <th scope="col">필드</th>
                <th scope="col">값</th>
                <th scope="col">상세</th>
              </tr>
            </thead>
            <tbody>
              {excelDisplayRows.length > 0 ? (
                excelDisplayRows.map((row) => (
                  <tr key={`${row.row}-${row.status}-${row.field}`}>
                    <td>{row.row}</td>
                    <td className="admin-file-name">{row.importSku}</td>
                    <td>
                      <span
                        className={`admin-badge ${
                          row.status === "CREATED" || row.status === "형식 통과"
                            ? "success"
                            : row.status === "SKIPPED"
                              ? "warning"
                              : "danger"
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td>{row.field}</td>
                    <td>{row.value}</td>
                    <td>{row.reason}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6}>
                    <div className="admin-empty-state">
                      <strong>아직 미리보기 결과가 없습니다</strong>
                      <span>엑셀 파일을 선택한 뒤 미리보기를 실행하면 형식 오류를 바로 확인할 수 있습니다.</span>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );

  const renderImageUpload = () => <AdminImageBulkLinkSection parseSpreadsheet={parseExcelUpload} />;

  const renderStockPrice = () => <AdminInventoryPriceSection />;

  const viewTitle =
    activeView === "dashboard"
      ? "대시보드"
      : activeView === "products"
        ? "상품 조회"
        : activeView === "excelUpload"
          ? "엑셀 대량 등록"
          : activeView === "imageUpload"
          ? "이미지 등록"
          : activeView === "ingredientReview"
            ? "성분 매핑 검수"
            : activeView === "evidenceReview"
              ? "논문 근거 관리"
            : activeView === "stockPrice"
              ? "재고·가격"
              : activeView === "orderStatus"
                ? "주문·결제"
                : activeView === "sellers"
                  ? "셀러 관리"
                  : activeView === "sellerInspection"
                    ? "셀러별 상품 검수"
                    : activeView === "sellerSettlement"
                      ? "셀러별 정산"
                      : "상품 등록";

  if (access.status !== "authenticated") {
    return <AdminAccessNotice status={access.status} retry={access.retry} />;
  }

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar" aria-label="관리자 메뉴">
        <a className="admin-brand" href="/">
          <span className="admin-brand-mark">뭐</span>
          <span>
            <strong>뭐바를래</strong>
            <small>관리자</small>
          </span>
        </a>

        <nav className="admin-nav">
          {navItems.map((item) => (
            <Fragment key={item.view}>
              {navGroupHeadings[item.view] ? (
                <div className="admin-nav-group">{navGroupHeadings[item.view]}</div>
              ) : null}
              <button
                className={item.view === activeView ? "active" : ""}
                disabled={
                  ![
                    "dashboard",
                    "products",
                    "productForm",
                    "excelUpload",
                    "imageUpload",
                    "ingredientReview",
                    "evidenceReview",
                    "stockPrice",
                    "orderStatus",
                    "cancelClaims",
                    "sellers",
                    "sellerInspection",
                    "sellerSettlement"
                  ].includes(item.view)
                }
                onClick={() => {
                  if (
                    item.view === "dashboard" ||
                    item.view === "products" ||
                    item.view === "productForm" ||
                    item.view === "excelUpload" ||
                    item.view === "imageUpload" ||
                    item.view === "ingredientReview" ||
                    item.view === "evidenceReview" ||
                    item.view === "stockPrice" ||
                    item.view === "orderStatus" ||
                    item.view === "cancelClaims" ||
                    item.view === "sellers" ||
                    item.view === "sellerInspection" ||
                    item.view === "sellerSettlement"
                  ) {
                    if (item.view === "productForm") setEditingProductCode(null);
                    setActiveView(item.view);
                  }
                }}
                type="button"
              >
                {item.label}
              </button>
            </Fragment>
          ))}
          {navPendingGroups.map((group) => (
            <Fragment key={group.heading}>
              <div className="admin-nav-group">
                {group.heading}
                <span className="admin-nav-ready">준비중</span>
              </div>
              {group.items.map((label) => (
                <div className="admin-nav-disabled" key={label}>
                  {label}
                </div>
              ))}
            </Fragment>
          ))}
        </nav>

        <div className="admin-sidebar-status">
          <span>preview</span>
          <strong>필수 6개 화면 로컬 시안</strong>
        </div>
      </aside>

      <section className="admin-main" id="admin-dashboard">
        <header className="admin-topbar">
          <div>
            <div className="admin-title-row">
              <p>{viewTitle}</p>
              <span>운영 확장</span>
            </div>
            <h1>상품 운영 관리자</h1>
          </div>
          {toast && (
            <div className={`admin-toast ${toast.tone}`} role="status">
              <span>{toast.message}</span>
              <button aria-label="알림 닫기" onClick={() => setToast(null)} type="button">
                닫기
              </button>
            </div>
          )}
          <div className="admin-topbar-side">
            <span className="admin-scope-chip">현재 운영 범위: 본사 셀러</span>
            <span className="admin-scope-chip">권한: 플랫폼 상품 운영자</span>
            <time dateTime={todayIso}>{todayLabel}</time>
          </div>
        </header>

        {activeView === "dashboard" && renderDashboard()}
        {activeView === "excelUpload" && renderExcelUpload()}
        {activeView === "imageUpload" && renderImageUpload()}
        {activeView === "evidenceReview" && (
          <EvidenceCandidateReviewPanel
            onNotify={(message, tone) => setToast({ message, tone })}
          />
        )}
        {activeView === "stockPrice" && renderStockPrice()}
        <AdminIngredientMappingSection
          key="admin-ingredient-mapping"
          active={activeView === "ingredientReview"}
          onOperationLog={pushOperationLog}
        />
        <AdminProductSection
          key="admin-product"
          active={activeView === "products"}
          onEditProduct={(productCode) => {
            setEditingProductCode(productCode);
            setActiveView("productForm");
          }}
          onOperationLog={pushOperationLog}
        />
        <AdminProductFormSection
          key="admin-product-form"
          active={activeView === "productForm"}
          productCode={editingProductCode}
          onOperationLog={pushOperationLog}
          onSaved={setEditingProductCode}
        />
        <AdminOrderStatusSection
          key="admin-order-status"
          active={activeView === "orderStatus"}
          onOperationLog={pushOperationLog}
        />
        <AdminCancelClaimSection
          key="admin-cancel-claims"
          active={activeView === "cancelClaims"}
          onOperationLog={pushOperationLog}
        />
        {activeView === "sellers" && renderSellerList()}
        {activeView === "sellerInspection" && renderSellerInspection()}
        {activeView === "sellerSettlement" && renderSellerSettlement()}

        <p className="admin-footnote">
          판매중·검수 필요·품절 임박·이미지 누락·주문·import 수치는 화면 검토용 예시값입니다.
          검색/추천 인덱스와 pending 수치는 현재 프로젝트 실측 기준을 반영했습니다.
        </p>
      </section>
    </main>
  );
}

export default AdminDashboardPage;
