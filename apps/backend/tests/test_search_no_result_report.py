from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import RecommendationRun
from app.db.session import make_engine
from app.services.search_no_result_report import (
    build_search_no_result_report,
    format_json_report,
    format_markdown_report,
)


def test_build_search_no_result_report_aggregates_alias_candidates() -> None:
    session = _make_session()
    _add_run(
        session,
        recommendation_code="rec_1",
        concern_text="주름 탄력 추천",
        no_result_reason="no_positive_search_match",
        alias_candidate_terms=["주름", "탄력"],
    )
    _add_run(
        session,
        recommendation_code="rec_2",
        concern_text="주름 크림",
        no_result_reason="parser_unmatched_partial",
        alias_candidate_terms=["주름"],
    )
    _add_run(session, recommendation_code="rec_3", concern_text="보습 크림", diagnostics=None)
    session.commit()

    report = build_search_no_result_report(session, scan_limit=10, top_n=5)

    assert report.scanned_run_count == 3
    assert report.diagnostic_run_count == 2
    assert report.alias_review_run_count == 2
    assert report.reason_counts == {
        "no_positive_search_match": 1,
        "parser_unmatched_partial": 1,
    }
    assert [(summary.term, summary.count) for summary in report.top_alias_candidate_terms] == [
        ("주름", 2),
        ("탄력", 1),
    ]
    assert [entry.recommendation_code for entry in report.entries] == ["rec_2", "rec_1"]


def test_search_no_result_report_formatters_include_summary() -> None:
    session = _make_session()
    _add_run(
        session,
        recommendation_code="rec_alias",
        concern_text="까무잡잡한데 허예지고 싶어",
        no_result_reason="parser_unmatched_only",
        alias_candidate_terms=["까무잡잡한데 허예지고 싶어"],
        unmatched_terms=["까무잡잡한데 허예지고 싶어"],
    )
    session.commit()
    report = build_search_no_result_report(session)

    markdown = format_markdown_report(report)
    json_report = format_json_report(report)

    assert "# 검색 무결과/동의어 후보 리포트" in markdown
    assert "parser_unmatched_only" in markdown
    assert "까무잡잡한데 허예지고 싶어" in markdown
    assert '"recommendation_id": "rec_alias"' in json_report
    assert '"alias_candidate_terms": [' in json_report


def _make_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _add_run(
    session: Session,
    *,
    recommendation_code: str,
    concern_text: str,
    no_result_reason: str = "no_positive_search_match",
    alias_candidate_terms: list[str] | None = None,
    unmatched_terms: list[str] | None = None,
    diagnostics: dict | None = None,
) -> None:
    now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC) + timedelta(
        seconds=int(recommendation_code.rsplit("_", 1)[-1]) if recommendation_code.rsplit("_", 1)[-1].isdigit() else 0
    )
    if diagnostics is None and alias_candidate_terms is not None:
        diagnostics = {
            "version": "search_no_result_v0",
            "no_result_reason": no_result_reason,
            "candidate_count": 2,
            "join_document_count": 2,
            "search_match_count": 2,
            "positive_keyword_match_count": 0,
            "positive_vector_match_count": 0,
            "positive_search_match_count": 0,
            "search_terms": ["주름", "탄력"],
            "unmatched_terms": unmatched_terms or [],
            "matched_terms": [],
            "alias_candidate_terms": alias_candidate_terms,
            "needs_alias_review": True,
        }

    session.add(
        RecommendationRun(
            recommendation_code=recommendation_code,
            concern_text=concern_text,
            skin_type="중성",
            sensitivity="보통",
            avoid_ingredients=[],
            request_context=(
                {"search_no_result_diagnostics": diagnostics}
                if diagnostics is not None
                else {}
            ),
            parser_result={},
            scoring_version="v0",
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
    )
