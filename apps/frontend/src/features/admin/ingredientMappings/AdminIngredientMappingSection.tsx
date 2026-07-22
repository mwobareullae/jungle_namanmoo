import { useState } from "react";

import {
  IngredientMappingAction,
  IngredientMappingCandidateFilter,
  IngredientMappingCandidateType,
  IngredientMappingFinalDisposition,
  IngredientMappingMatchSource,
  IngredientMappingNonMappingFinalDisposition,
  IngredientMappingStatus,
  IngredientMappingStatusFilter,
  IngredientMappingSort
} from "../api/adminIngredientMappingApi";
import { useAdminIngredientMappings } from "./useAdminIngredientMappings";

// 관리자 성분 매핑 검수 조회 화면 (P1-M2-A Chunk 4, 조회 전용).
// 승인/보류/반려/재검토(쓰기)는 다음 Chunk. 부모와는 onOperationLog 만 공유한다.
// 로딩 UX: 최초 진입 skeleton, 필터·검색·페이지 이동 중에는 기존 목록 유지 + 갱신 표시.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type AdminIngredientMappingSectionProps = {
  active: boolean;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
};

const STATUS_LABELS: Record<IngredientMappingStatus, string> = {
  PENDING: "미판정",
  HELD: "보류",
  APPROVED: "승인",
  REJECTED: "반려"
  , NEEDS_REVIEW: "재검토 필요"
};

const STATUS_TONES: Record<IngredientMappingStatus, BadgeTone> = {
  PENDING: "warning",
  HELD: "review",
  APPROVED: "success",
  REJECTED: "danger"
  , NEEDS_REVIEW: "warning"
};

const FINAL_DISPOSITION_LABELS: Record<IngredientMappingFinalDisposition, string> = {
  MAPPED: "정식 성분 연결",
  NON_INGREDIENT: "성분 아님",
  COMPOUND_MATERIAL: "복합 원료",
  SOURCE_ERROR: "원문 오류·데이터 정정 필요",
  UNRESOLVABLE: "근거 부족으로 매핑 불가"
};

const NON_MAPPING_FINAL_DISPOSITIONS: IngredientMappingNonMappingFinalDisposition[] = [
  "NON_INGREDIENT",
  "COMPOUND_MATERIAL",
  "SOURCE_ERROR",
  "UNRESOLVABLE"
];

const MATCH_SOURCE_LABELS: Record<IngredientMappingMatchSource, string> = {
  ALIAS_EXACT: "별칭 정확 일치",
  CANONICAL_NAME_EXACT: "표준명 정확 일치"
};

const CANDIDATE_TYPE_LABELS: Record<IngredientMappingCandidateType, string> = {
  CANONICAL_EXACT_MATCH: "정식명 정확 일치",
  ALIAS_EXACT_MATCH: "별칭 정확 일치",
  EXACT_MATCH_CONFLICT: "정확 일치 충돌",
  NO_EXACT_MATCH: "정확 일치 없음"
};

const ACTION_LABELS: Record<IngredientMappingAction, string> = {
  APPROVE: "승인",
  HOLD: "보류",
  REJECT: "반려",
  REOPEN: "재검토"
};

const ACTION_VARIANTS: Record<IngredientMappingAction, string> = {
  APPROVE: "approve",
  HOLD: "hold",
  REJECT: "reject",
  REOPEN: "reopen"
};

const ACTION_HELPERS: Record<IngredientMappingAction, string> = {
  APPROVE: "canonical 성분을 선택해 연결합니다.",
  HOLD: "근거가 부족하면 사유와 함께 보류합니다.",
  REJECT: "매핑하지 않는 사유를 이력에 남깁니다.",
  REOPEN: "기존 판정을 다시 검토합니다."
};

const STATUS_FILTER_OPTIONS: Array<{ value: IngredientMappingStatusFilter; label: string }> = [
  { value: "ALL", label: "전체" },
  { value: "PENDING", label: "미판정" },
  { value: "HELD", label: "보류" },
  { value: "APPROVED", label: "승인" },
  { value: "REJECTED", label: "반려" }
];

STATUS_FILTER_OPTIONS.splice(3, 0, { value: "NEEDS_REVIEW", label: "재검토 필요" });
STATUS_FILTER_OPTIONS[0] = { value: "ALL", label: "미분류 전체" };

const SKELETON_ROWS = Array.from({ length: 6 });

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
};

const formatCount = (value: number): string => value.toLocaleString("ko-KR");

const formatEventState = (
  status: IngredientMappingStatus,
  targetIngredientCode: string | null,
  finalDisposition: IngredientMappingFinalDisposition | null
): string =>
  `${STATUS_LABELS[status]}${
    finalDisposition ? ` · ${FINAL_DISPOSITION_LABELS[finalDisposition]}` : ""
  }${targetIngredientCode ? ` (${targetIngredientCode})` : ""}`;

