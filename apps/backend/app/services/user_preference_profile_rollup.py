from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.recommendation import UserPreferenceProfile
from app.services.recommendation_feature_rollup import upsert_rows
from app.services.recommendation_feature_versions import (
    USER_PREFERENCE_PROFILE_VERSION,
)
from app.services.scoring import (
    BEHAVIOR_POSITIVE_SOURCE_WEIGHTS,
    build_behavior_preference_profile,
    load_behavior_events,
    load_behavior_product_signals,
)


@dataclass(frozen=True)
class UserPreferenceProfileRollupResult:
    requested_user_count: int
    user_count: int
    profile_count: int
    stale_profile_count: int
    event_count: int
    batch_count: int
    computed_at: datetime
    profile_version: str = USER_PREFERENCE_PROFILE_VERSION


def rollup_user_preference_profiles(
    session: Session,
    *,
    user_ids: tuple[int, ...] | None = None,
    batch_size: int = 100,
    computed_at: datetime | None = None,
) -> UserPreferenceProfileRollupResult:
    normalized_batch_size = max(1, int(batch_size))
    normalized_user_ids = _load_target_user_ids(session, user_ids)
    now = computed_at or datetime.now(UTC)
    profile_count = 0
    stale_profile_count = 0
    event_count = 0
    batch_count = 0

    for start in range(0, len(normalized_user_ids), normalized_batch_size):
        batch_count += 1
        batch_user_ids = normalized_user_ids[start : start + normalized_batch_size]
        events_by_user = {
            user_id: load_behavior_events(session, user_id, now)
            for user_id in batch_user_ids
        }
        signal_product_ids = sorted(
            {
                event.product_db_id
                for positive_events, negative_events in events_by_user.values()
                for event in (*positive_events, *negative_events)
            }
        )
        signals_by_product = load_behavior_product_signals(
            session,
            signal_product_ids,
        )
        rows: list[dict[str, object]] = []
        current_pairs: list[tuple[int, str]] = []

        for user_id in batch_user_ids:
            positive_events, negative_events = events_by_user[user_id]
            source_events = {
                source: [
                    event
                    for event in positive_events
                    if event.source == source
                    and event.product_db_id in signals_by_product
                ]
                for source in BEHAVIOR_POSITIVE_SOURCE_WEIGHTS
            }
            source_events["negative_feedback"] = [
                event
                for event in negative_events
                if event.product_db_id in signals_by_product
            ]

            for source, events in source_events.items():
                if not events:
                    continue
                profile = build_behavior_preference_profile(
                    events,
                    signals_by_product,
                    now,
                )
                current_pairs.append((user_id, source))
                event_count += len(events)
                rows.append(
                    {
                        "user_id": user_id,
                        "source": source,
                        "category_scores": profile.category_scores,
                        "brand_scores": profile.brand_scores,
                        "ingredient_scores": profile.ingredient_scores,
                        "effect_scores": profile.effect_scores,
                        "price_band_scores": profile.price_band_scores,
                        "product_ids": list(profile.product_ids),
                        "total_weight": _decimal(profile.total_weight),
                        "effect_top3_sum": _decimal(profile.effect_top3_sum),
                        "ingredient_top5_sum": _decimal(profile.ingredient_top5_sum),
                        "category_max": _decimal(profile.category_max),
                        "brand_max": _decimal(profile.brand_max),
                        "price_band_max": _decimal(profile.price_band_max),
                        "event_count": len(events),
                        "last_event_at": _latest_event_at(events, now),
                        "profile_version": USER_PREFERENCE_PROFILE_VERSION,
                        "computed_at": now,
                    }
                )

        stale_profile_count += _delete_stale_profiles(
            session,
            batch_user_ids,
            current_pairs,
        )
        upsert_rows(
            session,
            UserPreferenceProfile,
            rows,
            conflict_columns=("user_id", "source"),
            update_columns=(
                "category_scores",
                "brand_scores",
                "ingredient_scores",
                "effect_scores",
                "price_band_scores",
                "product_ids",
                "total_weight",
                "effect_top3_sum",
                "ingredient_top5_sum",
                "category_max",
                "brand_max",
                "price_band_max",
                "event_count",
                "last_event_at",
                "profile_version",
                "computed_at",
            ),
        )
        profile_count += len(rows)
        session.flush()

    return UserPreferenceProfileRollupResult(
        requested_user_count=(
            len(user_ids) if user_ids is not None else len(normalized_user_ids)
        ),
        user_count=len(normalized_user_ids),
        profile_count=profile_count,
        stale_profile_count=stale_profile_count,
        event_count=event_count,
        batch_count=batch_count,
        computed_at=now,
    )


def _load_target_user_ids(
    session: Session,
    user_ids: tuple[int, ...] | None,
) -> list[int]:
    statement = select(User.id).order_by(User.id.asc())
    if user_ids is not None:
        normalized_ids = sorted({int(user_id) for user_id in user_ids})
        if not normalized_ids:
            return []
        statement = statement.where(User.id.in_(normalized_ids))
    return [int(user_id) for user_id in session.execute(statement).scalars()]


def _delete_stale_profiles(
    session: Session,
    user_ids: list[int],
    current_pairs: list[tuple[int, str]],
) -> int:
    statement = delete(UserPreferenceProfile).where(
        UserPreferenceProfile.user_id.in_(user_ids)
    )
    if current_pairs:
        statement = statement.where(
            tuple_(
                UserPreferenceProfile.user_id,
                UserPreferenceProfile.source,
            ).not_in(current_pairs)
        )
    result = session.execute(statement)
    return max(0, int(result.rowcount or 0))


def _latest_event_at(events: list, fallback: datetime) -> datetime:
    occurred_at_values = [
        _normalize_datetime(event.occurred_at)
        for event in events
        if event.occurred_at is not None
    ]
    return max(occurred_at_values, default=_normalize_datetime(fallback))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))

