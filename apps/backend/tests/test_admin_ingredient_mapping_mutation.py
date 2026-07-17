"""P1-M2-A Chunk 5 관리자 성분 매핑 판정 서비스 focused 테스트.

승인·보류·반려·재검토의 전이/멱등/사유 규칙은 PostgreSQL 전용 분석 SQL(그룹 존재
확인·suggestion 스냅샷)에 얽혀 있어 SQLite 픽스처로 전체 경로를 실행할 수 없다.
그 경로(전이·409·멱등·이벤트 이전 target 보존·canonical 검색)는 실 PostgreSQL로
수동 검증했다. 여기서는 SQL 실행 전에 결정되는 순수 규칙과 인가/검증만 자동
검증한다: 전이 가드, 사유 필수/선택 정규화, 라우트 401/403.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.session import get_db
from app.main import app
from app.schemas.common import ApiError
from app.services.admin import ingredient_mapping_mutation_service as mut


ADMIN_EMAIL = "admin-mapping-mutation@example.com"
USER_EMAIL = "user-mapping-mutation@example.com"


# --- 전이 가드 -------------------------------------------------------------

def test_allowed_source_statuses_match_contract() -> None:
    assert mut._ALLOWED_SOURCE_STATUSES["APPROVE"] == {"PENDING", "HELD"}
    assert mut._ALLOWED_SOURCE_STATUSES["HOLD"] == {"PENDING", "HELD"}
    assert mut._ALLOWED_SOURCE_STATUSES["REJECT"] == {"PENDING", "HELD"}
    assert mut._ALLOWED_SOURCE_STATUSES["REOPEN"] == {"APPROVED", "REJECTED"}


@pytest.mark.parametrize(
    ("action", "current"),
    [
        ("APPROVE", "PENDING"),
        ("APPROVE", "HELD"),
        ("HOLD", "PENDING"),
        ("REJECT", "HELD"),
        ("REOPEN", "APPROVED"),
        ("REOPEN", "REJECTED"),
    ],
)
def test_guard_transition_allows_valid(action: str, current: str) -> None:
    mut._guard_transition(action, current)  # 예외 없어야 함


@pytest.mark.parametrize(
    ("action", "current", "expected_code"),
    [
        ("APPROVE", "REJECTED", "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED"),
        ("HOLD", "APPROVED", "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED"),
        ("REJECT", "APPROVED", "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED"),
        ("REOPEN", "PENDING", "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED"),
        ("REOPEN", "HELD", "INGREDIENT_MAPPING_TRANSITION_NOT_ALLOWED"),
    ],
)
def test_guard_transition_blocks_invalid(action: str, current: str, expected_code: str) -> None:
    with pytest.raises(ApiError) as exc:
        mut._guard_transition(action, current)
    assert exc.value.status_code == 409
    assert exc.value.code == expected_code


# --- 사유 정규화 -----------------------------------------------------------

def test_require_reason_trims_and_rejects_blank() -> None:
    assert mut._require_reason("  확인 필요 ") == "확인 필요"
    for blank in ("", "   ", "\t\n"):
        with pytest.raises(ApiError) as exc:
            mut._require_reason(blank)
        assert exc.value.code == "DECISION_REASON_REQUIRED"


def test_require_reason_truncates_to_limit() -> None:
    long = "가" * (mut.MAX_DECISION_REASON_LENGTH + 50)
    assert len(mut._require_reason(long)) == mut.MAX_DECISION_REASON_LENGTH


def test_normalize_optional_reason() -> None:
    assert mut._normalize_optional_reason(None) is None
    assert mut._normalize_optional_reason("   ") is None
    assert mut._normalize_optional_reason("  ok ") == "ok"
    assert len(mut._normalize_optional_reason("나" * 2000)) == mut.MAX_DECISION_REASON_LENGTH


# --- 라우트 인가 (SQL 실행 전) ---------------------------------------------

@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _signup(client: TestClient, email: str, nickname: str) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200


def _promote_admin(db_engine: Engine, email: str) -> None:
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def test_approve_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/admin/ingredient-mappings/ing_pending_x/approve",
        json={"normalized_source_name": "x", "target_ingredient_code": "ing_y"},
    )
    assert response.status_code == 401


def test_hold_forbidden_for_non_admin(client: TestClient) -> None:
    _signup(client, USER_EMAIL, "plain-user-mut")
    response = client.post(
        "/api/admin/ingredient-mappings/ing_pending_x/hold",
        json={"normalized_source_name": "x", "decision_reason": "사유"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_hold_missing_reason_is_422(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mut")
    _promote_admin(db_engine, ADMIN_EMAIL)
    # decision_reason 누락은 Pydantic min_length 검증 → 전역 처리기로 400 INVALID_INPUT.
    response = client.post(
        "/api/admin/ingredient-mappings/ing_pending_x/hold",
        json={"normalized_source_name": "x"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"