export function AdminIngredientMappingSection({
  active,
  onOperationLog
}: AdminIngredientMappingSectionProps) {
  const {
    statusFilter,
    finalDispositionFilter,
    sort,
    candidateFilter,
    queryInput,
    setQueryInput,
    items,
    summary,
    pagination,
    page,
    pageSize,
    loading,
    error,
    hasLoaded,
    applySearch,
    setStatusFilter,
    setFinalDispositionFilter,
    setSort,
    setCandidateFilter,
    setPageSize,
    resetFilters,
    refresh,
    goToPage,
    selectedKey,
    detail,
    detailLoading,
    detailError,
    selectMapping,
    decisionSubmitting,
    decisionError,
    clearDecisionError,
    approve,
    hold,
    reject,
    reopen,
    bulkPreview,
    bulkPreviewLoading,
    bulkSubmitting,
    bulkError,
    loadKciaBulkApprovalPreview,
    approveKciaBulk,
    canonicalResults,
    canonicalSearching,
    canonicalError,
    searchCanonicals,
    resetCanonicalSearch
  } = useAdminIngredientMappings({ enabled: active });

  const totalPages = pagination?.totalPages ?? 1;
  const blockPages = getBlockPages(page, totalPages);
  const blockStart = blockPages[0] ?? 1;
  const blockEnd = blockPages[blockPages.length - 1] ?? 1;
  const hasPrevBlock = blockStart > 1;
  const hasNextBlock = blockEnd < totalPages;

  const [expandedEvents, setExpandedEvents] = useState(false);

  // 판정 모달 로컬 상태
  const [activeAction, setActiveAction] = useState<IngredientMappingAction | null>(null);
  const [reasonInput, setReasonInput] = useState("");
  const [canonicalQuery, setCanonicalQuery] = useState("");
  const [selectedTargetCode, setSelectedTargetCode] = useState<string | null>(null);
  const [selectedTargetName, setSelectedTargetName] = useState<string | null>(null);
  const [finalDisposition, setFinalDisposition] = useState<IngredientMappingNonMappingFinalDisposition | null>(null);
  const [evidenceSourceUrl, setEvidenceSourceUrl] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkSelectedKeys, setBulkSelectedKeys] = useState<string[]>([]);
  const [bulkConfirmation, setBulkConfirmation] = useState("");

  const bulkKey = (pendingCode: string, normalizedSourceName: string) =>
    `${pendingCode}::${normalizedSourceName}`;
  const selectedBulkItems =
    bulkPreview?.items.filter((item) =>
      bulkSelectedKeys.includes(bulkKey(item.pendingCode, item.normalizedSourceName))
    ) ?? [];
  const bulkConfirmationPhrase = `승인 ${selectedBulkItems.length}`;
  const allBulkItemsSelected =
    (bulkPreview?.items.length ?? 0) > 0 &&
    (bulkPreview?.items.every((item) =>
      bulkSelectedKeys.includes(bulkKey(item.pendingCode, item.normalizedSourceName))
    ) ?? false);

  const toggleSelectAllBulkItems = () => {
    if (!bulkPreview) return;
    setBulkSelectedKeys(
      allBulkItemsSelected
        ? []
        : bulkPreview.items.map((item) => bulkKey(item.pendingCode, item.normalizedSourceName))
    );
  };

  const openBulkApproval = async () => {
    const preview = await loadKciaBulkApprovalPreview();
    if (preview === null) return;
    setBulkSelectedKeys(preview.items.map((item) => bulkKey(item.pendingCode, item.normalizedSourceName)));
    setBulkConfirmation("");
    setBulkModalOpen(true);
  };

  const closeBulkApproval = () => {
    if (bulkSubmitting) return;
    setBulkModalOpen(false);
    setBulkConfirmation("");
  };

  const toggleBulkItem = (pendingCode: string, normalizedSourceName: string) => {
    const key = bulkKey(pendingCode, normalizedSourceName);
    setBulkSelectedKeys((previous) =>
      previous.includes(key) ? previous.filter((item) => item !== key) : [...previous, key]
    );
  };

  const submitBulkApproval = async () => {
    if (
      bulkSubmitting ||
      selectedBulkItems.length === 0 ||
      bulkConfirmation.trim() !== bulkConfirmationPhrase
    ) {
      return;
    }
    const result = await approveKciaBulk(selectedBulkItems);
    if (result === null) return;
    onOperationLog(
      "성분",
      "KCIA 별칭 후보 일괄 승인",
      `${result.approvedCount}개 pending 그룹을 승인했습니다. ${result.batchReference}`,
      "success"
    );
    setBulkModalOpen(false);
    setBulkConfirmation("");
  };

  const openAction = (action: IngredientMappingAction) => {
    clearDecisionError();
    setActiveAction(action);
    setReasonInput("");
    setCanonicalQuery("");
    setFinalDisposition(null);
    setEvidenceSourceUrl("");
    setSourceReference("");
    resetCanonicalSearch();
    // 승인 모달은 추천이 있으면 기본 target 으로 채운다.
    if (action === "APPROVE" && detail?.suggestion) {
      setSelectedTargetCode(detail.suggestion.targetIngredientCode);
      setSelectedTargetName(detail.suggestion.targetIngredientName);
    } else {
      setSelectedTargetCode(null);
      setSelectedTargetName(null);
    }
  };

  const closeAction = () => {
    setActiveAction(null);
    setReasonInput("");
    setCanonicalQuery("");
    setSelectedTargetCode(null);
    setSelectedTargetName(null);
    setFinalDisposition(null);
    setEvidenceSourceUrl("");
    setSourceReference("");
    clearDecisionError();
    resetCanonicalSearch();
  };

  const handleCanonicalSearch = (event: React.FormEvent) => {
    event.preventDefault();
    void searchCanonicals(canonicalQuery);
  };

  const pickTarget = (code: string, name: string) => {
    setSelectedTargetCode(code);
    setSelectedTargetName(name);
  };

  const reasonRequired = activeAction !== null && activeAction !== "APPROVE";
  const reasonTrimmed = reasonInput.trim();
  const evidenceSourceUrlTrimmed = evidenceSourceUrl.trim();
  const sourceReferenceTrimmed = sourceReference.trim();
  const finalDispositionRequiresEvidence =
    finalDisposition !== null && finalDisposition !== "NON_INGREDIENT";
  const canSubmitAction =
    activeAction !== null &&
    !decisionSubmitting &&
    (activeAction === "APPROVE"
      ? selectedTargetCode !== null
      : activeAction === "REJECT"
        ? reasonTrimmed.length > 0 &&
          finalDisposition !== null &&
          (!finalDispositionRequiresEvidence ||
            evidenceSourceUrlTrimmed.length > 0 ||
            sourceReferenceTrimmed.length > 0)
        : reasonTrimmed.length > 0);

  const submitAction = async () => {
    if (!activeAction || !canSubmitAction) return;
    const reasonValue = reasonTrimmed || null;
    let succeeded = false;
    if (activeAction === "APPROVE" && selectedTargetCode) {
      succeeded = await approve(selectedTargetCode, reasonValue);
    } else if (activeAction === "HOLD") {
      succeeded = await hold(reasonTrimmed);
    } else if (activeAction === "REJECT") {
      if (finalDisposition === null) return;
      succeeded = await reject(
        reasonTrimmed,
        finalDisposition,
        evidenceSourceUrlTrimmed || null,
        sourceReferenceTrimmed || null
      );
    } else if (activeAction === "REOPEN") {
      succeeded = await reopen(reasonTrimmed);
    }
    if (succeeded) {
      onOperationLog("성분", `성분 매핑 ${ACTION_LABELS[activeAction]}`, detail?.rawName ?? "", "success");
      closeAction();
    }
  };

  const handleSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    applySearch();
  };

  const handleRowSelect = (pendingCode: string, normalizedSourceName: string) => {
    setExpandedEvents(false);
    void selectMapping(pendingCode, normalizedSourceName);
  };

  const handleRefresh = async () => {
    const succeeded = await refresh();
    if (succeeded) return;
    onOperationLog("성분", "성분 매핑 목록 새로고침 실패", "잠시 후 다시 시도해 주세요.", "danger");
  };

  const summaryCards = summary
    ? [
        { label: "미판정", value: formatCount(summary.pendingCount), tone: "warning" as const },
        { label: "보류", value: formatCount(summary.heldCount), tone: "neutral" as const },
        { label: "승인", value: formatCount(summary.approvedCount), tone: "success" as const },
        { label: "반려", value: formatCount(summary.rejectedCount), tone: "danger" as const }
      ]
    : [];

  const showSkeleton = loading && !hasLoaded;
  const showUpdating = loading && hasLoaded;
  const showEmpty = hasLoaded && !loading && items.length === 0;

  return (
    <section className="admin-ingredient-layout" hidden={!active}>
      <section className="admin-panel admin-ingredient-hero">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>성분 매핑 검수</p>
            <h2>pending 성분을 내부 canonical 성분에 연결</h2>
          </div>
          <div className="admin-filter-row">
            <button
              className="admin-secondary-button admin-light-button"
              disabled={loading || bulkPreviewLoading || bulkSubmitting}
              onClick={() => void openBulkApproval()}
              type="button"
            >
              {bulkPreviewLoading ? "KCIA 후보 조회 중…" : "KCIA 후보 일괄 승인"}
            </button>
            <button className="admin-primary-button" disabled={loading} onClick={handleRefresh} type="button">
              새로고침
            </button>
          </div>
        </div>

        <div className="admin-excel-summary-grid admin-ingredient-summary-grid">
          {summaryCards.map((item) => (
            <article className={`admin-excel-summary ${item.tone}`} key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
      </section>

      {bulkError && !bulkModalOpen && (
        <div className="admin-state-banner danger">
          <span>{bulkError}</span>
        </div>
      )}

      <section className="admin-panel admin-ingredient-queue">
        <div className="admin-panel-header compact">
          <div>
            <p>검수 대기열</p>
            <h2>pending 원문 그룹</h2>
          </div>
          <form className="admin-filter-row" onSubmit={handleSearchSubmit}>
            <select
              className="admin-secondary-button"
              onChange={(event) =>
                setStatusFilter(event.target.value as IngredientMappingStatusFilter)
              }
              value={statusFilter}
            >
              {STATUS_FILTER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              aria-label="최종 분류 필터"
              className="admin-secondary-button"
              onChange={(event) =>
                setFinalDispositionFilter(event.target.value as IngredientMappingFinalDisposition | "ALL")
              }
              value={finalDispositionFilter}
            >
              <option value="ALL">최종 분류 전체</option>
              <option value="MAPPED">정식 성분 연결</option>
              <option value="NON_INGREDIENT">성분 아님</option>
              <option value="COMPOUND_MATERIAL">복합 원료</option>
              <option value="SOURCE_ERROR">원문 오류</option>
              <option value="UNRESOLVABLE">근거 부족</option>
            </select>
            <select
              aria-label="검수 우선순위"
              className="admin-secondary-button"
              onChange={(event) => setSort(event.target.value as IngredientMappingSort)}
              value={sort}
            >
              <option value="CODE_ASC">코드순</option>
              <option value="CONNECTION_DESC">연결 상품 많은 순</option>
            </select>
            <select
              aria-label="처리 후보"
              className="admin-secondary-button"
              onChange={(event) =>
                setCandidateFilter(event.target.value as IngredientMappingCandidateFilter)
              }
              value={candidateFilter}
            >
              <option value="ALL">처리 후보 전체</option>
              <option value="CANONICAL_EXACT_MATCH">정식명 정확 일치</option>
              <option value="ALIAS_EXACT_MATCH">별칭 정확 일치</option>
              <option value="EXACT_MATCH_CONFLICT">정확 일치 충돌</option>
              <option value="NO_EXACT_MATCH">정확 일치 없음</option>
            </select>
            <input
              aria-label="성분명·코드 검색"
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="성분명·코드 검색"
              type="search"
              value={queryInput}
            />
            <button className="admin-secondary-button admin-light-button" disabled={loading} type="submit">
              검색
            </button>
            <button className="admin-secondary-button admin-light-button" onClick={resetFilters} type="button">
              초기화
            </button>
          </form>
        </div>

        {error && (
          <div className="admin-state-banner danger">
            <strong>성분 매핑 목록 오류</strong>
            <span>{error}</span>
          </div>
        )}
        {showUpdating && (
          <div className="admin-state-banner neutral">
            <strong>목록 갱신 중…</strong>
            <span>기존 목록을 유지한 채 최신 결과를 불러오고 있습니다.</span>
          </div>
        )}

        <div className="admin-list-toolbar">
          <div className="admin-page-size">
            <label htmlFor="admin-ingredient-page-size">페이지당</label>
            <select
              id="admin-ingredient-page-size"
              onChange={(event) => setPageSize(Number(event.target.value))}
              value={pageSize}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}개
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="admin-table-wrap admin-ingredient-table-scroll">
          <table className="admin-table admin-ingredient-table">
            <thead>
              <tr>
                <th scope="col">pending 성분</th>
                <th scope="col">추천 canonical</th>
                <th scope="col">연결</th>
                <th scope="col">근거</th>
                <th scope="col">상태</th>
              </tr>
            </thead>
            <tbody>
              {showSkeleton &&
                SKELETON_ROWS.map((_, index) => (
                  <tr className="admin-skeleton-row" key={`skeleton-${index}`}>
                    <td colSpan={5}>
                      <span className="admin-skeleton-bar" />
                    </td>
                  </tr>
                ))}

              {!showSkeleton &&
                items.map((row) => {
                  const key = `${row.pendingCode}::${row.normalizedSourceName}`;
                  return (
                    <tr
                      className={key === selectedKey ? "selected" : undefined}
                      key={key}
                      onClick={() => handleRowSelect(row.pendingCode, row.normalizedSourceName)}
                    >
                      <td>
                        <button
                          aria-label={`${row.rawName} 성분 상세 보기`}
                          className="admin-ingredient-row-select"
                          onClick={(event) => {
                            event.stopPropagation();
                            handleRowSelect(row.pendingCode, row.normalizedSourceName);
                          }}
                          type="button"
                        >
                          <strong className="admin-product-name" title={row.rawName}>
                            {row.rawName}
                          </strong>
                          <small className="admin-product-code" title={row.pendingCode}>
                            {row.pendingCode}
                          </small>
                        </button>
                      </td>
                      <td>
                        {row.suggestion ? (
                          row.suggestion.targetIngredientName
                        ) : (
                          <small className="admin-product-code">직접 검색 필요</small>
                        )}
                      </td>
                      <td>
                        <strong>{formatCount(row.connectionCount)}</strong>
                        <small className="admin-product-code">상품 {formatCount(row.productCount)}</small>
                      </td>
                      <td>
                        <small className="admin-product-code">
                          {CANDIDATE_TYPE_LABELS[row.candidate.candidateType]}
                          {row.suggestion ? ` · ${MATCH_SOURCE_LABELS[row.suggestion.matchSource]}` : ""}
                        </small>
                      </td>
                      <td>
                        <span className={`admin-badge ${STATUS_TONES[row.status]}`}>
                          {STATUS_LABELS[row.status]}
                        </span>
                      </td>
                    </tr>
                  );
                })}

              {showEmpty && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    {error ? "목록을 불러오지 못했습니다." : "조건에 맞는 검수 대상이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="admin-pagination-row">
          <div className="admin-pagination">
            <button
              className="admin-pagination-jump"
              disabled={page <= 1 || loading}
              onClick={() => goToPage(1)}
              type="button"
            >
              처음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={!hasPrevBlock || loading}
              onClick={() => goToPage(blockStart - 1)}
              type="button"
            >
              이전
            </button>
            {blockPages.map((entry) => (
              <button
                className={`admin-pagination-page${entry === page ? " active" : ""}`}
                disabled={loading}
                key={entry}
                onClick={() => goToPage(entry)}
                type="button"
              >
                {entry}
              </button>
            ))}
            <button
              className="admin-pagination-jump"
              disabled={!hasNextBlock || loading}
              onClick={() => goToPage(blockEnd + 1)}
              type="button"
            >
              다음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={page >= totalPages || loading}
              onClick={() => goToPage(totalPages)}
              type="button"
            >
              맨끝
            </button>
          </div>
        </div>
      </section>

      <aside className="admin-panel admin-ingredient-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 성분</p>
            <h2>{detail ? detail.rawName : "상세 정보"}</h2>
          </div>
          {detail && (
            <span className={`admin-badge ${STATUS_TONES[detail.status]}`}>
              {STATUS_LABELS[detail.status]}
            </span>
          )}
        </div>

        <div className="admin-ingredient-detail-scroll">
        {detailError && (
          <div className="admin-state-banner danger">
            <strong>성분 상세 오류</strong>
            <span>{detailError}</span>
          </div>
        )}

        {detailLoading && !detail ? (
          <div className="admin-state-banner neutral">
            <strong>상세 정보를 불러오는 중입니다</strong>
            <span>잠시만 기다려 주세요.</span>
          </div>
        ) : detail ? (
          <>
            <div className="admin-detail-body">
              <p className="admin-metric-group-title">기본 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>pending code</dt>
                  <dd>{detail.pendingCode}</dd>
                </div>
                <div>
                  <dt>pending 성분명</dt>
                  <dd>{detail.pendingIngredientName}</dd>
                </div>
                <div>
                  <dt>정규화명</dt>
                  <dd>{detail.normalizedSourceName}</dd>
                </div>
                <div>
                  <dt>연결</dt>
                  <dd>
                    {formatCount(detail.connectionCount)} (상품 {formatCount(detail.productCount)})
                  </dd>
                </div>
              </dl>

              <p className="admin-metric-group-title">추천 정보</p>
              <dl className="admin-metric-list">
                <div>
                  <dt>추천 canonical</dt>
                  <dd>
                    {detail.suggestion
                      ? `${detail.suggestion.targetIngredientName} (${MATCH_SOURCE_LABELS[detail.suggestion.matchSource]})`
                      : "없음 — canonical 직접 검색 필요"}
                  </dd>
                </div>
                <div>
                  <dt>처리 후보</dt>
                  <dd>
                    {CANDIDATE_TYPE_LABELS[detail.candidate.candidateType]}
                    {` · ${detail.candidate.evidence}`}
                  </dd>
                </div>
              </dl>

              {detail.decision && (
                <>
                  <p className="admin-metric-group-title">관리자 판정</p>
                  <dl className="admin-metric-list">
                    <div>
                      <dt>판정 결과</dt>
                      <dd>
                        {STATUS_LABELS[detail.decision.status]}
                        {detail.decision.finalDisposition
                          ? ` · ${FINAL_DISPOSITION_LABELS[detail.decision.finalDisposition]}`
                          : ""}
                        {detail.decision.targetIngredientName
                          ? ` → ${detail.decision.targetIngredientName}`
                          : ""}
                        {detail.decision.decisionReason ? ` · ${detail.decision.decisionReason}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt>판정자</dt>
                      <dd>관리자 #{detail.decision.reviewedByUserId}</dd>
                    </div>
                    <div>
                      <dt>판정 시각</dt>
                      <dd>{detail.decision.reviewedAt}</dd>
                    </div>
                  </dl>
                </>
              )}
            </div>

            {detail.rawNameVariants.length > 0 && (
              <div className="admin-ingredient-variants">
                <p className="admin-product-code">원문 표기 ({detail.rawNameVariants.length})</p>
                <ul>
                  {detail.rawNameVariants.map((variant) => (
                    <li key={variant.rawName}>
                      <span>{variant.rawName}</span>
                      <small className="admin-product-code">{formatCount(variant.connectionCount)}</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.sampleProducts.length > 0 && (
              <div className="admin-ingredient-samples">
                <p className="admin-product-code">대표 상품 ({detail.sampleProducts.length})</p>
                <ul>
                  {detail.sampleProducts.map((product) => (
                    <li key={product.productCode}>
                      <span>{product.productName}</span>
                      <small className="admin-product-code">{product.rawName}</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.events.length > 0 && (
              <div className="admin-ingredient-events">
                <button
                  className="admin-secondary-button"
                  onClick={() => setExpandedEvents((prev) => !prev)}
                  type="button"
                >
                  결정 이력 {detail.events.length}건 {expandedEvents ? "접기" : "펼치기"}
                </button>
                {expandedEvents && (
                  <ul>
                    {detail.events.map((event, index) => (
                      <li key={`${event.createdAt}-${index}`}>
                        <span>
                          {event.fromStatus
                            ? `${formatEventState(
                                event.fromStatus,
                                event.fromTargetIngredientCode,
                                event.fromFinalDisposition
                              )} → `
                            : "최초 판정 → "}
                          {formatEventState(
                            event.toStatus,
                            event.toTargetIngredientCode,
                            event.toFinalDisposition
                          )}
                        </span>
                        <small className="admin-product-code">
                          {event.createdAt} · 관리자 #{event.actorId}
                          {event.reason ? ` · ${event.reason}` : ""}
                        </small>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {decisionError && (
              <div className="admin-state-banner danger">
                <strong>판정 오류</strong>
                <span>{decisionError}</span>
              </div>
            )}

            <div className="admin-ingredient-action-panel">
              <p className="admin-ingredient-action-title">관리자 판정</p>
              <p className="admin-ingredient-action-description">
                판정 결과와 사유는 변경 이력에 남습니다.
              </p>
              <div className="admin-ingredient-actions">
                {detail.availableActions.map((action) => (
                  <button
                    className={`admin-ingredient-action-button ${ACTION_VARIANTS[action]}`}
                    disabled={decisionSubmitting}
                    key={action}
                    onClick={() => openAction(action)}
                    title={ACTION_HELPERS[action]}
                    type="button"
                  >
                    {ACTION_LABELS[action]}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="admin-detail-body">
            <p className="admin-metric-group-title">기본 정보</p>
            <dl className="admin-metric-list">
              <div>
                <dt>pending code</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>pending 성분명</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>정규화명</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>연결</dt>
                <dd>-</dd>
              </div>
            </dl>

            <p className="admin-metric-group-title">추천 정보</p>
            <dl className="admin-metric-list">
              <div>
                <dt>추천 canonical</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>처리 후보</dt>
                <dd>-</dd>
              </div>
            </dl>
          </div>
        )}
        </div>
      </aside>

      {activeAction && detail && (
        <div className="admin-ingredient-modal-overlay">
          <section
            aria-describedby="ingredient-mapping-action-guide"
            aria-labelledby="ingredient-mapping-action-title"
            aria-modal="true"
            className="admin-panel admin-ingredient-modal"
            role="dialog"
          >
            <div className="admin-ingredient-modal-heading">
              <div>
                <p className={`admin-ingredient-action-kicker ${ACTION_VARIANTS[activeAction]}`}>
                  성분 매핑 판정
                </p>
                <h2 id="ingredient-mapping-action-title">{ACTION_LABELS[activeAction]}</h2>
              </div>
              <button
                aria-label="판정 모달 닫기"
                className="admin-ingredient-modal-close"
                disabled={decisionSubmitting}
                onClick={closeAction}
                type="button"
              >
                닫기
              </button>
            </div>

            <div className="admin-ingredient-action-context">
              <span>검수 대상</span>
              <strong>{detail.rawName}</strong>
              <code>{detail.pendingCode}</code>
            </div>
            <p className="admin-ingredient-action-guide" id="ingredient-mapping-action-guide">
              {ACTION_HELPERS[activeAction]}
            </p>

            {activeAction === "APPROVE" && (
              <div className="admin-ingredient-approve-target">
                <p className="admin-ingredient-field-label">연결할 canonical 성분</p>
                <div
                  className={`admin-ingredient-selected-target${selectedTargetCode ? " is-selected" : ""}`}
                >
                  <strong>{selectedTargetName ?? "대상 미선택"}</strong>
                  <span>{selectedTargetCode ?? "추천이 없으면 아래에서 검색해 선택하세요."}</span>
                </div>
                <form className="admin-ingredient-canonical-search" onSubmit={handleCanonicalSearch}>
                  <input
                    aria-label="canonical 검색"
                    onChange={(event) => setCanonicalQuery(event.target.value)}
                    placeholder="canonical 성분 검색"
                    type="search"
                    value={canonicalQuery}
                  />
                  <button className="admin-secondary-button" disabled={canonicalSearching} type="submit">
                    검색
                  </button>
                </form>
                {canonicalError && (
                  <div className="admin-state-banner danger">
                    <span>{canonicalError}</span>
                  </div>
                )}
                {canonicalSearching && <p className="admin-ingredient-search-state">후보를 찾고 있습니다…</p>}
                {canonicalResults.length > 0 && (
                  <ul className="admin-ingredient-canonical-results">
                    {canonicalResults.map((candidate) => (
                      <li key={candidate.ingredientCode}>
                        <button
                          aria-pressed={candidate.ingredientCode === selectedTargetCode}
                          className={`admin-ingredient-canonical-option${
                            candidate.ingredientCode === selectedTargetCode ? " is-selected" : ""
                          }`}
                          onClick={() => pickTarget(candidate.ingredientCode, candidate.nameKo)}
                          type="button"
                        >
                          {candidate.nameKo}
                          <small className="admin-product-code">{candidate.ingredientCode}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {activeAction === "REJECT" && (
              <div className="admin-ingredient-approve-target">
                <label className="admin-ingredient-reason">
                  <span className="admin-ingredient-reason-label">
                    최종 분류
                    <em>필수</em>
                  </span>
                  <select
                    aria-label="최종 분류"
                    onChange={(event) =>
                      setFinalDisposition(
                        event.target.value
                          ? (event.target.value as IngredientMappingNonMappingFinalDisposition)
                          : null
                      )
                    }
                    value={finalDisposition ?? ""}
                  >
                    <option value="">선택해 주세요</option>
                    {NON_MAPPING_FINAL_DISPOSITIONS.map((disposition) => (
                      <option key={disposition} value={disposition}>
                        {FINAL_DISPOSITION_LABELS[disposition]}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="admin-ingredient-reason">
                  <span className="admin-ingredient-reason-label">
                    근거 출처 URL
                    <em>{finalDispositionRequiresEvidence ? "필수(파일 식별자 대체 가능)" : "선택"}</em>
                  </span>
                  <input
                    aria-label="근거 출처 URL"
                    maxLength={2000}
                    onChange={(event) => setEvidenceSourceUrl(event.target.value)}
                    placeholder="https://…"
                    type="url"
                    value={evidenceSourceUrl}
                  />
                </label>

                <label className="admin-ingredient-reason">
                  <span className="admin-ingredient-reason-label">
                    원본 파일 식별자
                    <em>{finalDispositionRequiresEvidence ? "필수(URL 대체 가능)" : "선택"}</em>
                  </span>
                  <input
                    aria-label="원본 파일 식별자"
                    maxLength={255}
                    onChange={(event) => setSourceReference(event.target.value)}
                    placeholder="예: kcia_ingredients_2026-07.csv"
                    type="text"
                    value={sourceReference}
                  />
                </label>
              </div>
            )}

            <label className="admin-ingredient-reason">
              <span className="admin-ingredient-reason-label">
                판정 사유
                <em>{reasonRequired ? "필수" : "선택"}</em>
              </span>
              <textarea
                aria-describedby="ingredient-mapping-reason-help"
                maxLength={1000}
                onChange={(event) => setReasonInput(event.target.value)}
                placeholder={reasonRequired ? "보류·반려·재검토는 사유가 필요합니다." : "선택 입력"}
                rows={3}
                value={reasonInput}
              />
              <span className="admin-ingredient-reason-help" id="ingredient-mapping-reason-help">
                <small>{reasonRequired ? "사유는 판정 이력에 그대로 남습니다." : "필요한 경우에만 남겨 주세요."}</small>
                <small>{reasonInput.length}/1000</small>
              </span>
            </label>

            {decisionError && (
              <div className="admin-state-banner danger">
                <span>{decisionError}</span>
              </div>
            )}

            <div className="admin-ingredient-modal-actions">
              <button className="admin-secondary-button" disabled={decisionSubmitting} onClick={closeAction} type="button">
                취소
              </button>
              <button
                className={`admin-ingredient-confirm-button ${ACTION_VARIANTS[activeAction]}`}
                disabled={!canSubmitAction}
                onClick={() => void submitAction()}
                type="button"
              >
                {decisionSubmitting ? "처리 중…" : `${ACTION_LABELS[activeAction]} 확정`}
              </button>
            </div>
          </section>
        </div>
      )}

      {bulkModalOpen && bulkPreview && (
        <div className="admin-ingredient-modal-overlay">
          <section
            aria-describedby="ingredient-mapping-bulk-guide"
            aria-labelledby="ingredient-mapping-bulk-title"
            aria-modal="true"
            className="admin-panel admin-ingredient-modal"
            role="dialog"
          >
            <div className="admin-ingredient-modal-heading">
              <div>
                <p className="admin-ingredient-action-kicker approve">KCIA 근거 일괄 승인</p>
                <h2 id="ingredient-mapping-bulk-title">승인 전 미리보기</h2>
              </div>
              <button
                aria-label="일괄 승인 모달 닫기"
                className="admin-ingredient-modal-close"
                disabled={bulkSubmitting}
                onClick={closeBulkApproval}
                type="button"
              >
                닫기
              </button>
            </div>

            <p className="admin-ingredient-action-guide" id="ingredient-mapping-bulk-guide">
              별칭 출처와 canonical 근거가 모두 KCIA인 정확 일치 후보만 표시합니다. 저장 직전에
              서버가 다시 검증하며, 하나라도 바뀌면 전체 승인은 저장되지 않습니다.
            </p>
            <div className="admin-state-banner neutral">
              <span>
                현재 조건 충족 후보 {formatCount(bulkPreview.eligibleCount)}개 중 최대
                {formatCount(bulkPreview.maximumCount)}개를 표시합니다. 선택: {formatCount(selectedBulkItems.length)}개
              </span>
            </div>

            <div className="admin-filter-row">
              <button
                className="admin-secondary-button admin-light-button"
                disabled={bulkSubmitting}
                onClick={toggleSelectAllBulkItems}
                type="button"
              >
                {allBulkItemsSelected ? "전체 취소" : "전체 선택"}
              </button>
            </div>

            <div className="admin-table-wrap">
              <table className="admin-table admin-ingredient-table">
                <thead>
                  <tr>
                    <th scope="col">선택</th>
                    <th scope="col">pending 성분</th>
                    <th scope="col">연결 canonical</th>
                    <th scope="col">연결</th>
                  </tr>
                </thead>
                <tbody>
                  {bulkPreview.items.map((item) => {
                    const key = bulkKey(item.pendingCode, item.normalizedSourceName);
                    return (
                      <tr key={key}>
                        <td>
                          <input
                            aria-label={`${item.rawName} 일괄 승인 선택`}
                            checked={bulkSelectedKeys.includes(key)}
                            disabled={bulkSubmitting}
                            onChange={() => toggleBulkItem(item.pendingCode, item.normalizedSourceName)}
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <strong className="admin-product-name" title={item.rawName}>
                            {item.rawName}
                          </strong>
                          <small className="admin-product-code" title={item.pendingCode}>
                            {item.pendingCode}
                          </small>
                        </td>
                        <td>
                          <span title={item.targetIngredientName}>{item.targetIngredientName}</span>
                          <small className="admin-product-code" title={item.targetIngredientCode}>
                            {item.targetIngredientCode}
                          </small>
                        </td>
                        <td>{formatCount(item.connectionCount)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {bulkError && (
              <div className="admin-state-banner danger">
                <span>{bulkError}</span>
              </div>
            )}

            <label className="admin-ingredient-reason">
              <span className="admin-ingredient-reason-label">
                확인 문구 <em>필수</em>
              </span>
              <input
                aria-label="일괄 승인 확인 문구"
                disabled={bulkSubmitting}
                onChange={(event) => setBulkConfirmation(event.target.value)}
                placeholder={`"${bulkConfirmationPhrase}" 입력`}
                type="text"
                value={bulkConfirmation}
              />
              <small className="admin-ingredient-reason-help">
                정확히 {bulkConfirmationPhrase}을 입력하면 승인할 수 있습니다.
              </small>
            </label>

            <div className="admin-ingredient-modal-actions">
              <button className="admin-secondary-button" disabled={bulkSubmitting} onClick={closeBulkApproval} type="button">
                취소
              </button>
              <button
                className="admin-ingredient-confirm-button approve"
                disabled={
                  bulkSubmitting ||
                  selectedBulkItems.length === 0 ||
                  bulkConfirmation.trim() !== bulkConfirmationPhrase
                }
                onClick={() => void submitBulkApproval()}
                type="button"
              >
                {bulkSubmitting ? "일괄 승인 중…" : `${selectedBulkItems.length}개 승인 확정`}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
