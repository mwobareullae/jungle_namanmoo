from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import RecommendationRun, SearchCandidate
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.purchase_conditions import parse_purchase_conditions
from app.services.search_candidate_store import save_search_candidates
from app.services.search_matching import SearchMatch
from tests.test_data_loader import EXAMPLES_DIR


def test_save_search_candidates_persists_scores_and_rank_order() -> None:
    session = _seed_example_session()
    run = _create_recommendation_run(session)
    candidates = list_product_candidates(session, parse_purchase_conditions(""))
    matches = [
        SearchMatch(
            product_id=candidates[0].product_id,
            keyword_score=0.25,
            vector_score=0.0,
            search_match_score=0.25,
            matched_terms=("보습",),
        ),
        SearchMatch(
            product_id=candidates[1].product_id,
            keyword_score=0.75,
            vector_score=0.0,
            search_match_score=0.75,
            matched_terms=("진정",),
        ),
    ]

    rows = save_search_candidates(session, run.id, candidates, matches)

    assert [row.rank_order for row in rows] == [1, 2]
    assert [row.product_id for row in rows] == [
        candidates[1].db_product_id,
        candidates[0].db_product_id,
    ]
    assert rows[0].keyword_score == Decimal("0.7500")
    assert rows[0].vector_score == Decimal("0.0000")
    assert rows[0].search_match_score == Decimal("0.7500")


def test_save_search_candidates_replaces_existing_run_candidates() -> None:
    session = _seed_example_session()
    run = _create_recommendation_run(session)
    candidates = list_product_candidates(session, parse_purchase_conditions(""))

    save_search_candidates(
        session,
        run.id,
        candidates,
        [
            _make_match(candidates[0].product_id, 0.1),
            _make_match(candidates[1].product_id, 0.9),
        ],
    )
    save_search_candidates(
        session,
        run.id,
        candidates,
        [
            _make_match(candidates[0].product_id, 1.0),
            _make_match(candidates[1].product_id, 0.0),
        ],
    )

    rows = session.execute(
        select(SearchCandidate)
        .where(SearchCandidate.recommendation_run_id == run.id)
        .order_by(SearchCandidate.rank_order.asc())
    ).scalars().all()

    assert len(rows) == 2
    assert [row.product_id for row in rows] == [
        candidates[0].db_product_id,
        candidates[1].db_product_id,
    ]
    assert [row.search_match_score for row in rows] == [
        Decimal("1.0000"),
        Decimal("0.0000"),
    ]


def test_save_search_candidates_rejects_unknown_match_product_id() -> None:
    session = _seed_example_session()
    run = _create_recommendation_run(session)
    candidates = list_product_candidates(session, parse_purchase_conditions(""))

    with pytest.raises(ValueError, match="Unknown search match product_id"):
        save_search_candidates(
            session,
            run.id,
            candidates,
            [_make_match("unknown_product", 0.5)],
        )


def _make_match(product_id: str, score: float) -> SearchMatch:
    return SearchMatch(
        product_id=product_id,
        keyword_score=score,
        vector_score=0.0,
        search_match_score=score,
        matched_terms=(),
    )


def _create_recommendation_run(session: Session) -> RecommendationRun:
    run = RecommendationRun(
        recommendation_code=f"rec_{datetime.now(UTC).timestamp()}",
        concern_text="보습 추천",
        skin_type="중성",
        sensitivity="보통",
        avoid_ingredients=[],
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(run)
    session.flush()
    return run


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
