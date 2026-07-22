import { Fragment, useMemo, useRef, useState } from "react";
import ConfirmModal from "../components/ui/ConfirmModal";
import { AdminOrderStatusSection } from "../features/admin/orders/AdminOrderStatusSection";
import { AdminCancelClaimSection } from "../features/admin/cancelClaims/AdminCancelClaimSection";
import { AdminIngredientMappingSection } from "../features/admin/ingredientMappings/AdminIngredientMappingSection";
import { AdminInventoryPriceSection } from "../features/admin/inventoryPrice/AdminInventoryPriceSection";
import { AdminImageBulkLinkSection } from "../features/admin/imageBulkLink/AdminImageBulkLinkSection";
import { AdminProductFormSection } from "../features/admin/products/AdminProductFormSection";
import { AdminProductSection } from "../features/admin/products/AdminProductSection";
import type { AdminBulkImportRowInput } from "../features/admin/api/adminBulkImportApi";
import { useAdminBulkImport } from "../features/admin/bulkImport/useAdminBulkImport";
import { useAdminDashboardSummary } from "../features/admin/dashboard/useAdminDashboardSummary";
import { AdminAccessNotice } from "../features/admin/AdminAccessNotice";
import { useAdminAccess } from "../features/admin/hooks/useAdminAccess";

type AdminView =
  | "dashboard"
  | "products"
  | "productForm"
  | "excelUpload"
  | "imageUpload"
  | "ingredientReview"
  | "stockPrice"
  | "orderStatus"
  | "cancelClaims";
type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type ExcelImportState = "idle" | "preview" | "submitting" | "done";

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
type PendingAction = "ingredient" | "imageMissing";

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
  { label: "재고/가격 확인", view: "stockPrice" },
  { label: "주문 상태 확인", view: "orderStatus" },
  { label: "취소·클레임 관리", view: "cancelClaims" }
];

const navGroupHeadings: Partial<Record<AdminView, string>> = {
  products: "상품 운영",
  stockPrice: "추천 운영",
  orderStatus: "주문 운영"
};

const now = new Date();
const pad2 = (n: number) => String(n).padStart(2, "0");
const todayIso = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
const todayLabel = `${todayIso} ${["일", "월", "화", "수", "목", "금", "토"][now.getDay()]}`;

