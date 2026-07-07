from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.session import get_db
from app.schemas.home import HomeSectionsResponse
from app.services.event_tracking import request_id_from_request
from app.services.home_sections import (
    DEFAULT_HOME_LIMIT_PER_SECTION,
    MAX_HOME_LIMIT_PER_SECTION,
    get_home_sections_response,
)


router = APIRouter(tags=["home"])


@router.get(
    "/home/sections",
    response_model=HomeSectionsResponse,
)
def get_home_sections(
    request: Request,
    skin_type: str = Query(default="중성"),
    sensitivity: str = Query(default="보통"),
    category_code: str | None = Query(default=None),
    limit_per_section: int = Query(
        default=DEFAULT_HOME_LIMIT_PER_SECTION,
        ge=1,
        le=MAX_HOME_LIMIT_PER_SECTION,
    ),
    session: Session = Depends(get_db),
) -> HomeSectionsResponse:
    started_at = current_time()
    response = get_home_sections_response(
        session,
        skin_type=skin_type,
        sensitivity=sensitivity,
        category_code=category_code,
        limit_per_section=limit_per_section,
    )
    log_performance_event(
        "home_sections_completed",
        request_id=request_id_from_request(request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "section_count": len(response.sections),
            "product_count": sum(len(section.products) for section in response.sections),
            "category_code": response.category_code,
            "limit_per_section": limit_per_section,
            "skin_type": response.skin_type,
            "sensitivity": response.sensitivity,
            "section_ids": [section.section_id for section in response.sections],
        },
    )
    return response
