from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.home import HomeLayoutResponse, HomeProductSectionResponse
from app.services.event_tracking import request_id_from_request
from app.services.home_section_snapshot_service import (
    HOME_EVIDENCE_SNAPSHOT_CONTEXT,
    HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
    HOME_FOR_YOU_SNAPSHOT_SECTION_ID,
    guest_skin_snapshot_context,
    snapshot_metadata,
)
from app.services.home_sections import (
    DEFAULT_HOME_LIMIT_PER_SECTION,
    MAX_HOME_LIMIT_PER_SECTION,
    get_evidence_picks_response,
    get_for_you_response,
    get_home_layout_response,
    get_market_popular_response,
)


router = APIRouter(tags=["home"])


@router.get("/home/layout", response_model=HomeLayoutResponse)
def get_home_layout(request: Request) -> HomeLayoutResponse:
    started_at = current_time()
    response = get_home_layout_response()
    log_performance_event(
        "home_layout_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "section_count": len(response.sections),
            "section_ids": [section.section_id for section in response.sections],
        },
    )
    return response


@router.get("/home/market-popular", response_model=HomeProductSectionResponse)
def get_home_market_popular(
    request: Request,
    category_code: str | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_HOME_LIMIT_PER_SECTION,
        ge=1,
        le=MAX_HOME_LIMIT_PER_SECTION,
    ),
    session: Session = Depends(get_db),
) -> HomeProductSectionResponse:
    started_at = current_time()
    response = get_market_popular_response(
        session,
        category_code=category_code,
        limit=limit,
    )
    log_performance_event(
        "home_market_popular_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_count": len(response.products),
            "category_code": response.category_code,
            "limit": response.limit,
        },
    )
    return response


@router.get("/home/evidence-picks", response_model=HomeProductSectionResponse)
def get_home_evidence_picks(
    request: Request,
    category_code: str | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_HOME_LIMIT_PER_SECTION,
        ge=1,
        le=MAX_HOME_LIMIT_PER_SECTION,
    ),
    session: Session = Depends(get_db),
) -> HomeProductSectionResponse:
    started_at = current_time()
    response = get_evidence_picks_response(
        session,
        category_code=category_code,
        limit=limit,
    )
    home_snapshot_metadata = snapshot_metadata(
        session,
        section_id=HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
        context_key=HOME_EVIDENCE_SNAPSHOT_CONTEXT if category_code is None else None,
    )
    log_performance_event(
        "home_evidence_picks_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_count": len(response.products),
            "category_code": response.category_code,
            "limit": response.limit,
            **home_snapshot_metadata,
        },
    )
    return response

@router.get("/home/for-you", response_model=HomeProductSectionResponse)
def get_home_for_you(
    request: Request,
    skin_type: str | None = Query(default=None),
    sensitivity: str | None = Query(default=None),
    concern: str | None = Query(default=None),
    effect: str | None = Query(default=None),
    category_code: str | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_HOME_LIMIT_PER_SECTION,
        ge=1,
        le=MAX_HOME_LIMIT_PER_SECTION,
    ),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> HomeProductSectionResponse:
    started_at = current_time()
    response = get_for_you_response(
        session,
        skin_type=skin_type,
        sensitivity=sensitivity,
        concern=concern,
        effect=effect,
        category_code=category_code,
        limit=limit,
        current_user=current_user,
    )
    snapshot_context = (
        guest_skin_snapshot_context(response.skin_type)
        if category_code is None and response.skin_type is not None
        else None
    )
    home_snapshot_metadata = snapshot_metadata(
        session,
        section_id=HOME_FOR_YOU_SNAPSHOT_SECTION_ID,
        context_key=snapshot_context,
        user_context=True,
    )
    log_performance_event(
        "home_for_you_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_count": len(response.products),
            "category_code": response.category_code,
            "skin_type": response.skin_type,
            "sensitivity": response.sensitivity,
            "has_user": current_user is not None,
            "limit": response.limit,
            "personalization_sources": response.personalization_sources,
            **home_snapshot_metadata,
        },
    )
    return response
