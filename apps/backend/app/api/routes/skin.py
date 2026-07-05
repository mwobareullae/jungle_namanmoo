from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_optional_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.profile import SignupSkinProfileRequest, SkinProfileResponse, SkinProfileUpdateRequest
from app.schemas.skin_test import (
    SkinTestApplyRequest,
    SkinTestApplyResponse,
    SkinTestQuestionsResponse,
    SkinTestResultData,
    SkinTestResultResponse,
    SkinTestSubmitRequest,
)
from app.services.skin_profile_service import (
    SkinServiceError,
    get_skin_profile_response,
    upsert_manual_skin_profile,
    upsert_signup_skin_profile,
)
from app.services.skin_test_service import (
    apply_skin_test_result_to_profile,
    get_skin_test_questions_response,
    get_skin_test_result_data,
    submit_skin_test,
)


router = APIRouter(tags=["skin"])


@router.get("/me/skin-profile", response_model=SkinProfileResponse)
def get_my_skin_profile(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> SkinProfileResponse | JSONResponse:
    try:
        return get_skin_profile_response(session, current_user)
    except SkinServiceError as exc:
        return _skin_error(exc)


@router.put("/me/skin-profile", response_model=SkinProfileResponse)
def put_my_skin_profile(
    request: SkinProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> SkinProfileResponse | JSONResponse:
    try:
        response = upsert_manual_skin_profile(session, current_user, request)
        session.commit()
        return response
    except SkinServiceError as exc:
        session.rollback()
        return _skin_error(exc)


@router.post("/skin-profile", response_model=SkinProfileResponse)
def post_signup_skin_profile(
    request: SignupSkinProfileRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> SkinProfileResponse | JSONResponse:
    try:
        response = upsert_signup_skin_profile(session, current_user, request)
        session.commit()
        return response
    except SkinServiceError as exc:
        session.rollback()
        return _skin_error(exc)


@router.get("/skin-test/questions", response_model=SkinTestQuestionsResponse)
def get_skin_test_questions(
    session: Session = Depends(get_db),
) -> SkinTestQuestionsResponse | JSONResponse:
    try:
        response = get_skin_test_questions_response(session)
        session.commit()
        return response
    except SkinServiceError as exc:
        session.rollback()
        return _skin_error(exc)


@router.post("/skin-test/submit", response_model=SkinTestResultData)
def post_skin_test_submit(
    request: SkinTestSubmitRequest,
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> SkinTestResultData | JSONResponse:
    try:
        response = submit_skin_test(session, request, current_user)
        session.commit()
        return response
    except SkinServiceError as exc:
        session.rollback()
        return _skin_error(exc)


@router.get("/skin-test/results/{result_id}", response_model=SkinTestResultResponse)
def get_skin_test_result(
    result_id: int,
    session: Session = Depends(get_db),
) -> SkinTestResultResponse | JSONResponse:
    try:
        return SkinTestResultResponse(result=get_skin_test_result_data(session, result_id))
    except SkinServiceError as exc:
        return _skin_error(exc)


@router.post("/skin-test/apply-to-profile", response_model=SkinTestApplyResponse)
def post_skin_test_apply_to_profile(
    request: SkinTestApplyRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> SkinTestApplyResponse | JSONResponse:
    try:
        response = apply_skin_test_result_to_profile(session, current_user, request.result_id)
        session.commit()
        return SkinTestApplyResponse(success=True, skin_profile=response.profile)
    except SkinServiceError as exc:
        session.rollback()
        return _skin_error(exc)


def _skin_error(error: SkinServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "error": {
                "code": error.code,
                "message": error.message,
            },
        },
    )
