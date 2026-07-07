from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.skin import BaumannTypeProfile, SkinProfile, SkinTestAnswer, SkinTestResult
from app.db.session import get_db
from app.main import app


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


def test_skin_test_questions_returns_final_8q_contract(client: TestClient) -> None:
    response = client.get("/api/skin-test/questions")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "baumann_8q_v1"
    assert len(data["questions"]) == 8
    assert data["questions"][0]["text"] == "세안 후 아무것도 바르지 않고 몇 시간 지난 오후, 내 피부는?"
    assert [option["text"] for option in data["questions"][0]["options"]] == [
        "얼굴 전체가 번들거려 기름종이나 파우더가 필요하다.",
        "T존은 번들거리지만 볼은 적당하거나 살짝 건조하다.",
        "크게 당기진 않지만 만지면 살짝 까끌하고 푸석하다.",
        "속당김이 심하고 각질이 일어나며 갈라지는 느낌이다.",
    ]
    assert "axis" not in data["questions"][0]
    assert "internal_label" not in data["questions"][0]["options"][0]


def test_manual_skin_profile_accepts_frontend_signup_contract(client: TestClient) -> None:
    signup_data = _signup(client, email="skin-profile@example.com", nickname="피부프로필")

    response = client.post(
        "/api/skin-profile",
        headers=_auth_headers(signup_data),
        json={
            "skinType": "dehydrated_oily",
            "sensitivity": "normal",
            "concerns": ["concern_dry_barrier", "concern_pore"],
            "avoidIngredients": ["fragrance", "fragrance", "alcohol"],
        },
    )

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["skin_type"] == "수부지"
    assert profile["sensitivity"] == "보통"
    assert profile["skin_type_source"] == "manual"
    assert profile["sensitivity_source"] == "manual"
    assert profile["explicit_skin_type"] == "수부지"
    assert profile["explicit_sensitivity"] == "보통"
    assert profile["avoid_ingredients"] == ["fragrance", "alcohol"]
    assert profile["concerns"] == ["concern_dry_barrier", "concern_pore"]

    get_response = client.get("/api/me/skin-profile", headers=_auth_headers(signup_data))
    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["has_profile"] is True
    assert get_body["profile"]["concerns"] == ["concern_dry_barrier", "concern_pore"]


