from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.skin import SkinProfile, SkinTestResult
from app.schemas.profile import (
    SignupSkinProfileRequest,
    SkinProfileData,
    SkinProfileResponse,
    SkinProfileUpdateRequest,
)


ALLOWED_SKIN_TYPES = {"건성", "지성", "복합성", "중성", "수부지"}
ALLOWED_SENSITIVITIES = {"낮음", "보통", "높음", "민감"}
SKIN_TYPE_ALIASES = {
    "dry": "건성",
    "oily": "지성",
    "combination": "복합성",
    "normal": "중성",
    "dehydrated_oily": "수부지",
    "water_oil": "수부지",
}
SENSITIVITY_ALIASES = {
    "low": "낮음",
    "normal": "보통",
    "mid": "보통",
    "medium": "보통",
    "high": "높음",
    "sensitive": "민감",
}
MANUAL_CONFIDENCE = Decimal("1.0000")
BAUMANN_SIGNAL_WEIGHT = Decimal("0.2500")


@dataclass(frozen=True)
class SkinServiceError(Exception):
    status_code: int
    code: str
    message: str


def get_skin_profile_response(session: Session, user: User) -> SkinProfileResponse:
    profile = load_skin_profile_for_user(session, user.id)
    if profile is None:
        return SkinProfileResponse(has_profile=False, profile=None)
    return SkinProfileResponse(has_profile=True, profile=to_skin_profile_data(session, profile))


def upsert_manual_skin_profile(
    session: Session,
    user: User,
    request: SkinProfileUpdateRequest,
) -> SkinProfileResponse:
    return _upsert_manual_skin_profile_values(
        session=session,
        user=user,
        skin_type_value=request.skin_type,
        sensitivity_value=request.sensitivity,
        avoid_ingredients_values=request.avoid_ingredients,
        concern_values=request.concerns,
    )


def upsert_signup_skin_profile(
    session: Session,
    user: User,
    request: SignupSkinProfileRequest,
) -> SkinProfileResponse:
    return _upsert_manual_skin_profile_values(
        session=session,
        user=user,
        skin_type_value=request.skin_type,
        sensitivity_value=request.sensitivity,
        avoid_ingredients_values=request.avoid_ingredients,
        concern_values=request.concerns,
    )


def load_skin_profile_for_user(session: Session, user_id: int) -> SkinProfile | None:
    return session.execute(select(SkinProfile).where(SkinProfile.user_id == user_id)).scalar_one_or_none()


def to_skin_profile_data(session: Session, profile: SkinProfile) -> SkinProfileData:
    latest_result_code = None
    if profile.latest_skin_test_result_id is not None:
        latest_result = session.get(SkinTestResult, profile.latest_skin_test_result_id)
        latest_result_code = latest_result.result_code if latest_result is not None else None

    return SkinProfileData(
        id=profile.id,
        user_id=profile.user_id,
        skin_type=profile.skin_type,
        sensitivity=profile.sensitivity,
        skin_type_source=profile.skin_type_source,
        sensitivity_source=profile.sensitivity_source,
        explicit_skin_type=profile.explicit_skin_type,
        explicit_sensitivity=profile.explicit_sensitivity,
        avoid_ingredients=list(profile.avoid_ingredients or []),
        baumann_type_code=profile.baumann_type_code,
        baumann_inferred_skin_type=profile.baumann_inferred_skin_type,
        baumann_inferred_sensitivity=profile.baumann_inferred_sensitivity,
        baumann_signal_weight=float(profile.baumann_signal_weight or BAUMANN_SIGNAL_WEIGHT),
        latest_skin_test_result_id=profile.latest_skin_test_result_id,
        latest_skin_test_result_code=latest_result_code,
        commerce_profile=profile.commerce_profile,
        source=profile.source,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _normalize_skin_type(value: str) -> str:
    normalized = SKIN_TYPE_ALIASES.get(value.strip(), value.strip())
    if normalized not in ALLOWED_SKIN_TYPES:
        raise SkinServiceError(400, "INVALID_SKIN_TYPE", "피부 타입 값이 올바르지 않습니다.")
    return normalized


def _normalize_sensitivity(value: str) -> str:
    normalized = SENSITIVITY_ALIASES.get(value.strip(), value.strip())
    if normalized not in ALLOWED_SENSITIVITIES:
        raise SkinServiceError(400, "INVALID_SENSITIVITY", "민감도 값이 올바르지 않습니다.")
    return normalized


def _normalize_avoid_ingredients(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _upsert_manual_skin_profile_values(
    *,
    session: Session,
    user: User,
    skin_type_value: str,
    sensitivity_value: str,
    avoid_ingredients_values: list[str],
    concern_values: list[str],
) -> SkinProfileResponse:
    skin_type = _normalize_skin_type(skin_type_value)
    sensitivity = _normalize_sensitivity(sensitivity_value)
    avoid_ingredients = _normalize_avoid_ingredients(avoid_ingredients_values)
    concerns = _normalize_avoid_ingredients(concern_values)

    now = datetime.now(UTC)
    profile = load_skin_profile_for_user(session, user.id)
    if profile is None:
        profile = SkinProfile(
            user_id=user.id,
            skin_type=skin_type,
            sensitivity=sensitivity,
            source="manual",
        )
        session.add(profile)

    profile.skin_type = skin_type
    profile.sensitivity = sensitivity
    profile.skin_type_source = "manual"
    profile.sensitivity_source = "manual"
    profile.skin_type_confidence = MANUAL_CONFIDENCE
    profile.sensitivity_confidence = MANUAL_CONFIDENCE
    profile.explicit_skin_type = skin_type
    profile.explicit_sensitivity = sensitivity
    profile.avoid_ingredients = avoid_ingredients
    profile.concern_profile_json = {"concerns": concerns}
    profile.source = "manual" if profile.baumann_type_code is None else "mixed"
    profile.updated_at = now
    session.flush()
    return SkinProfileResponse(has_profile=True, profile=to_skin_profile_data(session, profile))
