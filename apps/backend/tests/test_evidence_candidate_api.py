from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.taxonomy import (
    EvidenceDiscoveryCandidate,
    EvidenceDiscoveryReview,
    IngredientEvidence,
)
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session, EXAMPLES_DIR)
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    monkeypatch.setattr(settings, "evidence_ingest_token", "test-ingest-token")
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_import_is_idempotent_and_does_not_create_runtime_evidence(
    client: TestClient,
    db_engine: Engine,
) -> None:
    payload = {"candidates": [_candidate("91000001")]}

    unauthorized = client.post("/api/internal/evidence-candidates/import", json=payload)
    first = client.post(
        "/api/internal/evidence-candidates/import",
        headers={"X-Evidence-Ingest-Token": "test-ingest-token"},
        json=payload,
    )
    second = client.post(
        "/api/internal/evidence-candidates/import",
        headers={"X-Evidence-Ingest-Token": "test-ingest-token"},
        json=payload,
    )

    assert unauthorized.status_code == 401
    assert first.status_code == 200
    assert first.json() == {"received": 1, "inserted": 1, "refreshed": 0}
    assert second.status_code == 200
    assert second.json() == {"received": 1, "inserted": 0, "refreshed": 1}
    with Session(db_engine) as session:
        candidates = session.execute(select(EvidenceDiscoveryCandidate)).scalars().all()
        promoted = session.execute(
            select(IngredientEvidence).where(IngredientEvidence.pmid == "91000001")
        ).scalars().all()
    assert len(candidates) == 1
    assert candidates[0].review_status == "candidate_unverified"
    assert promoted == []


def test_admin_can_approve_candidate_and_promote_it_once(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _import(client, _candidate("91000002"))
    _signup_admin(client, db_engine)

    listed = client.get("/api/admin/evidence-candidates?status=candidate_unverified")
    assert listed.status_code == 200
    candidate_id = listed.json()["items"][0]["id"]
    approved = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/approve",
        json={
            "summary": "인체 국소 시험에서 진정 지표가 개선됨",
            "evidence_level": "high",
            "evidence_score": 82,
            "result_direction": "positive",
            "score_use_level": "primary",
            "source_authority_score": 0.9,
            "is_representative": False,
            "representative_rank": None,
            "review_note": "원문과 성분 형태를 확인함",
        },
    )
    repeated = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/approve",
        json={
            "summary": "중복 승인",
            "evidence_level": "high",
            "evidence_score": 82,
            "result_direction": "positive",
            "score_use_level": "primary",
            "review_note": "중복",
        },
    )

    assert approved.status_code == 200
    evidence_id = approved.json()["promoted_evidence_id"]
    assert evidence_id is not None
    assert approved.json()["candidate"]["review_status"] == "accepted"
    assert any(
        item["id"] == evidence_id for item in approved.json()["candidate"]["current_evidence"]
    )
    assert len(approved.json()["candidate"]["history"]) == 1
    assert repeated.status_code == 409
    with Session(db_engine) as session:
        evidence = session.get(IngredientEvidence, evidence_id)
        reviews = session.execute(select(EvidenceDiscoveryReview)).scalars().all()
    assert evidence is not None
    assert evidence.review_status == "accepted"
    assert evidence.pmid == "91000002"
    assert float(evidence.evidence_score) == 82
    assert len(reviews) == 1


def test_admin_can_reject_without_promoting_candidate(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _import(client, _candidate("91000003"))
    _signup_admin(client, db_engine, email="reviewer2@example.com", nickname="reviewer2")
    candidate_id = client.get("/api/admin/evidence-candidates").json()["items"][0]["id"]

    response = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/reject",
        json={"review_note": "복합 제형이라 단일 성분 효과를 분리할 수 없음"},
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["review_status"] == "rejected"
    assert response.json()["promoted_evidence_id"] is None
    with Session(db_engine) as session:
        evidence = session.execute(
            select(IngredientEvidence).where(IngredientEvidence.pmid == "91000003")
        ).scalars().all()
    assert evidence == []


def test_weekly_reimport_preserves_rejected_decision(
    client: TestClient,
    db_engine: Engine,
) -> None:
    candidate = _candidate("91000006")
    _import(client, candidate)
    _signup_admin(client, db_engine, email="reviewer5@example.com", nickname="reviewer5")
    candidate_id = client.get("/api/admin/evidence-candidates").json()["items"][0]["id"]
    rejected = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/reject",
        json={"review_note": "범위 불일치"},
    )
    assert rejected.status_code == 200

    _import(client, {**candidate, "title": "Updated PubMed title"})

    with Session(db_engine) as session:
        stored = session.get(EvidenceDiscoveryCandidate, candidate_id)
    assert stored is not None
    assert stored.review_status == "rejected"
    assert stored.title == "Updated PubMed title"


