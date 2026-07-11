from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


EvidenceReviewStatus = Literal["candidate_unverified", "accepted", "rejected"]
EvidenceResultDirection = Literal["positive", "negative", "null", "unclear"]
EvidenceScoreUseLevel = Literal["primary", "supporting", "reference_only"]


class EvidenceCandidateImportItem(BaseModel):
    discovery_key: str = Field(min_length=1, max_length=240)
    ingredient_id: str = Field(min_length=1, max_length=64)
    effect_id: str = Field(min_length=1, max_length=64)
    effect_name: str = ""
    pmid: str = Field(default="", max_length=40)
    doi: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=2000)
    journal: str = Field(default="", max_length=1000)
    publication_date: str = Field(default="", max_length=80)
    publication_types: str = ""
    authors: str = ""
    abstract_available: bool = False
    abstract_excerpt: str = ""
    source_url: str = Field(min_length=1)
    discovery_scope: str = Field(min_length=1, max_length=40)
    review_status: Literal["candidate_unverified"] = "candidate_unverified"
    score_eligible: Literal[False] = False
    search_window_start: date | None = None
    search_window_end: date | None = None
    search_query: str = ""


class EvidenceCandidateImportRequest(BaseModel):
    candidates: list[EvidenceCandidateImportItem] = Field(max_length=1000)


class EvidenceCandidateImportResponse(BaseModel):
    received: int
    inserted: int
    refreshed: int


class EvidenceCandidateStats(BaseModel):
    total: int
    candidate_unverified: int
    accepted: int
    rejected: int


class EvidenceCandidateItem(BaseModel):
    id: int
    discovery_key: str
    ingredient_id: str
    ingredient_name: str
    effect_id: str
    effect_name: str
    pmid: str | None
    doi: str | None
    title: str
    journal: str | None
    publication_date: date | None
    publication_date_text: str | None
    publication_types: str | None
    authors: str | None
    abstract_excerpt: str | None
    source_url: str
    discovery_scope: str
    first_seen_at: datetime
    last_seen_at: datetime
    review_status: EvidenceReviewStatus
    review_note: str | None
    reviewed_at: datetime | None
    promoted_evidence_id: int | None
    current_evidence_count: int
    score_eligible: Literal[False] = False


class EvidenceCandidateListResponse(BaseModel):
    items: list[EvidenceCandidateItem]
    stats: EvidenceCandidateStats
    total: int
    limit: int
    offset: int


class EvidenceCandidateReviewItem(BaseModel):
    id: int
    previous_status: str
    new_status: str
    reviewer: str
    note: str | None
    promoted_evidence_id: int | None
    created_at: datetime


class CurrentIngredientEvidenceItem(BaseModel):
    id: int
    source_title: str | None
    source_url: str | None
    summary: str
    evidence_level: str | None
    evidence_score: Decimal
    review_status: str
    result_direction: str
    score_use_level: str
    is_representative: bool
    representative_rank: int | None


class EvidenceCandidateDetailResponse(EvidenceCandidateItem):
    search_query: str | None
    search_window_start: date | None
    search_window_end: date | None
    current_evidence: list[CurrentIngredientEvidenceItem]
    history: list[EvidenceCandidateReviewItem]


class EvidenceCandidateApproveRequest(BaseModel):
    summary: str = Field(min_length=1)
    evidence_level: Literal["low", "medium", "high"]
    evidence_score: Decimal = Field(ge=0, le=100)
    result_direction: EvidenceResultDirection
    score_use_level: EvidenceScoreUseLevel
    source_authority_score: Decimal | None = Field(default=None, ge=0, le=1)
    is_representative: bool = False
    representative_rank: int | None = Field(default=None, ge=1, le=3)
    review_note: str = Field(min_length=1)


class EvidenceCandidateRejectRequest(BaseModel):
    review_note: str = Field(min_length=1)


class EvidenceCandidateDecisionResponse(BaseModel):
    candidate: EvidenceCandidateDetailResponse
    promoted_evidence_id: int | None