def test_skin_test_submit_stores_result_and_returns_frontend_result(
    client: TestClient,
    db_engine: Engine,
) -> None:
    question_set = _question_set(client)
    answers = _answers_for_type(question_set["questions"], od="O", sr="S", pn="P", wt="W")

    response = client.post(
        "/api/skin-test/submit",
        json={"version": question_set["version"], "answers": answers},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_id"] > 0
    assert data["type_code"] == "OSPW"
    assert data["skin_type"] == "oily"
    assert data["sensitivity"] == "high"
    assert data["title"] == "진정과 미백이 동시에 필요한 타입"
    assert data["subtitle"] == "겉과 속 모두 섬세하게 신경 써줘야 하는 타입"
    assert data["recommended_effects"] == ["저자극", "미백", "안티에이징"]
    assert data["concern_tags"] == ["트러블", "색소침착", "잔주름"]
    assert data["image_storage_key"] == "skin-types/OSPW/OSPW.png"

    with Session(db_engine) as session:
        result = session.execute(select(SkinTestResult)).scalar_one()
        stored_answers = session.execute(select(SkinTestAnswer)).scalars().all()
        type_profile = session.execute(
            select(BaumannTypeProfile).where(BaumannTypeProfile.type_code == "OSPW")
        ).scalar_one()

    assert result.type_code == "OSPW"
    assert result.axis_scores["OD"]["winner"] == "O"
    assert result.commerce_profile["category_preference"]["code"] == "toner_pad"
    assert len(stored_answers) == 8
    assert type_profile.object_name == "딸기"


def test_skin_test_submit_with_auth_applies_result_to_profile(
    client: TestClient,
    db_engine: Engine,
) -> None:
    signup_data = _signup(client, email="auto-apply-skin-test@example.com", nickname="auto-apply")
    headers = _auth_headers(signup_data)
    question_set = _question_set(client)

    response = client.post(
        "/api/skin-test/submit",
        headers=headers,
        json={
            "version": question_set["version"],
            "answers": _answers_for_type(question_set["questions"], od="O", sr="S", pn="N", wt="T"),
        },
    )

    assert response.status_code == 200
    result_data = response.json()

    profile_response = client.get("/api/me/skin-profile", headers=headers)
    assert profile_response.status_code == 200
    profile = profile_response.json()["profile"]
    assert profile["latest_skin_test_result_id"] == result_data["result_id"]
    assert profile["baumann_type_code"] == result_data["type_code"]
    assert profile["baumann_signal_weight"] == 0.25
    assert profile["source"] == "skin_test"

    with Session(db_engine) as session:
        stored_profile = session.execute(select(SkinProfile)).scalar_one()
        result = session.execute(select(SkinTestResult)).scalar_one()

    assert result.user_id == signup_data["user"]["id"]
    assert result.applied_profile_id == stored_profile.id
    assert stored_profile.latest_skin_test_result_id == result.id


def test_skin_test_result_can_be_loaded_by_result_id(client: TestClient) -> None:
    question_set = _question_set(client)
    submit_response = client.post(
        "/api/skin-test/submit",
        json={
            "version": question_set["version"],
            "answers": _answers_for_type(question_set["questions"], od="D", sr="R", pn="P", wt="W"),
        },
    )
    result_id = submit_response.json()["result_id"]

    response = client.get(f"/api/skin-test/results/{result_id}")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["result_id"] == result_id
    assert result["type_code"] == "DRPW"
    assert result["title"] == "속부터 채우는 게 답인 타입"


def test_skin_test_rejects_option_from_other_question(client: TestClient) -> None:
    question_set = _question_set(client)
    questions = question_set["questions"]
    answers = _answers_for_type(questions, od="O", sr="S", pn="P", wt="W")
    answers[0]["option_id"] = questions[1]["options"][0]["id"]

    response = client.post(
        "/api/skin-test/submit",
        json={"version": question_set["version"], "answers": answers},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "OPTION_NOT_IN_QUESTION"


def test_apply_skin_test_does_not_override_manual_profile(
    client: TestClient,
    db_engine: Engine,
) -> None:
    signup_data = _signup(client, email="mixed-profile@example.com", nickname="혼합프로필")
    headers = _auth_headers(signup_data)
    client.put(
        "/api/me/skin-profile",
        headers=headers,
        json={"skin_type": "복합성", "sensitivity": "보통", "avoid_ingredients": []},
    )
    question_set = _question_set(client)
    submit_response = client.post(
        "/api/skin-test/submit",
        headers=headers,
        json={
            "version": question_set["version"],
            "answers": _answers_for_type(question_set["questions"], od="D", sr="S", pn="P", wt="W"),
        },
    )

    response = client.post(
        "/api/skin-test/apply-to-profile",
        headers=headers,
        json={"result_id": submit_response.json()["result_id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    profile = body["skin_profile"]
    assert profile["skin_type"] == "복합성"
    assert profile["sensitivity"] == "보통"
    assert profile["baumann_type_code"] == "DSPW"
    assert profile["baumann_inferred_skin_type"] == "건성"
    assert profile["baumann_inferred_sensitivity"] == "민감"
    assert profile["baumann_signal_weight"] == 0.25
    assert profile["source"] == "mixed"

    with Session(db_engine) as session:
        stored_profile = session.execute(select(SkinProfile)).scalar_one()
        result = session.execute(select(SkinTestResult)).scalar_one()

    assert stored_profile.latest_skin_test_result_id == result.id
    assert result.applied_profile_id == stored_profile.id


def test_apply_skin_test_creates_profile_when_manual_profile_is_missing(client: TestClient) -> None:
    signup_data = _signup(client, email="skin-test-only@example.com", nickname="테스트프로필")
    headers = _auth_headers(signup_data)
    question_set = _question_set(client)
    submit_response = client.post(
        "/api/skin-test/submit",
        headers=headers,
        json={
            "version": question_set["version"],
            "answers": _answers_for_type(question_set["questions"], od="O", sr="S", pn="N", wt="T"),
        },
    )

    response = client.post(
        "/api/skin-test/apply-to-profile",
        headers=headers,
        json={"result_id": submit_response.json()["result_id"]},
    )

    assert response.status_code == 200
    profile = response.json()["skin_profile"]
    assert profile["skin_type"] == "지성"
    assert profile["sensitivity"] == "민감"
    assert profile["skin_type_source"] == "skin_test"
    assert profile["sensitivity_source"] == "skin_test"
    assert profile["source"] == "skin_test"


def _signup(client: TestClient, *, email: str, nickname: str) -> dict:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200
    return response.json()


def _auth_headers(signup_data: dict) -> dict[str, str]:
    return {}


def _question_set(client: TestClient) -> dict:
    response = client.get("/api/skin-test/questions")
    assert response.status_code == 200
    return response.json()


def _answers_for_type(
    questions: list[dict],
    *,
    od: str,
    sr: str,
    pn: str,
    wt: str,
) -> list[dict[str, int]]:
    choice_by_sequence = {
        1: 0 if od == "O" else 3,
        2: 0 if sr == "S" else 3,
        3: 0,
        4: 0 if pn == "P" else 3,
        5: 0,
        6: 0 if wt == "W" else 3,
        7: 0,
        8: 0,
    }
    answers: list[dict[str, int]] = []
    for index, question in enumerate(questions, start=1):
        option_index = choice_by_sequence[index]
        option = question["options"][option_index]
        answers.append({"question_id": question["id"], "option_id": option["id"]})
    return answers