def test_non_admin_cannot_read_candidate_inbox(client: TestClient) -> None:
    _signup(client, email="user@example.com", nickname="user")
    response = client.get("/api/admin/evidence-candidates")
    assert response.status_code == 403


def test_non_positive_approval_cannot_increase_score(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _import(client, _candidate("91000004"))
    _signup_admin(client, db_engine, email="reviewer3@example.com", nickname="reviewer3")
    candidate_id = client.get("/api/admin/evidence-candidates").json()["items"][0]["id"]

    response = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/approve",
        json={
            "summary": "유의한 차이가 없음",
            "evidence_level": "medium",
            "evidence_score": 60,
            "result_direction": "null",
            "score_use_level": "supporting",
            "review_note": "무효 결과를 보존함",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NON_POSITIVE_EVIDENCE_CANNOT_SCORE"


def test_reference_only_approval_cannot_increase_score(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _import(client, _candidate("91000005"))
    _signup_admin(client, db_engine, email="reviewer4@example.com", nickname="reviewer4")
    candidate_id = client.get("/api/admin/evidence-candidates").json()["items"][0]["id"]

    response = client.post(
        f"/api/admin/evidence-candidates/{candidate_id}/approve",
        json={
            "summary": "참고용 연구",
            "evidence_level": "low",
            "evidence_score": 30,
            "result_direction": "positive",
            "score_use_level": "reference_only",
            "review_note": "직접성 부족으로 참고만 사용",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REFERENCE_ONLY_EVIDENCE_CANNOT_SCORE"


def test_approval_commit_failure_rolls_back_candidate_evidence_and_history(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pmid = "91000007"
    _import(client, _candidate(pmid))
    _signup_admin(client, db_engine, email="rollback-reviewer@example.com", nickname="rollback-reviewer")
    candidate_id = client.get("/api/admin/evidence-candidates").json()["items"][0]["id"]

    def fail_commit(_: Session) -> None:
        raise RuntimeError("simulated commit failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            client.post(
                f"/api/admin/evidence-candidates/{candidate_id}/approve",
                json={
                    "summary": "커밋 실패 롤백 확인",
                    "evidence_level": "high",
                    "evidence_score": 82,
                    "result_direction": "positive",
                    "score_use_level": "primary",
                    "review_note": "테스트",
                },
            )

    with Session(db_engine) as session:
        candidate = session.get(EvidenceDiscoveryCandidate, candidate_id)
        evidence = session.execute(
            select(IngredientEvidence).where(IngredientEvidence.pmid == pmid)
        ).scalars().all()
        reviews = session.execute(
            select(EvidenceDiscoveryReview).where(EvidenceDiscoveryReview.candidate_id == candidate_id)
        ).scalars().all()

    assert candidate is not None
    assert candidate.review_status == "candidate_unverified"
    assert candidate.promoted_evidence_id is None
    assert evidence == []
    assert reviews == []


def _candidate(pmid: str) -> dict:
    return {
        "discovery_key": f"PMID:{pmid}:ing_panthenol:effect_calming",
        "ingredient_id": "ing_panthenol",
        "effect_id": "effect_calming",
        "effect_name": "진정",
        "pmid": pmid,
        "doi": f"10.1000/{pmid}",
        "title": f"Panthenol calming study {pmid}",
        "journal": "Journal of Skin Tests",
        "publication_date": "2026 Jul-Aug",
        "publication_types": "Clinical Trial",
        "authors": "Test Author",
        "abstract_available": True,
        "abstract_excerpt": "Topical panthenol was evaluated in human skin.",
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "discovery_scope": "new_paper",
        "review_status": "candidate_unverified",
        "score_eligible": False,
        "search_window_start": "2026-07-03",
        "search_window_end": "2026-07-11",
        "search_query": '"panthenol" AND "calming"',
    }


def _import(client: TestClient, candidate: dict) -> None:
    response = client.post(
        "/api/internal/evidence-candidates/import",
        headers={"X-Evidence-Ingest-Token": "test-ingest-token"},
        json={"candidates": [candidate]},
    )
    assert response.status_code == 200, response.text


def _signup(client: TestClient, *, email: str, nickname: str) -> None:
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


def _signup_admin(
    client: TestClient,
    db_engine: Engine,
    *,
    email: str = "reviewer@example.com",
    nickname: str = "reviewer",
) -> None:
    _signup(client, email=email, nickname=nickname)
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        user.role = "ADMIN"
        session.commit()
