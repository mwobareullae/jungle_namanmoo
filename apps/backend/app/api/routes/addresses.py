from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.address import (
    DeleteUserAddressResponse,
    UserAddressCreateRequest,
    UserAddressResponse,
    UserAddressesResponse,
    UserAddressUpdateRequest,
)
from app.schemas.common import ErrorResponse
from app.services.address_service import (
    create_user_address,
    delete_user_address,
    get_user_addresses,
    update_user_address,
)


router = APIRouter(tags=["addresses"])


@router.get("/me/addresses", response_model=UserAddressesResponse)
def get_my_addresses(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> UserAddressesResponse:
    return get_user_addresses(session, current_user)


@router.post(
    "/me/addresses",
    response_model=UserAddressResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_my_address(
    request: UserAddressCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> UserAddressResponse:
    address = create_user_address(session, current_user, request)
    session.commit()
    return address


@router.patch(
    "/me/addresses/{address_id}",
    response_model=UserAddressResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def patch_my_address(
    address_id: int,
    request: UserAddressUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> UserAddressResponse:
    address = update_user_address(session, current_user, address_id, request)
    session.commit()
    return address


@router.delete(
    "/me/addresses/{address_id}",
    response_model=DeleteUserAddressResponse,
    responses={404: {"model": ErrorResponse}},
)
def delete_my_address(
    address_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DeleteUserAddressResponse:
    success = delete_user_address(session, current_user, address_id)
    session.commit()
    return DeleteUserAddressResponse(success=success)
