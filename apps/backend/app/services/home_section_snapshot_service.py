from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.recommendation import HomeSectionSnapshot
from app.schemas.home import HomeProductSectionResponse, HomeSection, HomeSectionProduct

if TYPE_CHECKING:
    from app.db.models.auth import User
    from app.services.home_sections import _ForYouContext


HOME_EVIDENCE_SNAPSHOT_SECTION_ID = "evidence_picks"
HOME_EVIDENCE_SNAPSHOT_CONTEXT = "overall"
HOME_FOR_YOU_SNAPSHOT_SECTION_ID = "for_you"
HOME_GUEST_SKIN_TYPES = ("건성", "지성", "복합성", "수부지", "중성")
HOME_EVIDENCE_SNAPSHOT_SIZE = 50
HOME_FOR_YOU_SNAPSHOT_SIZE = 200
HOME_SNAPSHOT_ALGORITHM_VERSION = "home_section_snapshot_v4"
HOME_SNAPSHOT_MAX_AGE = timedelta(days=2)


def get_evidence_snapshot_response(
    session: Session,
    *,
    limit: int,
) -> HomeProductSectionResponse | None:
    snapshots, metadata = _load_snapshot(
        session,
        section_id=HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
        context_key=HOME_EVIDENCE_SNAPSHOT_CONTEXT,
        required_count=limit,
    )
    _set_metadata(session, "home_evidence_snapshot_metadata", metadata)
    if snapshots is None:
        return None
    return _build_static_snapshot_response(
        session,
        snapshots=snapshots,
        section_id=HOME_EVIDENCE_SNAPSHOT_SECTION_ID,
        title="성분 근거가 좋은 제품",
        subtitle="효능 성분과 근거 점수가 잘 잡힌 제품",
        section_type="evidence_rank",
        algorithm="home_v1_snapshot_evidence",
        limit=limit,
    )


def get_for_you_snapshot_response(
    session: Session,
    *,
    context: _ForYouContext,
    current_user: User | None,
    requested_sensitivity: str | None,
    concern: str | None,
    effect: str | None,
    category_code: str | None,
    limit: int,
) -> HomeProductSectionResponse | None:
    from app.services import home_sections

    if not _is_canonical_request(
        requested_sensitivity=requested_sensitivity,
        concern=concern,
        effect=effect,
        category_code=category_code,
    ):
        _set_metadata(session, "home_for_you_snapshot_metadata", _fallback_metadata(None))
        return None
    if context.skin_type not in HOME_GUEST_SKIN_TYPES:
        _set_metadata(session, "home_for_you_snapshot_metadata", _fallback_metadata(None))
        return None
    if current_user is None and context.request_skin_type is None:
        _set_metadata(session, "home_for_you_snapshot_metadata", _fallback_metadata(None))
        return None

    context_key = guest_skin_snapshot_context(context.skin_type)
    snapshots, metadata = _load_snapshot(
        session,
        section_id=HOME_FOR_YOU_SNAPSHOT_SECTION_ID,
        context_key=context_key,
        required_count=limit,
    )
    if snapshots is None:
        _set_metadata(session, "home_for_you_snapshot_metadata", metadata)
        return None

    if current_user is None:
        metadata["personalized_rerank_ms"] = 0
        _set_metadata(session, "home_for_you_snapshot_metadata", metadata)
        return _build_static_snapshot_response(
            session,
            snapshots=snapshots,
            section_id="for_you",
            title="너를 위한 추천",
            subtitle="피부 타입에 맞춘 추천 제품",
            section_type="personalized_rank",
            algorithm="home_v2_for_you_guest_snapshot",
            limit=limit,
            skin_type=context.skin_type,
            sensitivity=context.sensitivity,
            personalization_sources=context.sources,
        )

    started_at = perf_counter()
    product_ids = [snapshot.product_id for snapshot in snapshots]
    products = home_sections._load_products(session, category_code=None, product_ids=product_ids)
    signals_by_product_id = home_sections._load_product_signals(session, product_ids)
    skin_profiles_by_product_id = home_sections._load_skin_profiles(session, product_ids)
    purchase_urls_by_product_id = home_sections._load_purchase_urls(session, product_ids)
    popularity_scores_by_product_id = home_sections._load_market_popularity_scores(session, product_ids)
    ranked = sorted(
        (
            (
                home_sections._for_you_score(
                    product,
                    signals_by_product_id.get(product.db_product_id, home_sections._empty_signals()),
                    skin_profiles_by_product_id.get(product.db_product_id),
                    popularity_scores_by_product_id.get(product.db_product_id),
                    context,
                ),
                product,
            )
            for product in products
        ),
        key=lambda item: (-item[0], item[1].product_id),
    )
    metadata["personalized_rerank_ms"] = round((perf_counter() - started_at) * 1000, 2)
    _set_metadata(session, "home_for_you_snapshot_metadata", metadata)
    section = HomeSection(
        section_id="for_you",
        title="너를 위한 추천",
        subtitle="피부 프로필과 행동 신호를 함께 본 맞춤 후보",
        section_type="personalized_rank",
        algorithm="home_v2_for_you_snapshot_rerank",
        products=[
            home_sections._build_section_product(
                "recommended_for_you",
                product,
                signals_by_product_id.get(product.db_product_id, home_sections._empty_signals()),
                purchase_urls_by_product_id.get(product.db_product_id),
                score,
            )
            for score, product in ranked[:limit]
        ],
    )
    return home_sections._section_to_response(
        section,
        category_code=None,
        limit=limit,
        skin_type=context.skin_type,
        sensitivity=context.sensitivity,
        personalization_sources=context.sources,
    )


