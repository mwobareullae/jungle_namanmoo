import { useMemo, useRef, useState } from "react";

import type { AdminImageBulkLinkRowInput } from "../api/adminImageBulkLinkApi";
import { useAdminImageBulkLink } from "./useAdminImageBulkLink";

type SpreadsheetParser = (file: File) => Promise<string[][] | null>;
type ImageType = "thumbnail" | "detail";
type ClientIssue = {
  rowNumber: number;
  importSku: string;
  field: string;
  value: string;
  message: string;
};
type DisplayRow = ClientIssue & {
  status: "형식 통과" | "형식 오류" | "UPDATED" | "SKIPPED" | "FAILED";
};
type BadgeTone = "success" | "warning" | "danger" | "neutral";

const REQUIRED_HEADERS = ["import_sku", "image_type", "display_order", "storage_key"];
const IMPORT_SKU_PATTERN = /^[A-Z0-9][A-Z0-9._-]{0,63}$/;
const ABSOLUTE_URL_PATTERN = /^[a-z][a-z\d+.-]*:\/\//i;

const templateColumns = [
  { name: "import_sku", note: "M3-B 대량등록 상품 식별자" },
  { name: "image_type", note: "thumbnail 또는 detail" },
  { name: "display_order", note: "thumbnail=0, detail은 1 이상" },
  { name: "storage_key", note: "S3 원본 기준 상대경로" }
];

const buildCsv = (rows: string[][]) =>
  rows.map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")).join("\n");

