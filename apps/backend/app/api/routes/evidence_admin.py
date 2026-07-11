import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ApiError, ErrorResponse
from app.schemas.evidence_admin import (
    EvidenceCandidateApproveRequest,
    EvidenceCandidateDecisionResponse,
    EvidenceCandidateDetailResponse,
    EvidenceCandidateImportRequest,
    EvidenceCandidateImportResponse,
    EvidenceCandidateListResponse,
    EvidenceCandidateRejectRequest,
)
from app.services.evidence_candidate_service import (
    approve_evidence_candidate,
    get_evidence_candidate,
    import_evidence_candidates,
    list_evidence_candidates,
    reject_evidence_candidate,
)


router = APIRouter(tags=["evidence-admin"])


def require_evidence_ingest_token(
    ingest_token: str | None = Header(default=None, alias="X-Evidence-Ingest-Token"),
) -> None:
    configured = settings.evidence_ingest_token
    if not configured:
        raise ApiError(503, "EVIDENCE_INGEST_NOT_CONFIGURED", "논문 후보 적재 인증이 설정되지 않았습니다.")
    if ingest_token is None or not hmac.compare_digest(ingest_token, configured):
        raise ApiError(401, "INVALID_EVIDENCE_INGEST_TOKEN", "논문 후보 적재 인증에 실패했습니다.")


@router.post(
    "/internal/evidence-candidates/import",
    response_model=EvidenceCandidateImportResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def post_evidence_candidate_import(
    request: EvidenceCandidateImportRequest,
    _: None = Depends(require_evidence_ingest_token),
    session: Session = Depends(get_db),
) -> EvidenceCandidateImportResponse:
    response = import_evidence_candidates(session, request.candidates)
    session.commit()
    return response


@router.get(
    "/admin/evidence-candidates",
    response_model=EvidenceCandidateListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_evidence_candidates(
    status: Literal["candidate_unverified", "accepted", "rejected"] | None = Query(default=None),
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin),
    session: Session = Depends(get_db),
) -> EvidenceCandidateListResponse:
    return list_evidence_candidates(
        session,
        status=status,
        query=query,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/admin/evidence-candidates/{candidate_id}",
    response_model=EvidenceCandidateDetailResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def get_evidence_candidate_detail(
    candidate_id: int,
    _: User = Depends(get_current_admin),
    session: Session = Depends(get_db),
) -> EvidenceCandidateDetailResponse:
    return get_evidence_candidate(session, candidate_id)


@router.post(
    "/admin/evidence-candidates/{candidate_id}/approve",
    response_model=EvidenceCandidateDecisionResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_evidence_candidate_approval(
    candidate_id: int,
    request: EvidenceCandidateApproveRequest,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_db),
) -> EvidenceCandidateDecisionResponse:
    response = approve_evidence_candidate(session, candidate_id, current_admin, request)
    session.commit()
    return response


@router.post(
    "/admin/evidence-candidates/{candidate_id}/reject",
    response_model=EvidenceCandidateDecisionResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_evidence_candidate_rejection(
    candidate_id: int,
    request: EvidenceCandidateRejectRequest,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_db),
) -> EvidenceCandidateDecisionResponse:
    response = reject_evidence_candidate(session, candidate_id, current_admin, request)
    session.commit()
    return response
