import { useState } from "react";

import {
  IngredientMappingMatchSource,
  IngredientMappingStatus,
  IngredientMappingStatusFilter
} from "../api/adminIngredientMappingApi";
import { useAdminIngredientMappings } from "./useAdminIngredientMappings";

// 관리자 성분 매핑 검수 조회 화면 (P1-M2-A Chunk 4, 조회 전용).
// 승인/보류/반려/재검토(쓰기)는 다음 Chunk. 부모와는 onOperationLog 만 공유한다.
// 로딩 UX: 최초 진입 skeleton, 필터·검색·더 보기 중에는 기존 목록 유지 + 갱신 표시.

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
};

const STATUS_TONES: Record<IngredientMappingStatus, BadgeTone> = {
  PENDING: "warning",
  HELD: "review",
  APPROVED: "success",
  REJECTED: "danger"
};

const MATCH_SOURCE_LABELS: Record<IngredientMappingMatchSource, string> = {
  ALIAS_EXACT: "별칭 정확 일치",
  CANONICAL_NAME_EXACT: "표준명 정확 일치"
};

const STATUS_FILTER_OPTIONS: Array<{ value: IngredientMappingStatusFilter; label: string }> = [
  { value: "ALL", label: "전체" },
  { value: "PENDING", label: "미판정" },
  { value: "HELD", label: "보류" },
  { value: "APPROVED", label: "승인" },
  { value: "REJECTED", label: "반려" }
];

const SKELETON_ROWS = Array.from({ length: 6 });

const formatCount = (value: number): string => value.toLocaleString("ko-KR");

const formatEventState = (status: IngredientMappingStatus, targetIngredientCode: string | null): string =>
  `${STATUS_LABELS[status]}${targetIngredientCode ? ` (${targetIngredientCode})` : ""}`;

export function AdminIngredientMappingSection({
  active,
  onOperationLog
}: AdminIngredientMappingSectionProps) {
  const {
    statusFilter,
    queryInput,
    setQueryInput,
    items,
    summary,
    nextCursor,
    loading,
    loadingMore,
    error,
    hasLoaded,
    applySearch,
    setStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    selectedKey,
    detail,
    detailLoading,
    detailError,
    selectMapping
  } = useAdminIngredientMappings({ enabled: active });

  const [expandedEvents, setExpandedEvents] = useState(false);

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
    onOperationLog(
      "성분",
      succeeded ? "성분 매핑 목록 새로고침" : "성분 매핑 목록 새로고침 실패",
      succeeded ? "검수 대기 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
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
            <input
              aria-label="성분명·코드 검색"
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="성분명·코드 검색"
              type="search"
              value={queryInput}
            />
            <button className="admin-secondary-button" disabled={loading} type="submit">
              검색
            </button>
            <button className="admin-secondary-button" onClick={resetFilters} type="button">
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

        <div className="admin-table-wrap">
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
                          <strong className="admin-product-name">{row.rawName}</strong>
                          <small className="admin-product-code">{row.pendingCode}</small>
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
                        {row.suggestion ? (
                          <small className="admin-product-code">
                            {MATCH_SOURCE_LABELS[row.suggestion.matchSource]}
                          </small>
                        ) : (
                          "-"
                        )}
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

        <div className="admin-filter-row">
          <button
            className="admin-secondary-button"
            disabled={nextCursor === null || loadingMore || loading}
            onClick={() => void loadMore()}
            type="button"
          >
            {loadingMore ? "불러오는 중…" : nextCursor === null ? "마지막 페이지" : "더 보기"}
          </button>
        </div>
      </section>

      <aside className="admin-panel admin-ingredient-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 성분</p>
            <h2>{detail ? detail.rawName : "선택된 성분 없음"}</h2>
          </div>
          {detail && (
            <span className={`admin-badge ${STATUS_TONES[detail.status]}`}>
              {STATUS_LABELS[detail.status]}
            </span>
          )}
        </div>

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
              <div>
                <dt>추천 canonical</dt>
                <dd>
                  {detail.suggestion
                    ? `${detail.suggestion.targetIngredientName} (${MATCH_SOURCE_LABELS[detail.suggestion.matchSource]})`
                    : "없음 — canonical 직접 검색 필요"}
                </dd>
              </div>
              {detail.decision && (
                <>
                  <div>
                    <dt>관리자 판정</dt>
                    <dd>
                      {STATUS_LABELS[detail.decision.status]}
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
                </>
              )}
            </dl>

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
                            ? `${formatEventState(event.fromStatus, event.fromTargetIngredientCode)} → `
                            : "최초 판정 → "}
                          {formatEventState(event.toStatus, event.toTargetIngredientCode)}
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

            <div className="admin-state-banner neutral">
              <strong>판정 액션은 다음 단계</strong>
              <span>승인·보류·반려·재검토 버튼은 후속 Chunk에서 연결됩니다.</span>
            </div>
          </>
        ) : (
          <div className="admin-state-banner neutral">
            <strong>선택된 성분 없음</strong>
            <span>대기열에서 성분을 선택하면 상세와 추천이 표시됩니다.</span>
          </div>
        )}
      </aside>
    </section>
  );
}
