"""P1-M2-A Chunk 3 관리자 성분 매핑 검수 조회 focused 테스트.

목록·상세의 그룹 집계 SQL은 PostgreSQL 전용(`regexp_replace(...,'g')`,
`distinct on`, `filter (where)`, 행 비교, `ilike`)이라 SQLite 픽스처에서 실행할 수
없다. 그 SQL 정합성(그룹핑·review JOIN·페이지네이션·suggestion 매칭)은 실
PostgreSQL로 수동 검증했다. 여기서는 SQL 실행 전에 결정되는 순수 로직과
인가/검증 계약만 자동 검증한다:
  - 정규화(`normalize_source_name`)와 커서 왕복·위변조·필터 불일치 거부
  - suggestion 병합 규칙(alias 우선, 충돌 시 None, 없으면 None)
  - status/limit 검증 400, 라우트 401/403.
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
from app.services.admin import ingredient_mapping_service as svc


ADMIN_EMAIL = "admin-ingredient-mapping@example.com"
USER_EMAIL = "user-ingredient-mapping@example.com"


# --- 순수 로직 -------------------------------------------------------------

def test_normalize_source_name_lower_and_strip_whitespace() -> None:
    assert svc.normalize_source_name("Sodium  Hyaluronate ") == "sodiumhyaluronate"
    assert svc.normalize_source_name(" A\tB\nC ") == "abc"
    assert svc.normalize_source_name(None) == ""
    assert svc.normalize_source_name("") == ""


def test_cursor_round_trip_preserves_keys() -> None:
    token = svc._encode_cursor(
        "ing_pending_ab", "nsn1", status="PENDING", final_disposition=None, q="foo"
    )
    pc, nsn = svc._decode_cursor(token, status="PENDING", final_disposition=None, q="foo")
    assert (pc, nsn) == ("ing_pending_ab", "nsn1")


def test_cursor_rejects_filter_mismatch() -> None:
    token = svc._encode_cursor(
        "ing_pending_ab", "nsn1", status="PENDING", final_disposition="MAPPED", q="foo"
    )
    with pytest.raises(ApiError) as exc:
        svc._decode_cursor(token, status="APPROVED", final_disposition="MAPPED", q="foo")
    assert exc.value.code == "INVALID_CURSOR"
    with pytest.raises(ApiError) as exc2:
        svc._decode_cursor(token, status="PENDING", final_disposition="MAPPED", q="bar")
    assert exc2.value.code == "INVALID_CURSOR"
    with pytest.raises(ApiError) as exc3:
        svc._decode_cursor(token, status="PENDING", final_disposition=None, q="foo")
    assert exc3.value.code == "INVALID_CURSOR"


def test_cursor_rejects_malformed_token() -> None:
    with pytest.raises(ApiError) as exc:
        svc._decode_cursor("!!!not-base64!!!", status=None, final_disposition=None, q="")
    assert exc.value.code == "INVALID_CURSOR"


def test_effective_status_derives_pending_when_no_review() -> None:
    assert svc._effective_status(None) == "PENDING"
    assert svc._effective_status("HELD") == "HELD"
    assert svc._effective_status("NEEDS_REVIEW") == "NEEDS_REVIEW"
    assert svc._effective_status("APPROVED") == "APPROVED"


def test_available_actions_by_status() -> None:
    assert svc._ACTIONS_BY_STATUS["PENDING"] == ["APPROVE", "HOLD", "REJECT"]
    assert svc._ACTIONS_BY_STATUS["HELD"] == ["APPROVE", "REJECT"]
    assert svc._ACTIONS_BY_STATUS["NEEDS_REVIEW"] == ["APPROVE", "HOLD", "REJECT"]
    assert svc._ACTIONS_BY_STATUS["APPROVED"] == ["REOPEN"]
    assert svc._ACTIONS_BY_STATUS["REJECTED"] == ["REOPEN"]


def test_suggestion_prefers_alias_when_both_agree() -> None:
    alias = {"nsn": (10, "ing_x", "성분엑스")}
    canonical = {"nsn": (10, "ing_x", "성분엑스")}
    result = svc._build_suggestion("nsn", alias, canonical)
    assert result is not None
    assert result.match_source == "ALIAS_EXACT"
    assert result.target_ingredient_id == 10


def test_suggestion_none_when_alias_and_canonical_conflict() -> None:
    alias = {"nsn": (10, "ing_x", "성분엑스")}
    canonical = {"nsn": (99, "ing_y", "성분와이")}
    assert svc._build_suggestion("nsn", alias, canonical) is None


def test_suggestion_canonical_only() -> None:
    result = svc._build_suggestion("nsn", {}, {"nsn": (7, "ing_c", "카논")})
    assert result is not None
    assert result.match_source == "CANONICAL_NAME_EXACT"


def test_suggestion_none_when_no_candidate() -> None:
    assert svc._build_suggestion("nsn", {}, {}) is None


def test_normalize_status_filter_rejects_unknown() -> None:
    with pytest.raises(ApiError) as exc:
        svc._normalize_status_filter("BOGUS")
    assert exc.value.code == "INVALID_INGREDIENT_MAPPING_STATUS"
    assert svc._normalize_status_filter("pending") == "PENDING"
    assert svc._normalize_status_filter("needs_review") == "NEEDS_REVIEW"
    assert svc._normalize_status_filter(None) is None


def test_normalize_final_disposition_filter_rejects_unknown() -> None:
    assert svc._normalize_final_disposition_filter("mapped") == "MAPPED"
    assert svc._normalize_final_disposition_filter(None) is None
    with pytest.raises(ApiError) as exc:
        svc._normalize_final_disposition_filter("BOGUS")
    assert exc.value.code == "INVALID_INGREDIENT_MAPPING_FINAL_DISPOSITION"


def test_normalize_limit_bounds() -> None:
    assert svc._normalize_limit(50) == 50
    for bad in (0, svc.MAX_LIMIT + 1):
        with pytest.raises(ApiError) as exc:
            svc._normalize_limit(bad)
        assert exc.value.code == "INVALID_LIMIT"


# --- 라우트 인가/검증 (SQL 실행 전에 결정됨) ------------------------------

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


def test_list_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/admin/ingredient-mappings")
    assert response.status_code == 401


def test_list_forbidden_for_non_admin(client: TestClient) -> None:
    _signup(client, USER_EMAIL, "plain-user")
    response = client.get("/api/admin/ingredient-mappings")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_list_rejects_invalid_status_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"status": "BOGUS"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INGREDIENT_MAPPING_STATUS"


def test_list_rejects_invalid_final_disposition_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"final_disposition": "BOGUS"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INGREDIENT_MAPPING_FINAL_DISPOSITION"


def test_list_rejects_invalid_limit_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"limit": 0})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_LIMIT"


def test_detail_requires_normalized_source_name(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    # 필수 쿼리 누락은 전역 RequestValidationError 처리기에 따라 400으로 통일된다.
    response = client.get("/api/admin/ingredient-mappings/ing_pending_x")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"
