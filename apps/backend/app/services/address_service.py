from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import UserAddress
from app.schemas.address import (
    UserAddressCreateRequest,
    UserAddressResponse,
    UserAddressesResponse,
    UserAddressUpdateRequest,
)
from app.schemas.common import ApiError


def get_user_addresses(session: Session, user: User) -> UserAddressesResponse:
    rows = (
        session.execute(
            select(UserAddress)
            .where(UserAddress.user_id == user.id)
            .order_by(UserAddress.is_default.desc(), UserAddress.updated_at.desc(), UserAddress.id.desc())
        )
        .scalars()
        .all()
    )
    return UserAddressesResponse(items=[_to_response(row) for row in rows])


def create_user_address(
    session: Session,
    user: User,
    request: UserAddressCreateRequest,
) -> UserAddressResponse:
    should_be_default = request.is_default or not _has_any_address(session, user.id)
    if should_be_default:
        _unset_default_addresses(session, user.id)

    now = datetime.now(UTC)
    row = UserAddress(
        user_id=user.id,
        recipient_name=_required_text(request.recipient_name, "recipient_name"),
        phone=_required_text(request.phone, "phone"),
        postal_code=_required_text(request.postal_code, "postal_code"),
        address1=_required_text(request.address1, "address1"),
        address2=_optional_text(request.address2),
        delivery_memo=_optional_text(request.delivery_memo),
        is_default=should_be_default,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return _to_response(row)


def update_user_address(
    session: Session,
    user: User,
    address_id: int,
    request: UserAddressUpdateRequest,
) -> UserAddressResponse:
    row = _load_owned_address(session, user.id, address_id)
    fields_set = _fields_set(request)

    if "recipient_name" in fields_set:
        if request.recipient_name is None:
            raise ApiError(400, "INVALID_ADDRESS", "recipient_name is required.")
        row.recipient_name = _required_text(request.recipient_name, "recipient_name")
    if "phone" in fields_set:
        if request.phone is None:
            raise ApiError(400, "INVALID_ADDRESS", "phone is required.")
        row.phone = _required_text(request.phone, "phone")
    if "postal_code" in fields_set:
        if request.postal_code is None:
            raise ApiError(400, "INVALID_ADDRESS", "postal_code is required.")
        row.postal_code = _required_text(request.postal_code, "postal_code")
    if "address1" in fields_set:
        if request.address1 is None:
            raise ApiError(400, "INVALID_ADDRESS", "address1 is required.")
        row.address1 = _required_text(request.address1, "address1")
    if "address2" in fields_set:
        row.address2 = _optional_text(request.address2)
    if "delivery_memo" in fields_set:
        row.delivery_memo = _optional_text(request.delivery_memo)

    if request.is_default is True:
        _unset_default_addresses(session, user.id)
        row.is_default = True
    elif request.is_default is False and row.is_default:
        row.is_default = False
        replacement = _find_latest_other_address(session, user.id, row.id)
        if replacement is None:
            row.is_default = True
        else:
            replacement.is_default = True
            replacement.updated_at = datetime.now(UTC)

    row.updated_at = datetime.now(UTC)
    session.flush()
    return _to_response(row)


def delete_user_address(session: Session, user: User, address_id: int) -> bool:
    row = _load_owned_address(session, user.id, address_id)
    was_default = row.is_default
    session.delete(row)
    session.flush()

    if was_default:
        replacement = _find_latest_other_address(session, user.id, row.id)
        if replacement is not None:
            replacement.is_default = True
            replacement.updated_at = datetime.now(UTC)
            session.flush()

    return True


def _load_owned_address(session: Session, user_id: int, address_id: int) -> UserAddress:
    row = session.execute(
        select(UserAddress).where(
            UserAddress.id == address_id,
            UserAddress.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "ADDRESS_NOT_FOUND", "Address was not found.")
    return row


def _has_any_address(session: Session, user_id: int) -> bool:
    return (
        session.execute(select(UserAddress.id).where(UserAddress.user_id == user_id).limit(1))
        .scalars()
        .first()
        is not None
    )


def _unset_default_addresses(session: Session, user_id: int) -> None:
    rows = session.execute(select(UserAddress).where(UserAddress.user_id == user_id)).scalars().all()
    for row in rows:
        row.is_default = False
        row.updated_at = datetime.now(UTC)


def _find_latest_other_address(session: Session, user_id: int, address_id: int) -> UserAddress | None:
    return (
        session.execute(
            select(UserAddress)
            .where(
                UserAddress.user_id == user_id,
                UserAddress.id != address_id,
            )
            .order_by(UserAddress.updated_at.desc(), UserAddress.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ApiError(400, "INVALID_ADDRESS", f"{field_name} is required.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _fields_set(request: UserAddressUpdateRequest) -> set[str]:
    if hasattr(request, "model_fields_set"):
        return set(request.model_fields_set)
    return set(request.__fields_set__)


def _to_response(row: UserAddress) -> UserAddressResponse:
    return UserAddressResponse(
        id=row.id,
        recipient_name=row.recipient_name,
        phone=row.phone,
        postal_code=row.postal_code,
        address1=row.address1,
        address2=row.address2,
        delivery_memo=row.delivery_memo,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
