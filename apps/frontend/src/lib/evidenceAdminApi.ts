import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

export type EvidenceReviewStatus = "candidate_unverified" | "accepted" | "rejected";
export type EvidenceResultDirection = "positive" | "negative" | "null" | "unclear";
export type EvidenceScoreUseLevel = "primary" | "supporting" | "reference_only";

export type EvidenceCandidate = {
  id: number;
  discovery_key: string;
  ingredient_id: string;
  ingredient_name: string;
  effect_id: string;
  effect_name: string;
  pmid: string | null;
  doi: string | null;
  title: string;
  journal: string | null;
  publication_date: string | null;
  publication_date_text: string | null;
  publication_types: string | null;
  authors: string | null;
  abstract_excerpt: string | null;
  source_url: string;
  discovery_scope: string;
  first_seen_at: string;
  last_seen_at: string;
  review_status: EvidenceReviewStatus;
  review_note: string | null;
  reviewed_at: string | null;
  promoted_evidence_id: number | null;
  current_evidence_count: number;
  score_eligible: false;
};

export type EvidenceCandidateHistory = {
  id: number;
  previous_status: string;
  new_status: string;
  reviewer: string;
  note: string | null;
  promoted_evidence_id: number | null;
  created_at: string;
};

export type EvidenceCandidateDetail = EvidenceCandidate & {
  search_query: string | null;
  search_window_start: string | null;
  search_window_end: string | null;
  current_evidence: Array<{
    id: number;
    source_title: string | null;
    source_url: string | null;
    summary: string;
    evidence_level: string | null;
    evidence_score: number;
    review_status: string;
    result_direction: string;
    score_use_level: string;
    is_representative: boolean;
    representative_rank: number | null;
  }>;
  history: EvidenceCandidateHistory[];
};

export type EvidenceCandidateList = {
  items: EvidenceCandidate[];
  stats: {
    total: number;
    candidate_unverified: number;
    accepted: number;
    rejected: number;
  };
  total: number;
  limit: number;
  offset: number;
};

export type EvidenceCandidateApprove = {
  summary: string;
  evidence_level: "low" | "medium" | "high";
  evidence_score: number;
  result_direction: EvidenceResultDirection;
  score_use_level: EvidenceScoreUseLevel;
  source_authority_score?: number | null;
  is_representative: boolean;
  representative_rank?: number | null;
  review_note: string;
};

const evidenceAdminApi = {
  async list(params: { status?: EvidenceReviewStatus | "all"; query?: string } = {}) {
    const searchParams = new URLSearchParams();
    if (params.status && params.status !== "all") searchParams.set("status", params.status);
    if (params.query?.trim()) searchParams.set("query", params.query.trim());
    const query = searchParams.toString();
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/admin/evidence-candidates${query ? `?${query}` : ""}`
    );
    return parseJson<EvidenceCandidateList>(response);
  },

  async detail(candidateId: number) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/admin/evidence-candidates/${encodeURIComponent(String(candidateId))}`
    );
    return parseJson<EvidenceCandidateDetail>(response);
  },

  async approve(candidateId: number, request: EvidenceCandidateApprove) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/admin/evidence-candidates/${encodeURIComponent(String(candidateId))}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request)
      }
    );
    return parseJson<{ candidate: EvidenceCandidateDetail; promoted_evidence_id: number }>(
      response
    );
  },

  async reject(candidateId: number, reviewNote: string) {
    const response = await fetchWithTimeout(
      `${API_BASE_URL}/admin/evidence-candidates/${encodeURIComponent(String(candidateId))}/reject`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_note: reviewNote })
      }
    );
    return parseJson<{ candidate: EvidenceCandidateDetail; promoted_evidence_id: null }>(response);
  }
};

export default evidenceAdminApi;