def snapshot_metadata(
    session: Session,
    *,
    section_id: str,
    context_key: str | None,
    user_context: bool = False,
) -> dict[str, int | str | bool | None]:
    key = "home_for_you_snapshot_metadata" if user_context else "home_evidence_snapshot_metadata"
    saved = session.info.pop(key, None)
    if saved is not None:
        return saved
    if context_key is None:
        return _fallback_metadata(None)
    _, metadata = _load_snapshot(
        session,
        section_id=section_id,
        context_key=context_key,
        required_count=1,
    )
    return metadata


def guest_skin_snapshot_context(skin_type: str) -> str:
    return f"guest:skin_type:{skin_type}"


def _build_static_snapshot_response(
    session: Session,
    *,
    snapshots: list[HomeSectionSnapshot],
    section_id: str,
    title: str,
    subtitle: str,
    section_type: str,
    algorithm: str,
    limit: int,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    personalization_sources: tuple[str, ...] = (),
) -> HomeProductSectionResponse:
    from app.services import home_sections

    requested_snapshots = snapshots[:limit]
    products_by_id = {
        product.db_product_id: product
        for product in home_sections._load_products(
            session,
            category_code=None,
            product_ids=[snapshot.product_id for snapshot in requested_snapshots],
        )
    }
    purchase_urls_by_product_id = home_sections._load_purchase_urls(session, list(products_by_id))
    products: list[HomeSectionProduct] = []
    for snapshot in requested_snapshots:
        product = products_by_id.get(snapshot.product_id)
        if product is None:
            continue
        products.append(
            HomeSectionProduct(
                product_id=product.product_id,
                brand=product.brand,
                name=product.name,
                category_code=product.category_code,
                category_name=product.category_name,
                thumbnail_url=product.thumbnail_url,
                lowest_price=product.lowest_price,
                original_price=None,
                discount_rate=None,
                purchase_url=purchase_urls_by_product_id.get(product.db_product_id),
                badges=list(snapshot.badges or []),
                tags=list(snapshot.tags or []),
                reason_summary=snapshot.reason_summary,
                display_score=snapshot.display_score,
                sales_status=product.sales_status,
                stock_status=product.stock_status,
                available_quantity=product.available_quantity,
                in_stock=product.in_stock,
            )
        )
    section = HomeSection(
        section_id=section_id,
        title=title,
        subtitle=subtitle,
        section_type=section_type,
        algorithm=algorithm,
        products=products,
    )
    return home_sections._section_to_response(
        section,
        category_code=None,
        limit=limit,
        skin_type=skin_type,
        sensitivity=sensitivity,
        personalization_sources=personalization_sources,
    )


def _load_snapshot(
    session: Session,
    *,
    section_id: str,
    context_key: str,
    required_count: int,
) -> tuple[list[HomeSectionSnapshot] | None, dict[str, int | str | bool | None]]:
    rows = session.execute(
        select(HomeSectionSnapshot)
        .where(
            HomeSectionSnapshot.section_id == section_id,
            HomeSectionSnapshot.context_key == context_key,
        )
        .order_by(HomeSectionSnapshot.rank_order.asc())
    ).scalars().all()
    if not rows:
        return None, _fallback_metadata(context_key)
    computed_at = _as_utc(rows[0].computed_at)
    age_ms = max(0, int((datetime.now(UTC) - computed_at).total_seconds() * 1000))
    current = (
        len(rows) >= required_count
        and all(row.algorithm_version == HOME_SNAPSHOT_ALGORITHM_VERSION for row in rows)
        and age_ms <= int(HOME_SNAPSHOT_MAX_AGE.total_seconds() * 1000)
    )
    metadata: dict[str, int | str | bool | None] = {
        "snapshot_hit": current,
        "snapshot_context": context_key,
        "snapshot_age_ms": age_ms,
        "snapshot_candidate_count": len(rows),
        "fallback_used": not current,
        "personalized_rerank_ms": 0,
    }
    return (rows if current else None), metadata


def _is_canonical_request(
    *,
    requested_sensitivity: str | None,
    concern: str | None,
    effect: str | None,
    category_code: str | None,
) -> bool:
    from app.services import home_sections

    return (
        not home_sections._normalize_optional_text(concern)
        and not home_sections._normalize_optional_text(effect)
        and not home_sections._normalize_optional_text(category_code)
        and (
            requested_sensitivity is None
            or home_sections._normalize_sensitivity(requested_sensitivity) == "보통"
        )
    )


def _fallback_metadata(context_key: str | None) -> dict[str, int | str | bool | None]:
    return {
        "snapshot_hit": False,
        "snapshot_context": context_key,
        "snapshot_age_ms": None,
        "snapshot_candidate_count": 0,
        "fallback_used": True,
        "personalized_rerank_ms": 0,
    }


def _set_metadata(session: Session, key: str, metadata: dict[str, int | str | bool | None]) -> None:
    session.info[key] = metadata


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