const downloadTemplate = () => {
  const blob = new Blob(
    [
      "\uFEFF",
      buildCsv([
        REQUIRED_HEADERS,
        ["IMPORT_001", "thumbnail", "0", "products/IMPORT_001/thumbnail.jpg"],
        ["IMPORT_001", "detail", "1", "products/IMPORT_001/detail_01.jpg"]
      ])
    ],
    { type: "text/csv;charset=utf-8" }
  );
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "mwbl_image_bulk_link_template.csv";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

const badgeTone = (status: DisplayRow["status"]): BadgeTone => {
  if (status === "UPDATED" || status === "형식 통과") return "success";
  if (status === "SKIPPED") return "neutral";
  return "danger";
};

const statusLabel = (status: DisplayRow["status"]) =>
  status === "UPDATED" ? "연결됨" : status === "SKIPPED" ? "변경 없음" : status;

export function AdminImageBulkLinkSection({
  parseSpreadsheet
}: {
  parseSpreadsheet: SpreadsheetParser;
}) {
  const imageBulkLink = useAdminImageBulkLink();
  const fileRef = useRef<File | null>(null);
  const [fileName, setFileName] = useState("파일을 선택해 주세요");
  const [previewRows, setPreviewRows] = useState<AdminImageBulkLinkRowInput[]>([]);
  const [clientIssues, setClientIssues] = useState<ClientIssue[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "preview" | "submitting" | "done">("idle");

  const displayRows = useMemo<DisplayRow[]>(() => {
    if (imageBulkLink.result) {
      return imageBulkLink.result.rows.map((resultRow) => {
        const source = previewRows[resultRow.rowNumber - 1];
        return {
          rowNumber: resultRow.rowNumber,
          importSku: resultRow.importSku ?? source?.importSku ?? "(누락)",
          field: resultRow.field ?? "-",
          value:
            resultRow.field === "storage_key"
              ? (source?.storageKey ?? "-")
              : resultRow.field === "image_type"
                ? (source?.imageType ?? "-")
                : resultRow.field === "display_order"
                  ? String(source?.displayOrder ?? "-")
                  : (resultRow.importSku ?? source?.importSku ?? "-"),
          message:
            resultRow.status === "UPDATED"
              ? "이미지 슬롯을 연결했습니다."
              : resultRow.status === "SKIPPED"
                ? "같은 storage_key가 이미 연결되어 있습니다."
                : (resultRow.message ?? "연결하지 못했습니다."),
          status: resultRow.status
        };
      });
    }

    return previewRows.map((row, index) => {
      const issue = clientIssues.find((candidate) => candidate.rowNumber === index + 1);
      return {
        rowNumber: index + 1,
        importSku: row.importSku || "(누락)",
        field: issue?.field ?? "-",
        value: issue?.value ?? row.storageKey,
        message: issue?.message ?? "서버 연결 전 형식 검사를 통과했습니다.",
        status: issue ? "형식 오류" : "형식 통과"
      };
    });
  }, [clientIssues, imageBulkLink.result, previewRows]);

  const previewFile = async () => {
    const file = fileRef.current;
    if (!file) {
      setFormError("먼저 CSV 또는 XLSX 파일을 선택해 주세요.");
      return;
    }

    const grid = await parseSpreadsheet(file);
    if (!grid || grid.length < 2) {
      setFormError("데이터 행이 있는 CSV 또는 XLSX 파일만 사용할 수 있습니다.");
      return;
    }
    if (grid.length - 1 > 1000) {
      setFormError(
        "한 번에 최대 1,000행까지 연결할 수 있습니다. 파일을 나누어 다시 시도해 주세요."
      );
      return;
    }

    const header = grid[0].map((cell) => (cell || "").replace(/^\ufeff/, "").trim());
    const missing = REQUIRED_HEADERS.filter((name) => !header.includes(name));
    if (missing.length > 0) {
      setFormError(`필수 컬럼이 없습니다: ${missing.join(", ")}`);
      return;
    }

    const columnIndex = (name: string) => header.indexOf(name);
    const parsedRows: AdminImageBulkLinkRowInput[] = [];
    const issues: ClientIssue[] = [];
    const seenSlots = new Set<string>();
    grid.slice(1).forEach((cells, index) => {
      const rowNumber = index + 1;
      const valueOf = (name: string) => (cells[columnIndex(name)] ?? "").toString().trim();
      const importSku = valueOf("import_sku");
      const imageType = valueOf("image_type") as ImageType;
      const displayOrderRaw = valueOf("display_order");
      const storageKey = valueOf("storage_key");
      const parsed = {
        importSku,
        imageType,
        displayOrder: Number(displayOrderRaw),
        storageKey
      };
      parsedRows.push(parsed);

      const fail = (field: string, value: string, message: string) => {
        if (issues.some((issue) => issue.rowNumber === rowNumber)) return;
        issues.push({ rowNumber, importSku: importSku || "(누락)", field, value, message });
      };

      if (!IMPORT_SKU_PATTERN.test(importSku)) {
        fail("import_sku", importSku, "대문자 영문·숫자·._-만 사용해 1~64자로 입력해 주세요.");
      }
      if (imageType !== "thumbnail" && imageType !== "detail") {
        fail("image_type", imageType, "thumbnail 또는 detail로 입력해 주세요.");
      }
      if (!/^\d+$/.test(displayOrderRaw)) {
        fail("display_order", displayOrderRaw, "0 이상의 정수로 입력해 주세요.");
      } else if (imageType === "thumbnail" && parsed.displayOrder !== 0) {
        fail("display_order", displayOrderRaw, "thumbnail의 display_order는 0이어야 합니다.");
      } else if (imageType === "detail" && parsed.displayOrder < 1) {
        fail("display_order", displayOrderRaw, "detail의 display_order는 1 이상이어야 합니다.");
      }
      if (!storageKey) {
        fail("storage_key", storageKey, "storage_key는 비어 있을 수 없습니다.");
      } else if (
        storageKey.length > 500 ||
        ABSOLUTE_URL_PATTERN.test(storageKey) ||
        storageKey.includes("..")
      ) {
        fail(
          "storage_key",
          storageKey,
          "상대 storage_key만 입력해 주세요. 완성 URL과 .. 경로는 사용할 수 없습니다."
        );
      }

      const slot = `${importSku}\u0000${imageType}\u0000${displayOrderRaw}`;
      if (
        importSku &&
        (imageType === "thumbnail" || imageType === "detail") &&
        /^\d+$/.test(displayOrderRaw)
      ) {
        if (seenSlots.has(slot)) {
          fail(
            "display_order",
            displayOrderRaw,
            "같은 import_sku·image_type·display_order 슬롯은 한 번만 입력할 수 있습니다."
          );
        }
        seenSlots.add(slot);
      }
    });

    setPreviewRows(parsedRows);
    setClientIssues(issues);
    setFormError(null);
    imageBulkLink.reset();
    setPhase("preview");
  };

  const submit = async () => {
    if (previewRows.length === 0) {
      setFormError("먼저 파일을 선택하고 미리보기를 실행해 주세요.");
      return;
    }
    if (clientIssues.length > 0) {
      setFormError("형식 오류를 수정한 뒤 파일을 다시 선택하고 미리보기를 실행해 주세요.");
      return;
    }

    setFormError(null);
    setPhase("submitting");
    const result = await imageBulkLink.submit(previewRows);
    setPhase(result ? "done" : "preview");
  };

  const errorMessage = formError ?? imageBulkLink.error;
  const summary = imageBulkLink.result?.summary;

  return (
    <section className="admin-excel-layout admin-image-layout">
      <section className="admin-panel admin-excel-main">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>상품 이미지 운영</p>
            <h2>파일 미리보기 후 이미지 storage_key를 연결합니다</h2>
          </div>
          <div className="admin-filter-row">
            <button className="admin-secondary-button" onClick={downloadTemplate} type="button">
              템플릿
            </button>
            <button
              className="admin-secondary-button"
              disabled={phase === "submitting"}
              onClick={() => void previewFile()}
              type="button"
            >
              미리보기
            </button>
            <button
              className="admin-primary-button"
              disabled={
                phase === "submitting" || previewRows.length === 0 || clientIssues.length > 0
              }
              onClick={() => void submit()}
              type="button"
            >
              {phase === "submitting" ? "연결 중" : "연결 실행"}
            </button>
          </div>
        </div>

        <div className="admin-upload-zone">
          <div>
            <strong>{fileName}</strong>
            <p>
              CSV/XLSX에 CDN 원본 기준 상대 storage_key를 입력합니다. 이미지 파일 자체는 업로드하지
              않습니다.
            </p>
          </div>
          <label className="admin-upload-input">
            파일 선택
            <input
              accept=".csv,.xlsx"
              aria-label="이미지 연결 CSV 또는 XLSX 파일 선택"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                fileRef.current = file;
                setFileName(file?.name ?? "파일을 선택해 주세요");
                setPreviewRows([]);
                setClientIssues([]);
                setFormError(null);
                imageBulkLink.reset();
                setPhase("idle");
              }}
              type="file"
            />
          </label>
        </div>

        {errorMessage && (
          <div className="admin-state-banner danger">
            <strong>연결 전 확인이 필요합니다</strong>
            <span>{errorMessage}</span>
          </div>
        )}
        {phase === "done" && summary && (
          <div className={`admin-state-banner ${summary.failed > 0 ? "warning" : "success"}`}>
            <strong>이미지 연결을 완료했습니다</strong>
            <span>
              연결 {summary.updated}행 · 변경 없음 {summary.skipped}행 · 실패 {summary.failed}행
            </span>
          </div>
        )}
        <div className="admin-state-banner neutral">
          <strong>운영 전제</strong>
          <span>
            S3에 원본과 resized/w400·resized/w1200 파일을 먼저 올린 뒤, 원본 storage_key만 입력해
            주세요.
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
          {templateColumns.map((column) => (
            <div key={column.name}>
              <span>
                <strong>{column.name}</strong>
                <small>{column.note}</small>
              </span>
              <b>필수</b>
            </div>
          ))}
        </div>
      </aside>

      <section className="admin-panel admin-excel-summary-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>{phase === "done" ? "연결 결과" : "파일 형식 요약"}</p>
            <h2>{phase === "done" ? "UPDATED · SKIPPED · FAILED" : "등록 전 미리보기"}</h2>
          </div>
        </div>
        <div className="admin-excel-summary-grid">
          {[
            { label: "총 행", value: summary?.total ?? previewRows.length, tone: "neutral" },
            {
              label: phase === "done" ? "연결됨" : "형식 통과",
              value: summary?.updated ?? previewRows.length - clientIssues.length,
              tone: "success"
            },
            { label: "변경 없음", value: summary?.skipped ?? 0, tone: "neutral" },
            {
              label: phase === "done" ? "실패" : "형식 오류",
              value: summary?.failed ?? clientIssues.length,
              tone: "danger"
            }
          ].map((item) => (
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
            <p>{phase === "done" ? "연결 결과" : "파싱 행"}</p>
            <h2>이미지 연결 미리보기</h2>
          </div>
          <span className="admin-badge neutral">최대 1,000행</span>
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
              {displayRows.length > 0 ? (
                displayRows.map((row) => (
                  <tr key={row.rowNumber}>
                    <td>{row.rowNumber}</td>
                    <td>{row.importSku}</td>
                    <td>
                      <span className={`admin-badge ${badgeTone(row.status)}`}>
                        {statusLabel(row.status)}
                      </span>
                    </td>
                    <td>{row.field}</td>
                    <td className="admin-file-name">{row.value}</td>
                    <td>{row.message}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6}>
                    <div className="admin-empty-state">
                      <strong>아직 미리보기 결과가 없습니다</strong>
                      <span>
                        파일을 선택한 뒤 미리보기를 실행하면 형식 오류를 먼저 확인할 수 있습니다.
                      </span>
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
}