const DONUT_CIRC = 2 * Math.PI * 52;

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

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
};

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
  const [editingProductCode, setEditingProductCode] = useState<string | null>(null);
  const [productFormDirty, setProductFormDirty] = useState(false);
  const [pendingNavView, setPendingNavView] = useState<AdminView | null>(null);
  const [excelImportState, setExcelImportState] = useState<ExcelImportState>("idle");
  const [excelFileName, setExcelFileName] = useState("파일을 선택해 주세요");
  const excelFileRef = useRef<File | null>(null);
  const [excelPreviewRows, setExcelPreviewRows] = useState<AdminBulkImportRowInput[]>([]);
  const [excelClientIssues, setExcelClientIssues] = useState<ExcelClientIssue[]>([]);
  const [excelFormError, setExcelFormError] = useState<string | null>(null);
  const [excelPage, setExcelPage] = useState(1);
  const [excelPageSize, setExcelPageSize] = useState(PAGE_SIZE_OPTIONS[0]);
  const dashboardSummary = useAdminDashboardSummary({ enabled: activeView === "dashboard" });
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

  const excelTotalPages = Math.max(1, Math.ceil(excelDisplayRows.length / excelPageSize));
  const excelCurrentPage = Math.min(excelPage, excelTotalPages);
  const excelBlockPages = getBlockPages(excelCurrentPage, excelTotalPages);
  const excelBlockStart = excelBlockPages[0] ?? 1;
  const excelBlockEnd = excelBlockPages[excelBlockPages.length - 1] ?? 1;
  const excelHasPrevBlock = excelBlockStart > 1;
  const excelHasNextBlock = excelBlockEnd < excelTotalPages;
  const excelCurrentRows = excelDisplayRows.slice(
    (excelCurrentPage - 1) * excelPageSize,
    excelCurrentPage * excelPageSize,
  );

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

  const dashboardStatCards = useMemo(() => {
    const productStats = dashboardSummary.data?.productStats;
    return [
      { label: "전체 상품", value: productStats ? productStats.totalCount.toLocaleString("ko-KR") : "-" },
      { label: "추천 가능", value: productStats ? productStats.recommendableCount.toLocaleString("ko-KR") : "-" },
      { label: "이미지 미연결", value: productStats ? productStats.imageMissingCount.toLocaleString("ko-KR") : "-" }
    ];
  }, [dashboardSummary.data]);

  const stockStatusSegments = useMemo(() => {
    const breakdown = dashboardSummary.data?.stockStatusBreakdown;
    if (!breakdown) return [];
    const raw = [
      { label: "판매중", value: breakdown.inStockCount, color: "#3aa6d1" },
      { label: "품절 임박", value: breakdown.lowStockCount, color: "#f0b429" },
      { label: "품절", value: breakdown.soldOutCount, color: "#e57373" },
      { label: "숨김", value: breakdown.hiddenCount, color: "#9575cd" },
      { label: "재고 미확인", value: breakdown.unknownCount, color: "#c9cdd3" }
    ];
    const total = raw.reduce((sum, seg) => sum + seg.value, 0);
    if (total <= 0) return raw.map((seg) => ({ ...seg, dash: 0, offset: 0 }));

    // 판매중 비중이 압도적(예: 99%)이면 나머지 상태는 각도가 거의 0이라 도넛에서 안 보인다.
    // 값이 있는 항목은 최소 이 비율만큼은 보이게 하고, 그만큼을 큰 항목들에서 나눠 덜어낸다.
    // (같은 대시보드의 성분 검수 막대그래프도 Math.max(1.5, ...)로 동일한 문제를 처리한다.)
    const MIN_SLICE_FRACTION = 0.025;
    const smallLabels = new Set(
      raw.filter((seg) => seg.value > 0 && seg.value / total < MIN_SLICE_FRACTION).map((seg) => seg.label)
    );
    const reserved = smallLabels.size * MIN_SLICE_FRACTION;
    const largeTotal = raw
      .filter((seg) => !smallLabels.has(seg.label))
      .reduce((sum, seg) => sum + seg.value, 0);

    let acc = 0;
    return raw.map((seg) => {
      let fraction: number;
      if (seg.value <= 0) {
        fraction = 0;
      } else if (smallLabels.has(seg.label)) {
        fraction = MIN_SLICE_FRACTION;
      } else {
        fraction = largeTotal > 0 ? (seg.value / largeTotal) * (1 - reserved) : 0;
      }
      const dash = fraction * DONUT_CIRC;
      const segment = { ...seg, dash, offset: -acc };
      acc += dash;
      return segment;
    });
  }, [dashboardSummary.data]);

  const ingredientQueueBars = useMemo(() => {
    const summary = dashboardSummary.data?.ingredientReviewSummary;
    if (!summary) return [];
    return [
      { label: "신규 대기", value: summary.pendingCount, color: "#f0b429" },
      { label: "보류", value: summary.heldCount, color: "#e57373" },
      { label: "재검토", value: summary.needsReviewCount, color: "#3aa6d1" },
      { label: "미분류", value: summary.unclassifiedCount, color: "#9575cd" }
    ];
  }, [dashboardSummary.data]);
  const ingredientQueueMax = Math.max(1, ...ingredientQueueBars.map((bar) => bar.value));

  const pendingItems = useMemo<PendingItem[]>(() => {
    const summary = dashboardSummary.data;
    if (!summary) return [];
    const ingredientWaiting =
      summary.ingredientReviewSummary.pendingCount +
      summary.ingredientReviewSummary.heldCount +
      summary.ingredientReviewSummary.needsReviewCount;
    return [
      {
        label: "성분 매핑 검수 대기",
        note: `신규 대기 ${summary.ingredientReviewSummary.pendingCount.toLocaleString("ko-KR")}건 · 보류 ${summary.ingredientReviewSummary.heldCount.toLocaleString("ko-KR")}건 · 재검토 ${summary.ingredientReviewSummary.needsReviewCount.toLocaleString("ko-KR")}건`,
        status: ingredientWaiting > 0 ? "검수 필요" : "정상",
        tone: ingredientWaiting > 0 ? "warning" : "success",
        action: "ingredient"
      },
      {
        label: "이미지 미연결 상품",
        note: `대표·상세 이미지가 없는 상품 ${summary.productStats.imageMissingCount.toLocaleString("ko-KR")}개`,
        status: summary.productStats.imageMissingCount > 0 ? "연결 필요" : "정상",
        tone: summary.productStats.imageMissingCount > 0 ? "warning" : "success",
        action: "imageMissing"
      }
    ];
  }, [dashboardSummary.data]);

  const orderSummaryCards = useMemo(() => {
    const summary = dashboardSummary.data?.orderSummary;
    if (!summary) return [];
    return [
      { label: "결제 대기", value: summary.pendingPaymentCount.toLocaleString("ko-KR") },
      { label: "배송 준비", value: summary.preparingShipmentCount.toLocaleString("ko-KR") },
      { label: "배송 중", value: summary.shippedCount.toLocaleString("ko-KR") },
      { label: "취소 요청", value: summary.cancelRequestedCount.toLocaleString("ko-KR") },
      { label: "재고 예약", value: summary.reservedQuantityTotal.toLocaleString("ko-KR") }
    ];
  }, [dashboardSummary.data]);

  const claimPendingCount = dashboardSummary.data?.claimSummary.pendingCount ?? null;
  const pushOperationLog = (_area: string, title: string, detail: string, tone: BadgeTone = "success") => {
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
    setExcelPage(1);
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
    setExcelPage(1);
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

  const handleFailureFile = () => {
    downloadTextFile(
      "mwbl_product_import_failures.csv",
      buildCsv([
        ["row", "import_sku", "status", "field", "value", "reason"],
        ...excelDisplayRows.map((row) => [row.row, row.importSku, row.status, row.field, row.value, row.reason])
      ]),
    );

    pushOperationLog("엑셀", "실패 파일 다운로드", "검수 실패 행을 CSV로 생성", "neutral");
  };

  const navigateTo = (view: AdminView) => {
    if (view === "productForm") setEditingProductCode(null);
    setActiveView(view);
  };

  // 상품 등록/수정 화면에서 저장 안 한 수정 내용이 있는 채로 다른 메뉴로 이동하면 그 내용이
  // 그냥 사라진다. "재고/가격 확인으로 이동" 버튼과 같은 이유로 사이드바 이동도 확인을 받는다.
  const handleNavClick = (view: AdminView) => {
    if (activeView === "productForm" && productFormDirty) {
      setPendingNavView(view);
      return;
    }
    navigateTo(view);
  };

  const handlePendingItemClick = (item: PendingItem) => {
    if (item.action === "ingredient") {
      setActiveView("ingredientReview");
      return;
    }

    setActiveView("imageUpload");
  };

  const handleClaimWidgetClick = () => {
    setActiveView("cancelClaims");
  };

  const renderDashboard = () => {
    const summary = dashboardSummary.data;
    const summaryPending = dashboardSummary.loading && !summary;
    const summaryPlaceholder = summaryPending ? "불러오는 중입니다" : "정보 없음";

    return (
      <>
        {dashboardSummary.error && (
          <div className="admin-state-banner danger" role="alert">
            <strong>운영 현황을 불러오지 못했습니다</strong>
            <span>{dashboardSummary.error}</span>
            <button
              className="admin-secondary-button"
              onClick={() => void dashboardSummary.refresh()}
              type="button"
            >
              다시 시도
            </button>
          </div>
        )}

        <section className="admin-stats" aria-label="운영 지표" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
          {dashboardStatCards.map((item) => (
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
                <h2>재고 상태 구성비</h2>
              </div>
            </div>
            {summary ? (
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: "22px" }}>
                <svg viewBox="0 0 140 140" role="img" aria-label="재고 상태 구성비 도넛 차트" style={{ width: "126px", height: "126px", flex: "0 0 auto", overflow: "visible" }}>
                  {stockStatusSegments.map((seg) => (
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
                  <text x="70" y="68" textAnchor="middle" style={{ fontSize: "20px", fontWeight: 700, fill: "#222" }}>
                    {summary.productStats.totalCount.toLocaleString("ko-KR")}
                  </text>
                  <text x="70" y="86" textAnchor="middle" style={{ fontSize: "11px", fill: "#8a9099" }}>전체 상품</text>
                </svg>
                <ul style={{ flex: "0 1 260px", maxWidth: "260px", listStyle: "none", margin: 0, padding: 0 }}>
                  {stockStatusSegments.map((seg) => (
                    <li key={seg.label} style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "13px", color: "#55585d", margin: "5px 0" }}>
                      <span style={{ width: "9px", height: "9px", borderRadius: "2px", background: seg.color, flex: "0 0 auto" }} />
                      <span style={{ flex: 1 }}>{seg.label}</span>
                      <b style={{ color: "#222" }}>{seg.value.toLocaleString("ko-KR")}</b>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="admin-state-banner neutral">
                <strong>{summaryPlaceholder}</strong>
              </div>
            )}
          </article>
          <article className="admin-panel">
            <div className="admin-panel-header">
              <div>
                <p>처리 대기</p>
                <h2>성분 검수 대기 현황</h2>
              </div>
            </div>
            {summary ? (
              <ul style={{ listStyle: "none", margin: 0, padding: "0 24px 0 0" }}>
                {ingredientQueueBars.map((bar) => (
                  <li key={bar.label} style={{ display: "flex", alignItems: "center", gap: "9px", margin: "10px 0" }}>
                    <span style={{ width: "92px", fontSize: "13px", color: "#55585d", textAlign: "right", flex: "0 0 auto" }}>{bar.label}</span>
                    <span style={{ flex: 1, background: "#eef1f4", borderRadius: "5px", height: "17px", overflow: "hidden" }}>
                      <span style={{ display: "block", width: `${Math.max(1.5, (bar.value / ingredientQueueMax) * 100)}%`, height: "100%", background: bar.color, borderRadius: "5px" }} />
                    </span>
                    <b style={{ width: "68px", fontSize: "13px", color: "#222", textAlign: "right", flex: "0 0 auto" }}>{bar.value.toLocaleString("ko-KR")}</b>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="admin-state-banner neutral">
                <strong>{summaryPlaceholder}</strong>
              </div>
            )}
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
            {summary ? (
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
            ) : (
              <div className="admin-state-banner neutral">
                <strong>{summaryPlaceholder}</strong>
              </div>
            )}
          </section>

          <section className="admin-panel">
            <div className="admin-panel-header compact">
              <div>
                <p>주문·결제</p>
                <h2>현재 주문·결제 현황</h2>
              </div>
            </div>
            {summary ? (
              <dl className="admin-metric-list">
                {orderSummaryCards.map((item) => (
                  <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <div className="admin-state-banner neutral">
                <strong>{summaryPlaceholder}</strong>
              </div>
            )}
          </section>

          <section className="admin-panel admin-full-width-panel">
            <div className="admin-panel-header compact">
              <div>
                <p>주문 운영</p>
                <h2>클레임 대기 현황</h2>
              </div>
            </div>
            {claimPendingCount === null ? (
              <div className="admin-state-banner neutral">
                <strong>{summaryPlaceholder}</strong>
              </div>
            ) : (
              <div className="admin-pending-list">
                <button className="admin-pending-item" onClick={handleClaimWidgetClick} type="button">
                  <span>
                    <strong>처리 대기 클레임</strong>
                    <small>반품·교환·환불 요청 중 아직 처리하지 않은 건</small>
                  </span>
                  <b className={`admin-badge ${claimPendingCount > 0 ? "warning" : "success"}`}>
                    {claimPendingCount.toLocaleString("ko-KR")}건
                  </b>
                  <i aria-hidden="true">›</i>
                </button>
              </div>
            )}
          </section>

        </section>
      </>
    );
  };

  const renderExcelUpload = () => (
    <section className="admin-excel-layout">
      <section className="admin-panel admin-excel-main">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>엑셀 기반 상품 대량 등록</p>
            <h2>상품·재고·전성분 일괄 등록</h2>
          </div>
          <div className="admin-filter-row">
            <button
              className="admin-secondary-button admin-light-button"
              onClick={handleExcelTemplateDownload}
              type="button"
            >
              템플릿
            </button>
            <button
              className="admin-secondary-button admin-light-button"
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
                setExcelPage(1);
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
            className="admin-secondary-button admin-light-button"
            disabled={excelDisplayRows.length === 0}
            onClick={() => handleFailureFile()}
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

        <div className="admin-list-toolbar">
          <div className="admin-page-size">
            <label htmlFor="admin-excel-upload-page-size">페이지당</label>
            <select
              id="admin-excel-upload-page-size"
              onChange={(event) => {
                setExcelPageSize(Number(event.target.value));
                setExcelPage(1);
              }}
              value={excelPageSize}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}개
                </option>
              ))}
            </select>
          </div>
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
              {excelCurrentRows.length > 0 ? (
                excelCurrentRows.map((row) => (
                  <tr key={`${row.row}-${row.status}-${row.field}`}>
                    <td>{row.row}</td>
                    <td className="admin-file-name" title={row.importSku}>
                      {row.importSku}
                    </td>
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

        {excelDisplayRows.length > 0 && (
          <div className="admin-pagination-row">
            <div className="admin-pagination">
              <button
                className="admin-pagination-jump"
                disabled={excelCurrentPage <= 1}
                onClick={() => setExcelPage(1)}
                type="button"
              >
                처음
              </button>
              <button
                className="admin-pagination-jump"
                disabled={!excelHasPrevBlock}
                onClick={() => setExcelPage(excelBlockStart - 1)}
                type="button"
              >
                이전
              </button>
              {excelBlockPages.map((entry) => (
                <button
                  className={`admin-pagination-page${entry === excelCurrentPage ? " active" : ""}`}
                  key={entry}
                  onClick={() => setExcelPage(entry)}
                  type="button"
                >
                  {entry}
                </button>
              ))}
              <button
                className="admin-pagination-jump"
                disabled={!excelHasNextBlock}
                onClick={() => setExcelPage(excelBlockEnd + 1)}
                type="button"
              >
                다음
              </button>
              <button
                className="admin-pagination-jump"
                disabled={excelCurrentPage >= excelTotalPages}
                onClick={() => setExcelPage(excelTotalPages)}
                type="button"
              >
                맨끝
              </button>
            </div>
          </div>
        )}
      </section>
    </section>
  );

  const renderImageUpload = () => <AdminImageBulkLinkSection parseSpreadsheet={parseExcelUpload} />;

  const renderStockPrice = () => <AdminInventoryPriceSection />;

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
                    "stockPrice",
                    "orderStatus",
                    "cancelClaims"
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
                    item.view === "stockPrice" ||
                    item.view === "orderStatus" ||
                    item.view === "cancelClaims"
                  ) {
                    handleNavClick(item.view);
                  }
                }}
                type="button"
              >
                {item.label}
              </button>
            </Fragment>
          ))}
        </nav>
      </aside>

      <section className="admin-main" id="admin-dashboard">
        <header className="admin-topbar">
          <div />
          {toast && (
            <div className={`admin-toast ${toast.tone}`} role="status">
              <span>{toast.message}</span>
              <button aria-label="알림 닫기" onClick={() => setToast(null)} type="button">
                닫기
              </button>
            </div>
          )}
          <div className="admin-topbar-side">
            <time dateTime={todayIso}>{todayLabel}</time>
          </div>
        </header>

        {activeView === "dashboard" && renderDashboard()}
        {activeView === "excelUpload" && renderExcelUpload()}
        {activeView === "imageUpload" && renderImageUpload()}
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
          onDirtyChange={setProductFormDirty}
          onOperationLog={pushOperationLog}
          onSaved={setEditingProductCode}
          onViewInventory={() => setActiveView("stockPrice")}
        />
        <AdminOrderStatusSection key="admin-order-status" active={activeView === "orderStatus"} />
        <AdminCancelClaimSection key="admin-cancel-claims" active={activeView === "cancelClaims"} />
      </section>
      <ConfirmModal
        compact
        message="저장하지 않은 수정 내용이 있습니다. 지금 이동하면 사라집니다. 계속할까요?"
        onCancel={() => setPendingNavView(null)}
        onConfirm={() => {
          const view = pendingNavView;
          setPendingNavView(null);
          if (view) navigateTo(view);
        }}
        open={pendingNavView !== null}
      />
    </main>
  );
}

export default AdminDashboardPage;
