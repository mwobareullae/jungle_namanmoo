"""P1-M2-A Chunk 3 관리자 성분 매핑 검수 조회 focused 테스트.

목록·상세의 그룹 집계 SQL은 PostgreSQL 전용(`regexp_replace(...,'g')`,
`distinct on`, `filter (where)`, 행 비교, `ilike`)이라 SQLite 픽스처에서 실행할 수
없다. 그 SQL 정합성(그룹핑·review JOIN·페이지네이션·suggestion 매칭)은 실
PostgreSQL로 수동 검증했다. 여기서는 SQL 실행 전에 결정되는 순수 로직과
인가/검증 계약만 자동 검증한다:
  - 정규화(`normalize_source_name`)
  - suggestion 병합 규칙(alias 우선, 충돌 시 None, 없으면 None)
  - status/page_size 검증 400, 라우트 401/403.
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


def test_candidate_types_are_read_only_exact_match_categories() -> None:
    assert svc._build_candidate("nsn", {}, {}, set()).candidate_type == "NO_EXACT_MATCH"
    assert (
        svc._build_candidate("nsn", {}, {"nsn": (7, "ing_c", "canonical")}, set()).candidate_type
        == "CANONICAL_EXACT_MATCH"
    )
    assert (
        svc._build_candidate("nsn", {"nsn": (7, "ing_c", "canonical")}, {}, set()).candidate_type
        == "ALIAS_EXACT_MATCH"
    )
    assert (
        svc._build_candidate(
            "nsn",
            {"nsn": (7, "ing_c", "canonical")},
            {"nsn": (9, "ing_other", "other")},
            set(),
        ).candidate_type
        == "EXACT_MATCH_CONFLICT"
    )
    assert (
        svc._build_candidate("nsn", {}, {}, {"nsn"}).candidate_type == "EXACT_MATCH_CONFLICT"
    )


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


def test_normalize_page_size_bounds() -> None:
    assert svc._normalize_page_size(50) == 50
    for bad in (0, svc.MAX_PAGE_SIZE + 1):
        with pytest.raises(ApiError) as exc:
            svc._normalize_page_size(bad)
        assert exc.value.code == "INVALID_PAGE_SIZE"


def test_normalize_sort_rejects_unknown() -> None:
    assert svc._normalize_sort(None) == "CODE_ASC"
    assert svc._normalize_sort("") == "CODE_ASC"
    assert svc._normalize_sort("connection_desc") == "CONNECTION_DESC"
    with pytest.raises(ApiError) as exc:
        svc._normalize_sort("BOGUS")
    assert exc.value.code == "INVALID_INGREDIENT_MAPPING_SORT"


def test_normalize_candidate_type_rejects_unknown() -> None:
    assert svc._normalize_candidate_type(None) is None
    assert svc._normalize_candidate_type("") is None
    assert svc._normalize_candidate_type("alias_exact_match") == "ALIAS_EXACT_MATCH"
    with pytest.raises(ApiError) as exc:
        svc._normalize_candidate_type("SOURCE_ERROR")
    assert exc.value.code == "INVALID_INGREDIENT_MAPPING_CANDIDATE"


def test_alias_exact_match_uses_targeted_list_query() -> None:
    assert svc._list_sql_for_candidate_type("ALIAS_EXACT_MATCH") is svc._LIST_ALIAS_EXACT_MATCH_SQL
    assert svc._list_sql_for_candidate_type("CANONICAL_EXACT_MATCH") is svc._LIST_CANDIDATE_SQL
    assert svc._list_sql_for_candidate_type(None) is svc._LIST_SQL


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


def test_list_rejects_invalid_sort_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"sort": "BOGUS"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INGREDIENT_MAPPING_SORT"


def test_list_rejects_invalid_candidate_type_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"candidate_type": "SOURCE_ERROR"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INGREDIENT_MAPPING_CANDIDATE"


def test_list_rejects_invalid_page_size_before_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    response = client.get("/api/admin/ingredient-mappings", params={"page_size": 0})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PAGE_SIZE"


def test_detail_requires_normalized_source_name(client: TestClient, db_engine: Engine) -> None:
    _signup(client, ADMIN_EMAIL, "admin-mapping")
    _promote_admin(db_engine, ADMIN_EMAIL)
    # 필수 쿼리 누락은 전역 RequestValidationError 처리기에 따라 400으로 통일된다.
    response = client.get("/api/admin/ingredient-mappings/ing_pending_x")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"
