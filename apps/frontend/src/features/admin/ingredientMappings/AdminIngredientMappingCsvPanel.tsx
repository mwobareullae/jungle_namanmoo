import { useMemo, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  IngredientMappingCsvPreview,
  IngredientMappingCsvRowInput,
  applyIngredientMappingCsv,
  downloadPendingIngredientMappingCsv,
  previewIngredientMappingCsv,
  refreshIngredientMappingPendingGroups
} from "../api/adminIngredientMappingCsvApi";

type SpreadsheetParser = (file: File) => Promise<string[][] | null>;
type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type PreviewBatch = {
  rows: IngredientMappingCsvRowInput[];
  preview: IngredientMappingCsvPreview;
};

type Props = {
  parseSpreadsheet: SpreadsheetParser;
  onApplied: () => Promise<unknown>;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
};

const REQUIRED_HEADERS = [
  "action",
  "pending_code",
  "normalized_source_name",
  "expected_connection_count",
  "target_ingredient_code",
  "target_name_ko",
  "target_name_en",
  "decision_reason",
  "source_reference"
];
const BATCH_SIZE = 1000;

const describeError = (error: unknown, fallback: string): string =>
  (error as Partial<ApiError> | undefined)?.message ?? fallback;

const chunkRows = (rows: IngredientMappingCsvRowInput[]): IngredientMappingCsvRowInput[][] => {
  const chunks: IngredientMappingCsvRowInput[][] = [];
  for (let index = 0; index < rows.length; index += BATCH_SIZE) {
    chunks.push(rows.slice(index, index + BATCH_SIZE));
  }
  return chunks;
};

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export function AdminIngredientMappingCsvPanel({
  parseSpreadsheet,
  onApplied,
  onOperationLog
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewBatches, setPreviewBatches] = useState<PreviewBatch[]>([]);
  const [busy, setBusy] = useState<"download" | "preview" | "apply" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [resultMessage, setResultMessage] = useState<string | null>(null);

  const summary = useMemo(
    () =>
      previewBatches.reduce(
        (total, batch) => ({
          total: total.total + batch.preview.summary.total,
          valid: total.valid + batch.preview.summary.valid,
          invalid: total.invalid + batch.preview.summary.invalid,
          alreadyApplied: total.alreadyApplied + batch.preview.summary.alreadyApplied,
          connectionCount: total.connectionCount + batch.preview.summary.connectionCount
        }),
        { total: 0, valid: 0, invalid: 0, alreadyApplied: 0, connectionCount: 0 }
      ),
    [previewBatches]
  );
  const invalidRows = useMemo(
    () => previewBatches.flatMap((batch) => batch.preview.rows.filter((row) => row.status === "INVALID")),
    [previewBatches]
  );
  const confirmationPhrase = `${summary.valid}건 적용`;
  const canApply =
    busy === null &&
    summary.valid > 0 &&
    summary.invalid === 0 &&
    confirmation.trim() === confirmationPhrase;

  const resetPreview = () => {
    setPreviewBatches([]);
    setConfirmation("");
    setResultMessage(null);
    setProgress(0);
  };

  const parseRows = async (): Promise<IngredientMappingCsvRowInput[] | null> => {
    if (!file) {
      setError("먼저 서버에서 내려받아 작성한 CSV 또는 XLSX 파일을 선택해 주세요.");
      return null;
    }
    const grid = await parseSpreadsheet(file);
    if (!grid || grid.length < 2) {
      setError("데이터 행이 있는 CSV 또는 XLSX 파일만 사용할 수 있습니다.");
      return null;
    }
    const headers = grid[0].map((cell) => (cell ?? "").replace(/^\ufeff/, "").trim());
    const missingHeaders = REQUIRED_HEADERS.filter((header) => !headers.includes(header));
    if (missingHeaders.length > 0) {
      setError(`필수 컬럼이 없습니다: ${missingHeaders.join(", ")}`);
      return null;
    }
    const column = (name: string) => headers.indexOf(name);
    const issues: string[] = [];
    const rows: IngredientMappingCsvRowInput[] = [];
    grid.slice(1).forEach((cells, index) => {
      const value = (name: string) => String(cells[column(name)] ?? "").trim();
      if (cells.every((cell) => String(cell ?? "").trim() === "")) return;
      const rowNumber = index + 2;
      const action = value("action");
      const connectionCountText = value("expected_connection_count");
      const expectedConnectionCount = Number(connectionCountText);
      if (action !== "MAP_EXISTING" && action !== "CREATE_AND_MAP") {
        issues.push(`${rowNumber}행 action은 MAP_EXISTING 또는 CREATE_AND_MAP이어야 합니다.`);
      }
      if (!value("pending_code") || !value("normalized_source_name") || !value("target_ingredient_code")) {
        issues.push(`${rowNumber}행의 pending/원문/target 코드가 비어 있습니다.`);
      }
      if (!Number.isInteger(expectedConnectionCount) || expectedConnectionCount < 1) {
        issues.push(`${rowNumber}행 expected_connection_count는 1 이상의 정수여야 합니다.`);
      }
      rows.push({
        rowNumber,
        action: action as IngredientMappingCsvRowInput["action"],
        pendingCode: value("pending_code"),
        normalizedSourceName: value("normalized_source_name"),
        expectedConnectionCount,
        targetIngredientCode: value("target_ingredient_code"),
        targetNameKo: value("target_name_ko") || null,
        targetNameEn: value("target_name_en") || null,
        decisionReason: value("decision_reason") || null,
        sourceReference: value("source_reference") || null
      });
    });
    if (issues.length > 0) {
      setError(`${issues.slice(0, 5).join(" ")}${issues.length > 5 ? ` 외 ${issues.length - 5}건` : ""}`);
      return null;
    }
    if (rows.length === 0) {
      setError("적용할 데이터 행이 없습니다.");
      return null;
    }
    return rows;
  };

  const downloadCsv = async () => {
    setBusy("download");
    setError(null);
    try {
      saveBlob(await downloadPendingIngredientMappingCsv(), "mwbl_ingredient_mapping_pending.csv");
    } catch (caught) {
      setError(describeError(caught, "서버 미판정 CSV를 내려받지 못했습니다."));
    } finally {
      setBusy(null);
    }
  };

  const runPreview = async () => {
    setBusy("preview");
    setError(null);
    resetPreview();
    try {
      const rows = await parseRows();
      if (!rows) return;
      const chunks = chunkRows(rows);
      const batches: PreviewBatch[] = [];
      for (let index = 0; index < chunks.length; index += 1) {
        const batchRows = chunks[index];
        batches.push({ rows: batchRows, preview: await previewIngredientMappingCsv(batchRows) });
        setProgress(Math.round(((index + 1) / chunks.length) * 100));
      }
      setPreviewBatches(batches);
    } catch (caught) {
      setError(describeError(caught, "CSV dry-run을 완료하지 못했습니다."));
    } finally {
      setBusy(null);
    }
  };

  const applyCsv = async () => {
    if (!canApply) return;
    setBusy("apply");
    setError(null);
    setResultMessage(null);
    setProgress(0);
    let completedBatches = 0;
    let applied = 0;
    let moved = 0;
    let collapsed = 0;
    let created = 0;
    let refreshFailed = false;
    try {
      for (let index = 0; index < previewBatches.length; index += 1) {
        const batch = previewBatches[index];
        const result = await applyIngredientMappingCsv(
          batch.rows,
          batch.preview.previewDigest,
          index === previewBatches.length - 1
        );
        applied += result.applied;
        moved += result.movedConnections;
        collapsed += result.collapsedDuplicates;
        created += result.createdCanonicals;
        refreshFailed ||= result.reviewRefresh === "FAILED";
        completedBatches += 1;
        setProgress(Math.round((completedBatches / previewBatches.length) * 100));
      }
      const detail = `${applied.toLocaleString("ko-KR")}개 그룹, ${moved.toLocaleString("ko-KR")}개 연결 이동, ${collapsed.toLocaleString("ko-KR")}개 중복 병합, 신규 canonical ${created.toLocaleString("ko-KR")}개`;
      let refreshWarning = "";
      if (refreshFailed) {
        try {
          await refreshIngredientMappingPendingGroups();
        } catch {
          refreshWarning = " 미판정 목록 갱신은 실패했으므로 재시도가 필요합니다.";
        }
      }
      onOperationLog("성분", "CSV 일괄 매핑 완료", detail, "success");
      resetPreview();
      setResultMessage(`${detail} 완료.${refreshWarning} 고객 검색 색인은 배포 환경에서 재색인이 필요합니다.`);
      await onApplied();
    } catch (caught) {
      let recoveryMessage = "";
      if (completedBatches > 0) {
        try {
          await refreshIngredientMappingPendingGroups();
          await onApplied();
          recoveryMessage = " 완료된 배치 기준으로 미판정 목록을 갱신했습니다.";
        } catch {
          recoveryMessage = " 미판정 목록 갱신도 실패했으므로 갱신 API를 재시도해야 합니다.";
        }
      }
      setError(
        `${completedBatches}개 배치까지 반영되었습니다.${recoveryMessage} 목록을 다시 export해 dry-run을 재실행해 주세요. ${describeError(caught, "일괄 적용 중 오류가 발생했습니다.")}`
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="admin-panel admin-ingredient-csv-panel">
      <div className="admin-panel-header compact">
        <div>
          <p>운영 DB 대량 처리</p>
          <h2>미판정 성분 CSV 일괄 매핑</h2>
        </div>
        <div className="admin-filter-row">
          <button className="admin-secondary-button admin-light-button" disabled={busy !== null} onClick={() => void downloadCsv()} type="button">
            {busy === "download" ? "내려받는 중..." : "서버 미판정 CSV 다운로드"}
          </button>
          <input
            accept=".csv,.xlsx"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setError(null);
              resetPreview();
            }}
            ref={fileInputRef}
            type="file"
          />
          <button className="admin-primary-button" disabled={busy !== null || !file} onClick={() => void runPreview()} type="button">
            {busy === "preview" ? `dry-run ${progress}%` : "dry-run 실행"}
          </button>
        </div>
      </div>

      <p className="admin-muted-copy">
        다운로드한 행에서 target 컬럼을 작성하세요. 기존 성분은 MAP_EXISTING, 복합 원료를 새 성분으로 만들 때만 CREATE_AND_MAP을 사용하고 생성 근거를 입력해야 합니다. 미판정으로 남길 행은 업로드 파일에서 제외하세요.
      </p>
      {file && <p className="admin-muted-copy">선택 파일: {file.name}</p>}
      {error && <div className="admin-state-banner danger"><span>{error}</span></div>}
      {resultMessage && <div className="admin-state-banner success"><span>{resultMessage}</span></div>}

      {previewBatches.length > 0 && (
        <>
          <div className="admin-excel-summary-grid admin-ingredient-summary-grid">
            <article className="admin-excel-summary neutral"><span>전체</span><strong>{summary.total.toLocaleString("ko-KR")}</strong></article>
            <article className="admin-excel-summary success"><span>적용 가능</span><strong>{summary.valid.toLocaleString("ko-KR")}</strong></article>
            <article className="admin-excel-summary danger"><span>오류</span><strong>{summary.invalid.toLocaleString("ko-KR")}</strong></article>
            <article className="admin-excel-summary neutral"><span>이미 적용</span><strong>{summary.alreadyApplied.toLocaleString("ko-KR")}</strong></article>
          </div>
          <div className="admin-state-banner warning">
            <span>적용 대상 연결 {summary.connectionCount.toLocaleString("ko-KR")}건. 오류가 1건이라도 있으면 전체 파일 적용을 시작할 수 없습니다.</span>
          </div>
          {invalidRows.length > 0 && (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead><tr><th>CSV 행</th><th>pending 코드</th><th>오류 코드</th><th>설명</th></tr></thead>
                <tbody>
                  {invalidRows.slice(0, 100).map((row) => (
                    <tr key={`${row.rowNumber}-${row.pendingCode}`}><td>{row.rowNumber}</td><td>{row.pendingCode}</td><td>{row.errorCode}</td><td>{row.message}</td></tr>
                  ))}
                </tbody>
              </table>
              {invalidRows.length > 100 && <p className="admin-muted-copy">오류는 처음 100건만 표시합니다.</p>}
            </div>
          )}
          {summary.invalid === 0 && summary.valid > 0 && (
            <div className="admin-filter-row">
              <label>
                확인 문구 <strong>{confirmationPhrase}</strong>
                <input onChange={(event) => setConfirmation(event.target.value)} placeholder={confirmationPhrase} value={confirmation} />
              </label>
              <button className="admin-primary-button" disabled={!canApply} onClick={() => void applyCsv()} type="button">
                {busy === "apply" ? `적용 ${progress}%` : "운영 DB에 적용"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
