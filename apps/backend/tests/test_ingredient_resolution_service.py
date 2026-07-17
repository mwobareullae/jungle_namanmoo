"""P1-M3-B Chunk 1 성분 해소 서비스 focused 테스트.

계약 §5 순서(ADMIN 판정 → canonical → high alias)를 SQLite 픽스처로 실행 검증한다.
정규화 함수·pending code는 순수 함수라 세션 없이 검증한다.

실 PostgreSQL 전용 함정(예: 실제 lower/casefold 동치성)은 이 파일에서 다루지
않고, Chunk 3 bulk API 통합 테스트와 배포 전 수동 검증에서 확인한다.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.taxonomy import (
    Ingredient,
    IngredientAlias,
    IngredientMappingReview,
)
from app.schemas.common import ApiError
from app.services import ingredient_resolution_service as svc


# --- 순수 함수 --------------------------------------------------------------


def test_normalize_for_resolution_casefold_and_whitespace() -> None:
    assert svc.normalize_for_resolution("Niacinamide") == "niacinamide"
    assert svc.normalize_for_resolution(" Nia  cin\tamide\n") == "niacinamide"
    # 합자 ﬁ 는 casefold 에서 'fi' 로 풀린다.
    assert svc.normalize_for_resolution("Niacinamiﬁcation") == "niacinamification"


def test_normalize_for_review_lookup_lower_and_whitespace_keeps_ligature() -> None:
    # lower 는 합자를 보존한다. matview 및 review 테이블 키와 정확히 일치해야 한다.
    assert svc.normalize_for_review_lookup("Niacinamiﬁcation") == "niacinamiﬁcation"
    assert svc.normalize_for_review_lookup(" A B ") == "ab"


def test_postgres_review_lookup_expression_matches_pending_groups_view() -> None:
    """운영 DB에서는 Python lower가 아니라 0048과 같은 SQL 식을 사용한다."""
    from sqlalchemy import literal, select

    compiled = str(
        select(svc._postgres_review_lookup_expression(literal("A B"))).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "lower(regexp_replace(coalesce(" in compiled


def test_compute_pending_code_is_deterministic_and_prefixed() -> None:
    code_one = svc.compute_pending_code("niacinamide")
    code_two = svc.compute_pending_code("niacinamide")
    assert code_one == code_two
    assert code_one.startswith(svc.PENDING_ADMIN_PREFIX)
    # sha256 앞 32자.
    assert len(code_one) == len(svc.PENDING_ADMIN_PREFIX) + 32
    # 다른 정규화 값은 다른 code.
    assert code_one != svc.compute_pending_code("water")


# --- 세션 픽스처 ------------------------------------------------------------


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(db_engine: Engine) -> Generator[Session, None, None]:
    with Session(db_engine) as sess:
        yield sess


def _add_canonical(sess: Session, code: str, name_ko: str, normalized: str) -> Ingredient:
    ingredient = Ingredient(
        ingredient_code=code,
        name_ko=name_ko,
        name_en=None,
        normalized_name=normalized,
        is_active=True,
    )
    sess.add(ingredient)
    sess.flush()
    return ingredient


def _add_alias(
    sess: Session,
    ingredient_id: int,
    alias: str,
    normalized_alias: str,
    *,
    alias_type: str = "en",
    confidence: str = "high",
) -> IngredientAlias:
    row = IngredientAlias(
        ingredient_id=ingredient_id,
        alias=alias,
        normalized_alias=normalized_alias,
        alias_type=alias_type,
        confidence=confidence,
    )
    sess.add(row)
    sess.flush()
    return row


def _add_admin(sess: Session, email: str = "admin@example.com") -> User:
    user = User(email=email, role="ADMIN")
    sess.add(user)
    sess.flush()
    return user


def _add_review(
    sess: Session,
    *,
    source_id: int,
    review_lookup_name: str,
    status: str,
    target_id: int | None,
    reviewer_id: int,
    reason: str | None = None,
) -> IngredientMappingReview:
    review = IngredientMappingReview(
        source_ingredient_id=source_id,
        source_ingredient_name=None,
        normalized_source_name=review_lookup_name,
        target_ingredient_id=target_id,
        status=status,
        decision_reason=reason,
        reviewed_by_user_id=reviewer_id,
        reviewed_at=datetime.now(timezone.utc),
    )
    sess.add(review)
    sess.flush()
    return review


# --- 검증(§11 INVALID_INGREDIENT_INPUT) -------------------------------------


def test_rejects_over_500_inputs(session: Session) -> None:
    inputs = [svc.ResolutionInput(raw_name=f"X{i}") for i in range(501)]
    with pytest.raises(ApiError) as ex:
        svc.resolve_many(session, inputs)
    assert ex.value.code == "INVALID_INGREDIENT_INPUT"


def test_rejects_blank_or_too_long_or_bad_confidence(session: Session) -> None:
    with pytest.raises(ApiError) as ex1:
        svc.resolve_many(session, [svc.ResolutionInput(raw_name="   ")])
    assert ex1.value.code == "INVALID_INGREDIENT_INPUT"

    with pytest.raises(ApiError) as ex2:
        svc.resolve_many(session, [svc.ResolutionInput(raw_name="A" * 256)])
    assert ex2.value.code == "INVALID_INGREDIENT_INPUT"

    with pytest.raises(ApiError) as ex3:
        svc.resolve_many(
            session, [svc.ResolutionInput(raw_name="water", content_confidence="perfect")]
        )
    assert ex3.value.code == "INVALID_INGREDIENT_INPUT"


def test_empty_input_returns_zero_counters(session: Session) -> None:
    outcome = svc.resolve_many(session, [])
    assert outcome.results == []
    assert outcome.counters == {
        "input_count": 0,
        "saved_count": 0,
        "canonical_count": 0,
        "pending_count": 0,
        "duplicate_count": 0,
        "created_pending_count": 0,
    }


# --- §5 (3·4·5) canonical/alias exact --------------------------------------


def test_canonical_exact_match(session: Session) -> None:
    water = _add_canonical(session, "ing_water", "정제수", "water")
    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="Water")])
    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.ingredient_id == water.id
    assert result.resolution_status == svc.STATUS_CANONICAL
    assert result.match_source == svc.MATCH_CANONICAL_NAME
    assert outcome.counters["canonical_count"] == 1
    assert outcome.counters["created_pending_count"] == 0


def test_high_alias_hits_across_alias_types(session: Session) -> None:
    """BHA/AHA/PHA 등 abbrev 인데 high confidence 인 경우 매칭돼야 한다."""
    salicylic = _add_canonical(session, "ing_bha", "살리실릭애씨드", "salicylicacid")
    _add_alias(
        session,
        salicylic.id,
        "BHA",
        "bha",
        alias_type="abbrev",
        confidence="high",
    )
    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="BHA")])
    assert outcome.results[0].ingredient_id == salicylic.id
    assert outcome.results[0].match_source == svc.MATCH_ALIAS


def test_medium_or_low_alias_is_ignored(session: Session) -> None:
    other = _add_canonical(session, "ing_other", "기타성분", "othercompound")
    _add_alias(
        session, other.id, "loose", "loose", alias_type="synonym", confidence="medium"
    )
    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="loose")])
    # canonical 없고 medium alias는 무시 → pending 새로 생성.
    assert outcome.results[0].resolution_status == svc.STATUS_PENDING
    assert outcome.results[0].match_source == svc.MATCH_CREATED_PENDING


def test_conflicting_canonicals_go_to_pending(session: Session) -> None:
    """canonical 이름과 alias 가 서로 다른 canonical 을 가리키면 자동 확정 없이 pending."""
    a = _add_canonical(session, "ing_a", "A", "duplicate")
    b = _add_canonical(session, "ing_b", "B", "somethingelse")
    _add_alias(
        session, b.id, "duplicate", "duplicate", alias_type="synonym", confidence="high"
    )
    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="Duplicate")])
    assert outcome.results[0].resolution_status == svc.STATUS_PENDING
    assert outcome.results[0].match_source == svc.MATCH_CREATED_PENDING
    # 어느 쪽도 자동 채택되지 않는다.
    assert outcome.results[0].ingredient_id not in (a.id, b.id)


# --- §5 (2) ADMIN 판정 우선 ------------------------------------------------


def test_admin_approved_beats_later_added_canonical(session: Session) -> None:
    """관리자가 pending 을 APPROVED 한 뒤 나중에 canonical/alias 가 추가돼도
    ADMIN 판정이 우선이라는 회귀 (지현이 짚은 시나리오)."""
    admin = _add_admin(session)
    # 이번 계약으로 이미 만들어진 pending (레거시 아님).
    pending_code = svc.compute_pending_code("mysterious")
    pending = Ingredient(
        ingredient_code=pending_code,
        name_ko="mysterious",
        name_en=None,
        normalized_name="mysterious",
        is_active=True,
    )
    session.add(pending)
    session.flush()

    # 관리자가 다른 canonical 로 승인.
    target = _add_canonical(session, "ing_real", "진짜성분", "realone")
    _add_review(
        session,
        source_id=pending.id,
        review_lookup_name="mysterious",
        status="APPROVED",
        target_id=target.id,
        reviewer_id=admin.id,
    )

    # 지금 자동 룩업이 걸릴 만한 canonical/alias 도 추가돼 있다고 가정.
    conflicting = _add_canonical(session, "ing_conflict", "미스", "mysterious")

    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="mysterious")])
    result = outcome.results[0]
    assert result.ingredient_id == target.id, "ADMIN 승인이 exact 자동 룩업보다 우선"
    assert result.match_source == svc.MATCH_ADMIN_APPROVED
    assert conflicting.id != target.id


def test_held_or_rejected_keeps_pending(session: Session) -> None:
    admin = _add_admin(session)
    pending_code = svc.compute_pending_code("shady")
    pending = Ingredient(
        ingredient_code=pending_code,
        name_ko="shady",
        name_en=None,
        normalized_name="shady",
        is_active=True,
    )
    session.add(pending)
    session.flush()
    # 자동 룩업이 걸릴 canonical 도 있지만, 관리자 HELD 라 자동 해소 금지.
    _add_canonical(session, "ing_maybe", "혹시", "shady")
    _add_review(
        session,
        source_id=pending.id,
        review_lookup_name="shady",
        status="HELD",
        target_id=None,
        reviewer_id=admin.id,
        reason="확인 필요",
    )
    outcome = svc.resolve_many(session, [svc.ResolutionInput(raw_name="shady")])
    result = outcome.results[0]
    assert result.ingredient_id == pending.id
    assert result.match_source == svc.MATCH_EXISTING_PENDING
    assert result.resolution_status == svc.STATUS_PENDING


def test_approved_inactive_target_keeps_pending(session: Session) -> None:
    """APPROVED여도 target이 비활성이면 활성 canonical로 자동 연결하지 않는다."""
    admin = _add_admin(session)
    pending_code = svc.compute_pending_code("inactive-target")
    pending = Ingredient(
        ingredient_code=pending_code,
        name_ko="inactive-target",
        name_en=None,
        normalized_name="inactive-target",
        is_active=True,
    )
    session.add(pending)
    session.flush()
    inactive_target = _add_canonical(
        session,
        "ing_inactive_target",
        "비활성 성분",
        "inactivecanonical",
    )
    inactive_target.is_active = False
    session.flush()
    _add_review(
        session,
        source_id=pending.id,
        review_lookup_name="inactive-target",
        status="APPROVED",
        target_id=inactive_target.id,
        reviewer_id=admin.id,
    )

    outcome = svc.resolve_many(
        session, [svc.ResolutionInput(raw_name="inactive-target")]
    )
    result = outcome.results[0]
    assert result.ingredient_id == pending.id
    assert result.resolution_status == svc.STATUS_PENDING
    assert result.match_source == svc.MATCH_EXISTING_PENDING


# --- 합자 회귀 (핵심 §5-2) --------------------------------------------------


def test_ligature_regression_casefold_pending_lower_review(session: Session) -> None:
    """ﬁ 입력 → casefold 로 pending 생성 → 관리자가 lower 정규화 키로 판정
    저장 → 다음 입력에서 lower 로 조회해 자동 적용."""
    admin = _add_admin(session)

    # 첫 입력: pending 생성. resolution 키(=casefold)는 'fi' 로 풀림.
    first = svc.resolve_many(session, [svc.ResolutionInput(raw_name="Niaﬁ")])
    pending_result = first.results[0]
    assert pending_result.resolution_status == svc.STATUS_PENDING
    assert pending_result.match_source == svc.MATCH_CREATED_PENDING
    # 정규화 값에는 ﬁ 가 fi 로 풀려 들어가 있다.
    assert pending_result.normalized_name == "niafi"
    pending_ingredient = session.get(Ingredient, pending_result.ingredient_id)
    assert pending_ingredient is not None

    # 관리자가 target canonical 로 APPROVED. review 키는 lower(=ﬁ 보존).
    target = _add_canonical(session, "ing_real2", "니아신", "niafi")
    review_key = svc.normalize_for_review_lookup("Niaﬁ")
    assert review_key == "niaﬁ", "lower 는 합자를 보존해야 한다"
    _add_review(
        session,
        source_id=pending_ingredient.id,
        review_lookup_name=review_key,
        status="APPROVED",
        target_id=target.id,
        reviewer_id=admin.id,
    )

    # 두 번째 입력: 같은 합자 표기 → ADMIN 판정으로 자동 연결.
    second = svc.resolve_many(session, [svc.ResolutionInput(raw_name="Niaﬁ")])
    assert second.results[0].ingredient_id == target.id
    assert second.results[0].match_source == svc.MATCH_ADMIN_APPROVED


# --- pending 재사용·동일 상품 내 중복 제거 ---------------------------------


def test_same_raw_name_within_request_reuses_pending(session: Session) -> None:
    outcome = svc.resolve_many(
        session,
        [
            svc.ResolutionInput(raw_name="OrphanX"),
            svc.ResolutionInput(raw_name="orphanx"),  # 정규화 시 동일
        ],
    )
    assert outcome.counters["created_pending_count"] == 1
    assert outcome.counters["duplicate_count"] == 1
    assert len(outcome.results) == 1


def test_pending_reused_across_requests(session: Session) -> None:
    first = svc.resolve_many(session, [svc.ResolutionInput(raw_name="Zeta")])
    first_id = first.results[0].ingredient_id
    second = svc.resolve_many(session, [svc.ResolutionInput(raw_name="ZETA")])
    assert second.results[0].ingredient_id == first_id
    assert second.results[0].match_source == svc.MATCH_EXISTING_PENDING
    assert second.counters["created_pending_count"] == 0


def test_pending_unique_race_reuses_existing_pending(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """초기 조회 뒤 다른 요청이 만든 pending의 unique 충돌은 재조회·재사용한다."""
    resolution = svc.normalize_for_resolution("Concurrent orphan")
    pending_code = svc.compute_pending_code(resolution)
    existing = Ingredient(
        ingredient_code=pending_code,
        name_ko="Concurrent orphan",
        name_en=None,
        normalized_name=resolution,
        is_active=True,
    )
    session.add(existing)
    session.commit()

    original_load_pending = svc._load_pending_by_code
    first_lookup = True

    def _simulate_race(
        current_session: Session, codes: set[str]
    ) -> dict[str, Ingredient]:
        nonlocal first_lookup
        if first_lookup:
            first_lookup = False
            return {}
        return original_load_pending(current_session, codes)

    monkeypatch.setattr(svc, "_load_pending_by_code", _simulate_race)
    outcome = svc.resolve_many(
        session, [svc.ResolutionInput(raw_name="Concurrent orphan")]
    )

    assert outcome.results[0].ingredient_id == existing.id
    assert outcome.results[0].match_source == svc.MATCH_EXISTING_PENDING
    assert outcome.counters["created_pending_count"] == 0


def test_display_order_and_duplicate_counter(session: Session) -> None:
    water = _add_canonical(session, "ing_water3", "정제수", "water")
    outcome = svc.resolve_many(
        session,
        [
            svc.ResolutionInput(raw_name="Water"),
            svc.ResolutionInput(raw_name="Glycerin"),
            svc.ResolutionInput(raw_name="water"),  # 중복 (canonical 기준)
        ],
    )
    assert [r.display_order for r in outcome.results] == [1, 2]
    assert outcome.results[0].ingredient_id == water.id
    assert outcome.counters["duplicate_count"] == 1
    assert outcome.counters["input_count"] == 3
    assert outcome.counters["saved_count"] == 2


# --- §6 pending code 충돌 ---------------------------------------------------


def test_pending_code_conflict_raises_409(session: Session) -> None:
    """같은 code 에 다른 normalized_name 이 저장돼 있으면 409."""
    resolution = svc.normalize_for_resolution("Corrupted")
    code = svc.compute_pending_code(resolution)
    # 계약을 위반한 잘못된 상태를 인위로 만들어 놓는다.
    bad = Ingredient(
        ingredient_code=code,
        name_ko="corrupted",
        name_en=None,
        normalized_name="somethingelse",
        is_active=True,
    )
    session.add(bad)
    session.flush()
    with pytest.raises(ApiError) as ex:
        svc.resolve_many(session, [svc.ResolutionInput(raw_name="Corrupted")])
    assert ex.value.status_code == 409
    assert ex.value.code == "INGREDIENT_PENDING_CODE_CONFLICT"


# --- 성능: batch 조회로 N+1 회피 -------------------------------------------


def test_resolve_many_avoids_n_plus_1_queries(db_engine: Engine) -> None:
    """입력 개수와 무관하게 SELECT 횟수가 상수여야 한다.

    현재 구현은 (pending 조회 · review 조회 · target 조회 · canonical 조회 · alias
    조회)로 상한 5개. 신규 pending 생성 시 flush 로 인한 추가 조회는 별개 카운트에
    포함되지 않는다. 이번 테스트는 canonical exact 만 있는 경우로 최소 조회를 잰다.
    """
    with Session(db_engine) as sess:
        for i in range(5):
            _add_canonical(sess, f"ing_{i}", f"성분{i}", f"n{i}")
        sess.commit()

    counter = {"selects": 0}

    @event.listens_for(db_engine, "before_cursor_execute")
    def _count(_conn, _cursor, statement, *_args, **_kwargs):
        if statement.lstrip().lower().startswith("select"):
            counter["selects"] += 1

    try:
        with Session(db_engine) as sess:
            svc.resolve_many(
                sess,
                [svc.ResolutionInput(raw_name=f"N{i}") for i in range(5)],
            )
    finally:
        event.remove(db_engine, "before_cursor_execute", _count)

    # 5건 canonical 해소에 SELECT ≤ 5 (pending·review·target·canonical·alias).
    # target 은 APPROVED 가 없어 배치가 비어 실제로는 스킵될 수 있다.
    assert counter["selects"] <= 5, f"N+1 의심: SELECT {counter['selects']}회"
