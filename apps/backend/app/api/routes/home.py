from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.home import HomeSectionsResponse
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
    return get_home_sections_response(
        session,
        skin_type=skin_type,
        sensitivity=sensitivity,
        category_code=category_code,
        limit_per_section=limit_per_section,
    )
