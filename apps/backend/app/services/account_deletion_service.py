from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models.agent import AgentToolCall
from app.db.models.auth import AuthAccount, AuthSession, PasswordResetToken, RefreshToken, User
from app.db.models.commerce import OrderShippingAddress, RecentView, UserAddress, Wishlist
from app.db.models.events import EventLog
from app.db.models.recommendation import UserPreferenceProfile
from app.db.models.review import ProductReview
from app.db.models.skin import SkinProfile, SkinTestAnswer, SkinTestResult
from app.schemas.common import ApiError


def delete_user_account(session: Session, user: User) -> None:
    if user.role == "ADMIN":
        raise ApiError(403, "ADMIN_ACCOUNT_DELETION_NOT_ALLOWED", "관리자 계정은 탈퇴할 수 없습니다.")

    user_id = int(user.id)
    now = datetime.now(UTC)

    _delete_user_addresses(session, user_id)
    _delete_skin_data(session, user_id)

    session.execute(delete(Wishlist).where(Wishlist.user_id == user_id))
    session.execute(delete(RecentView).where(RecentView.user_id == user_id))
    session.execute(delete(UserPreferenceProfile).where(UserPreferenceProfile.user_id == user_id))

    session.execute(update(ProductReview).where(ProductReview.user_id == user_id).values(user_id=None))
    session.execute(update(EventLog).where(EventLog.user_id == user_id).values(user_id=None))
    session.execute(update(AgentToolCall).where(AgentToolCall.user_id == user_id).values(user_id=None))

    session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .values(replaced_by_token_id=None)
    )
    session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    session.execute(delete(AuthAccount).where(AuthAccount.user_id == user_id))
    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))

    user.email = f"deleted-{user_id}@deleted.local"
    user.display_name = None
    user.phone = None
    user.status = "DELETED"
    user.last_login_at = None
    user.updated_at = now
    session.flush()


def _delete_user_addresses(session: Session, user_id: int) -> None:
    address_ids = list(
        session.execute(select(UserAddress.id).where(UserAddress.user_id == user_id)).scalars()
    )
    if not address_ids:
        return
    session.execute(
        update(OrderShippingAddress)
        .where(OrderShippingAddress.user_address_id.in_(address_ids))
        .values(user_address_id=None)
    )
    session.execute(delete(UserAddress).where(UserAddress.id.in_(address_ids)))


def _delete_skin_data(session: Session, user_id: int) -> None:
    result_ids = list(
        session.execute(select(SkinTestResult.id).where(SkinTestResult.user_id == user_id)).scalars()
    )
    profile_ids = list(
        session.execute(select(SkinProfile.id).where(SkinProfile.user_id == user_id)).scalars()
    )

    if result_ids:
        session.execute(delete(SkinTestAnswer).where(SkinTestAnswer.result_id.in_(result_ids)))
        session.execute(delete(SkinTestResult).where(SkinTestResult.id.in_(result_ids)))
    if profile_ids:
        session.execute(
            update(SkinTestResult)
            .where(SkinTestResult.applied_profile_id.in_(profile_ids))
            .values(applied_profile_id=None)
        )
        session.execute(delete(SkinProfile).where(SkinProfile.id.in_(profile_ids)))
