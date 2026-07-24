import { useCallback, useEffect, useMemo, useState } from "react";

import "./EvidenceCandidateReviewPanel.css";
import evidenceAdminApi, {
  type EvidenceCandidate,
  type EvidenceCandidateApprove,
  type EvidenceCandidateDetail,
  type EvidenceResultDirection,
  type EvidenceReviewStatus,
  type EvidenceScoreUseLevel
} from "../../lib/evidenceAdminApi";

type Props = {
  onNotify: (
    message: string,
    tone: "success" | "warning" | "danger" | "neutral" | "review"
  ) => void;
};

type EvidenceLevel = EvidenceCandidateApprove["evidence_level"];
type StatusFilter = EvidenceReviewStatus | "all";

const statusLabels: Record<EvidenceReviewStatus, string> = {
  candidate_unverified: "검수 대기",
  accepted: "승인",
  rejected: "기각"
};

function EvidenceCandidateReviewPanel({ onNotify }: Props) {
  const [items, setItems] = useState<EvidenceCandidate[]>([]);
  const [stats, setStats] = useState({
    total: 0,
    candidate_unverified: 0,
    accepted: 0,
    rejected: 0
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EvidenceCandidateDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("candidate_unverified");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState<EvidenceResultDirection>("positive");
  const [scoreUseLevel, setScoreUseLevel] = useState<EvidenceScoreUseLevel>("supporting");
  const [evidenceLevel, setEvidenceLevel] = useState<EvidenceLevel>("medium");
  const [evidenceScore, setEvidenceScore] = useState(60);
  const [summary, setSummary] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [isRepresentative, setIsRepresentative] = useState(false);
  const [representativeRank, setRepresentativeRank] = useState(1);

  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
    [items, selectedId]
  );

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await evidenceAdminApi.list({ status: statusFilter, query });
      setItems(response.items);
      setStats(response.stats);
      if (response.items.length === 0) setDetail(null);
      setSelectedId((current) =>
        response.items.some((item) => item.id === current)
          ? current
          : (response.items[0]?.id ?? null)
      );
    } catch (caught) {
      setError(errorMessage(caught));
      setItems([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [query, statusFilter]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void loadList(), 250);
    return () => window.clearTimeout(timeoutId);
  }, [loadList]);

  useEffect(() => {
    if (!selected?.id) {
      return;
    }
    let cancelled = false;
    void evidenceAdminApi
      .detail(selected.id)
      .then((response) => {
        if (cancelled) return;
        setDetail(response);
        setSummary(response.abstract_excerpt ?? "");
        setReviewNote("");
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id]);

  const handleDirectionChange = (nextDirection: EvidenceResultDirection) => {
    setDirection(nextDirection);
    if (nextDirection === "positive") return;
    setEvidenceScore(0);
    setScoreUseLevel("reference_only");
    setIsRepresentative(false);
  };

  const handleScoreUseLevelChange = (nextLevel: EvidenceScoreUseLevel) => {
    setScoreUseLevel(nextLevel);
    if (nextLevel === "reference_only") setEvidenceScore(0);
  };

  const handleApprove = async () => {
    if (!detail || !summary.trim() || !reviewNote.trim()) {
      onNotify("근거 요약과 검수 메모를 입력해 주세요.", "warning");
      return;
    }
    setSaving(true);
    try {
      await evidenceAdminApi.approve(detail.id, {
        summary: summary.trim(),
        evidence_level: evidenceLevel,
        evidence_score: evidenceScore,
        result_direction: direction,
        score_use_level: scoreUseLevel,
        source_authority_score: null,
        is_representative: isRepresentative,
        representative_rank: isRepresentative ? representativeRank : null,
        review_note: reviewNote.trim()
      });
      onNotify("승인된 논문을 런타임 근거로 연결했습니다.", "success");
      await loadList();
    } catch (caught) {
      onNotify(errorMessage(caught), "danger");
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async () => {
    if (!detail || !reviewNote.trim()) {
      onNotify("기각 사유를 검수 메모에 입력해 주세요.", "warning");
      return;
    }
    setSaving(true);
    try {
      await evidenceAdminApi.reject(detail.id, reviewNote.trim());
      onNotify("논문 후보를 기각하고 이력을 남겼습니다.", "success");
      await loadList();
    } catch (caught) {
      onNotify(errorMessage(caught), "danger");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="admin-evidence-layout">
      <section className="admin-panel admin-evidence-main">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p className="admin-panel-eyebrow">추천 운영</p>
            <h2>신규 논문 후보 검수</h2>
          </div>
          <div className="admin-filter-row">
            <input
              aria-label="논문 후보 검색"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="성분, 효능, PMID, 제목"
              type="search"
              value={query}
            />
            <select
              aria-label="논문 후보 상태"
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
              value={statusFilter}
            >
              <option value="candidate_unverified">검수 대기</option>
              <option value="accepted">승인</option>
              <option value="rejected">기각</option>
              <option value="all">전체</option>
            </select>
          </div>
        </div>

        <div className="admin-stats admin-evidence-stats" aria-label="논문 후보 현황">
          <div className="admin-stat">
            <span>전체 후보</span>
            <strong>{stats.total}</strong>
          </div>
          <div className="admin-stat">
            <span>검수 대기</span>
            <strong>{stats.candidate_unverified}</strong>
          </div>
          <div className="admin-stat">
            <span>승인</span>
            <strong>{stats.accepted}</strong>
          </div>
          <div className="admin-stat">
            <span>기각</span>
            <strong>{stats.rejected}</strong>
          </div>
        </div>

        {error ? <div className="admin-state-banner danger">{error}</div> : null}
        <div className="admin-table-wrap">
          <table className="admin-table admin-evidence-table">
            <thead>
              <tr>
                <th>성분 × 효능</th>
                <th>논문</th>
                <th>발표일</th>
                <th>발견일</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  className={item.id === selected?.id ? "selected" : undefined}
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                >
                  <td>
                    <strong>
                      {item.ingredient_name} × {item.effect_name}
                    </strong>
                    <small className="admin-product-code">
                      {item.ingredient_id} / {item.effect_id}
                    </small>
                  </td>
                  <td>
                    <strong className="admin-evidence-title">{item.title}</strong>
                    <small className="admin-product-code">
                      {item.pmid ? `PMID ${item.pmid}` : item.doi}
                    </small>
                  </td>
                  <td>{item.publication_date_text || item.publication_date || "—"}</td>
                  <td>{dateLabel(item.first_seen_at)}</td>
                  <td>
                    <span className={`admin-badge ${statusTone(item.review_status)}`}>
                      {statusLabels[item.review_status]}
                    </span>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 ? (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    조건에 맞는 논문 후보가 없습니다.
                  </td>
                </tr>
              ) : null}
              {loading ? (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    논문 후보를 불러오는 중입니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <aside className="admin-panel admin-evidence-detail">
        {detail ? (
          <>
            <div className="admin-panel-header compact">
              <div>
                <p className="admin-panel-eyebrow">후보 상세</p>
                <h2>
                  {detail.ingredient_name} × {detail.effect_name}
                </h2>
              </div>
              <span className={`admin-badge ${statusTone(detail.review_status)}`}>
                {statusLabels[detail.review_status]}
              </span>
            </div>

            <h3 className="admin-evidence-detail-title">{detail.title}</h3>
            <dl className="admin-detail-list">
              <div>
                <dt>식별자</dt>
                <dd>{detail.pmid ? `PMID ${detail.pmid}` : detail.doi || "—"}</dd>
              </div>
              <div>
                <dt>저널</dt>
                <dd>{detail.journal || "—"}</dd>
              </div>
              <div>
                <dt>연구유형</dt>
                <dd>{detail.publication_types || "—"}</dd>
              </div>
              <div>
                <dt>현재 근거</dt>
                <dd>{detail.current_evidence_count}편</dd>
              </div>
            </dl>
            <a
              className="admin-text-button"
              href={detail.source_url}
              rel="noreferrer"
              target="_blank"
            >
              PubMed 원문 확인
            </a>

            <div className="admin-evidence-abstract">
              <strong>초록</strong>
              <p>{detail.abstract_excerpt || "초록이 제공되지 않았습니다."}</p>
            </div>

            <section className="admin-evidence-current">
              <h3>현재 연결된 근거</h3>
              {detail.current_evidence.map((evidence) => (
                <article key={evidence.id}>
                  <div>
                    <strong>{evidence.source_title || `근거 #${evidence.id}`}</strong>
                    <span
                      className={`admin-badge ${evidence.is_representative ? "success" : "neutral"}`}
                    >
                      {evidence.is_representative
                        ? `대표 ${evidence.representative_rank}`
                        : evidence.review_status}
                    </span>
                  </div>
                  <p>{evidence.summary}</p>
                  <small>
                    {evidence.result_direction} · {evidence.score_use_level} ·{" "}
                    {evidence.evidence_score}점
                  </small>
                </article>
              ))}
              {detail.current_evidence.length === 0 ? <p>현재 연결된 근거가 없습니다.</p> : null}
            </section>

            {detail.review_status === "candidate_unverified" ? (
              <div className="admin-evidence-review-form">
                <div className="admin-evidence-field-grid">
                  <label>
                    결과 방향
                    <select
                      onChange={(event) =>
                        handleDirectionChange(event.target.value as EvidenceResultDirection)
                      }
                      value={direction}
                    >
                      <option value="positive">효과 있음</option>
                      <option value="negative">악화·부작용</option>
                      <option value="null">효과 없음</option>
                      <option value="unclear">불명확</option>
                    </select>
                  </label>
                  <label>
                    근거 등급
                    <select
                      onChange={(event) => setEvidenceLevel(event.target.value as EvidenceLevel)}
                      value={evidenceLevel}
                    >
                      <option value="high">높음</option>
                      <option value="medium">중간</option>
                      <option value="low">낮음</option>
                    </select>
                  </label>
                  <label>
                    점수 사용
                    <select
                      disabled={direction !== "positive"}
                      onChange={(event) =>
                        handleScoreUseLevelChange(event.target.value as EvidenceScoreUseLevel)
                      }
                      value={scoreUseLevel}
                    >
                      <option value="primary">주근거</option>
                      <option value="supporting">보조근거</option>
                      <option value="reference_only">참고만</option>
                    </select>
                  </label>
                  <label>
                    근거 점수
                    <input
                      disabled={direction !== "positive"}
                      max={100}
                      min={0}
                      onChange={(event) => setEvidenceScore(Number(event.target.value))}
                      type="number"
                      value={evidenceScore}
                    />
                  </label>
                </div>
                <label className="admin-form-wide">
                  근거 요약
                  <textarea
                    onChange={(event) => setSummary(event.target.value)}
                    rows={4}
                    value={summary}
                  />
                </label>
                <label className="admin-form-wide">
                  검수 메모
                  <textarea
                    onChange={(event) => setReviewNote(event.target.value)}
                    rows={3}
                    value={reviewNote}
                  />
                </label>
                <label className="admin-evidence-checkbox">
                  <input
                    checked={isRepresentative}
                    disabled={direction !== "positive"}
                    onChange={(event) => setIsRepresentative(event.target.checked)}
                    type="checkbox"
                  />
                  대표 근거로 지정
                </label>
                {isRepresentative ? (
                  <label>
                    대표 순위
                    <select
                      onChange={(event) => setRepresentativeRank(Number(event.target.value))}
                      value={representativeRank}
                    >
                      <option value={1}>1</option>
                      <option value={2}>2</option>
                      <option value={3}>3</option>
                    </select>
                  </label>
                ) : null}
                <div className="admin-evidence-actions">
                  <button
                    className="admin-primary-button"
                    disabled={saving}
                    onClick={() => void handleApprove()}
                    type="button"
                  >
                    승인 및 근거 연결
                  </button>
                  <button
                    className="admin-secondary-button danger"
                    disabled={saving}
                    onClick={() => void handleReject()}
                    type="button"
                  >
                    기각
                  </button>
                </div>
              </div>
            ) : (
              <div className="admin-state-banner neutral">
                {detail.review_note || "판정 메모가 없습니다."}
              </div>
            )}

            <section className="admin-evidence-history">
              <h3>판정 이력</h3>
              {detail.history.map((history) => (
                <div key={history.id}>
                  <strong>
                    {statusLabels[history.new_status as EvidenceReviewStatus] ?? history.new_status}
                  </strong>
                  <span>
                    {history.reviewer} · {dateTimeLabel(history.created_at)}
                  </span>
                  <p>{history.note || "—"}</p>
                </div>
              ))}
              {detail.history.length === 0 ? <p>아직 판정 이력이 없습니다.</p> : null}
            </section>
          </>
        ) : (
          <div className="admin-empty-state">
            <strong>논문 후보를 선택해 주세요.</strong>
          </div>
        )}
      </aside>
    </section>
  );
}

function statusTone(status: EvidenceReviewStatus) {
  if (status === "accepted") return "success";
  if (status === "rejected") return "danger";
  return "warning";
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(new Date(value));
}

function dateTimeLabel(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(value)
  );
}

function errorMessage(caught: unknown) {
  if (typeof caught === "object" && caught !== null && "message" in caught) {
    return String(caught.message);
  }
  return "논문 후보 요청을 처리하지 못했습니다.";
}

export default EvidenceCandidateReviewPanel;
