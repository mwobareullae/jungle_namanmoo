from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.services.recommendation_pipeline as recommendation_pipeline
import app.services.candidate_pool as candidate_pool_service
from app.db.base import Base
from app.db.models.recommendation import (
    RecommendationResult,
    RecommendationRun,
    RecommendationRunConcern,
    RecommendationRunConstraint,
    RecommendationScoreEvidence,
    SearchCandidate,
)
from app.schemas.recommendation import RecommendationRequest
from app.db.session import make_engine
from app.services.elasticsearch_recommendation_candidates import (
    ElasticsearchRecommendationCandidateResult,
)
from app.services.db_seed import seed_database
from app.services.product_candidates import ProductCandidate
from app.services.recommendation_candidate_cache import (
    CachedCandidateBundle,
    CandidateCacheLookup,
    CandidateCacheWrite,
)
from app.services.recommendation_pipeline import (
    create_recommendation_response,
    create_structured_recommendation_response,
    get_recommendation_response,
)
from app.services.recommendation_intent import (
    StructuredRecommendationIntent,
    build_recommendation_intent,
)
from app.services.recommendation_run_store import (
    cleanup_expired_recommendation_runs,
    save_recommendation_run,
)
from app.services.repository import load_repository
from app.services.search_index_builder import build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_save_recommendation_run_persists_run_context_constraints_and_concerns() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(
        "속건조 보습 세럼 2만원 이하 추천",
        repository=repository,
    )
    now = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)

    timings: dict[str, float] = {}
    saved = save_recommendation_run(
        session,
        intent,
        skin_type="수부지",
        sensitivity="높음",
        avoid_ingredients=["향료"],
        recommendation_code="rec_store_test",
        now=now,
        timings=timings,
    )

    assert saved.run.recommendation_code == "rec_store_test"
    assert saved.run.concern_text == "속건조 보습 세럼 2만원 이하 추천"
    assert saved.run.skin_type == "수부지"
    assert saved.run.sensitivity == "높음"
    assert saved.run.avoid_ingredients == ["향료"]
    assert saved.run.expires_at == now + timedelta(hours=24)
    assert saved.run.scoring_version == "v0"
    assert saved.run.parser_result["concerns"][0]["tag_id"] == "concern_dryness"
    assert saved.run.parser_result["effects"][0]["effect_id"] == "effect_moisturizing"
    assert saved.run.request_context["purchase_conditions"]["categories"][0]["category_code"] == "serum"
    assert saved.run.request_context["purchase_conditions"]["price_max"] == 20000
    assert set(timings) == {
        "run_row_build_ms",
        "run_insert_flush_ms",
        "run_relation_build_ms",
        "run_relation_add_ms",
        "run_relation_flush_ms",
    }
    assert all(value >= 0 for value in timings.values())

    constraints = _load_constraints(session, saved.run.id)
    assert [constraint.constraint_type for constraint in constraints] == ["category", "price_max"]
    assert constraints[0].operator == "eq"
    assert constraints[0].normalized_value == "serum"
    assert constraints[0].category_id is not None
    assert constraints[1].operator == "lte"
    assert constraints[1].numeric_value == Decimal("20000")

    concerns = _load_concerns(session, saved.run.id)
    assert len(concerns) == 1
    assert concerns[0].matched_text == "속건조"
    assert concerns[0].confidence == Decimal("1.0000")


def test_save_recommendation_run_persists_category_and_default_inputs() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(
        "라운드랩 건조 크림 추천",
        repository=repository,
    )

    saved = save_recommendation_run(
        session,
        intent,
        skin_type="",
        sensitivity=None,
        avoid_ingredients=[" ", "알코올", ""],
        recommendation_code="rec_store_defaults",
        now=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
    )

    assert saved.run.skin_type == "중성"
    assert saved.run.sensitivity == "보통"
    assert saved.run.avoid_ingredients == ["알코올"]

    constraints = _load_constraints(session, saved.run.id)
    assert [constraint.constraint_type for constraint in constraints] == ["category"]
    assert constraints[0].category_id is not None
    assert constraints[0].normalized_value == "cream"


def test_cleanup_expired_recommendation_runs_deletes_run_and_children() -> None:
    session = _seed_example_session()
    now = datetime(2026, 6, 29, 4, 0, 0, tzinfo=UTC)
    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="?띻굔議?蹂댁뒿 異붿쿇"),
        commit=False,
    )
    run = _load_run(session, response.recommendation_id)
    persisted_result = session.execute(
        select(RecommendationResult)
        .where(RecommendationResult.recommendation_run_id == run.id)
        .order_by(RecommendationResult.rank_order.asc())
        .limit(1)
    ).scalar_one()
    session.add(
        SearchCandidate(
            recommendation_run_id=run.id,
            product_id=persisted_result.product_id,
            keyword_score=Decimal("0.1000"),
            vector_score=Decimal("0.2000"),
            search_match_score=Decimal("0.3000"),
            rank_order=1,
        )
    )
    run.expires_at = now - timedelta(seconds=1)
    session.flush()

    dry_run = cleanup_expired_recommendation_runs(session, now=now, dry_run=True)

    assert dry_run.dry_run is True
    assert dry_run.recommendation_runs == 1
    assert dry_run.search_candidates == 1
    assert dry_run.recommendation_results > 0
    assert _count_rows(session, RecommendationRun) == 1

    result = cleanup_expired_recommendation_runs(session, now=now)

    assert result.dry_run is False
    assert result.recommendation_runs == 1
    assert _count_rows(session, RecommendationScoreEvidence) == 0
    assert _count_rows(session, RecommendationResult) == 0
    assert _count_rows(session, SearchCandidate) == 0
    assert _count_rows(session, RecommendationRunConstraint) == 0
    assert _count_rows(session, RecommendationRunConcern) == 0
    assert _count_rows(session, RecommendationRun) == 0


def test_create_recommendation_response_skips_candidate_trace_persistence() -> None:
    session = _seed_example_session()

    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="속건조 보습 추천"),
        result_limit=10,
        candidate_pool_limit=20,
        commit=False,
    )

    assert response.products
    assert _count_rows(session, SearchCandidate) == 0
    assert _count_rows(session, RecommendationResult) == len(response.products)


def test_create_recommendation_response_uses_compact_fresh_response_path(
    monkeypatch,
) -> None:
    session = _seed_example_session()
    get_response = recommendation_pipeline.get_recommendation_response
    events: list[dict] = []

    def _unexpected_result_reload(*args, **kwargs):
        raise AssertionError("fresh recommendation response must not reload persisted results")

    def _record_event(_event_name: str, *, duration_ms: float, metadata: dict) -> None:
        events.append({"duration_ms": duration_ms, "metadata": metadata})

    monkeypatch.setattr(
        recommendation_pipeline,
        "get_recommendation_response",
        _unexpected_result_reload,
    )
    monkeypatch.setattr(recommendation_pipeline, "log_performance_event", _record_event)

    created = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="hydration recommendation"),
        result_limit=2,
        candidate_pool_limit=20,
        page=2,
        page_size=1,
        commit=False,
    )

    assert created.products
    assert created.pagination.page == 2
    assert created.pagination.total_items == 2
    completed = events[-1]["metadata"]
    assert completed["response_read_path"] == "fresh_compact"
    assert completed["response_run_load_ms"] == 0.0
    assert completed["response_result_count_ms"] == 0.0
    assert completed["response_thumbnail_load_ms"] == 0.0
    assert completed["response_evidence_load_ms"] == 0.0
    assert completed["response_display_query_ms"] >= 0.0

    monkeypatch.setattr(
        recommendation_pipeline,
        "get_recommendation_response",
        get_response,
    )
    loaded = get_recommendation_response(
        session,
        created.recommendation_id,
        page=2,
        page_size=1,
    )

    assert created.model_dump(mode="json") == loaded.model_dump(mode="json")


def test_get_recommendation_response_records_response_load_diagnostics() -> None:
    session = _seed_example_session()
    created = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="hydration recommendation"),
        result_limit=10,
        candidate_pool_limit=20,
        commit=False,
    )

    timings: dict[str, float] = {}
    response = get_recommendation_response(
        session,
        created.recommendation_id,
        timings=timings,
    )

    expected_keys = {
        "response_load_ms",
        "response_run_load_ms",
        "response_result_count_ms",
        "response_product_query_ms",
        "response_thumbnail_load_ms",
        "response_availability_build_ms",
        "response_result_rows_ms",
        "response_evidence_query_ms",
        "response_evidence_group_ms",
        "response_evidence_load_ms",
        "response_serialize_ms",
        "response_unattributed_ms",
        "response_page_size",
        "response_total_item_count",
        "response_result_row_count",
        "response_thumbnail_count",
        "response_evidence_row_count",
    }

    assert response.products
    assert expected_keys <= timings.keys()
    assert timings["response_page_size"] == response.pagination.page_size
    assert timings["response_total_item_count"] == response.pagination.total_items
    assert timings["response_result_row_count"] == len(response.products)
    assert all(value >= 0 for value in timings.values())


def test_create_recommendation_response_persists_candidate_pool_diagnostics() -> None:
    session = _seed_example_session()

    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="속건조 보습 추천"),
        result_limit=10,
        candidate_pool_limit=20,
        commit=False,
    )

    run = _load_run(session, response.recommendation_id)
    diagnostics = run.request_context["candidate_pool_diagnostics"]
    search_diagnostics = run.request_context["search_no_result_diagnostics"]

    assert diagnostics["candidate_generation_version"] == "candidate_pool_catalog_es_v2"
    assert diagnostics["strategy"] == "catalog_es_candidate_pool"
    assert diagnostics["requested_candidate_pool_limit"] == 20
    assert diagnostics["result_limit"] == 10
    assert diagnostics["loaded_candidate_count"] == 2
    assert diagnostics["avoid_filtered_count"] == 0
    assert diagnostics["after_avoid_filter_count"] == 2
    assert diagnostics["merged_count"] == 2
    assert diagnostics["deduped_count"] == 2
    assert diagnostics["join_document_count"] == 2
    assert diagnostics["search_match_count"] == 2
    assert diagnostics["scored_candidate_count"] == 2
    assert diagnostics["final_result_count"] == 2
    assert diagnostics["source_counts"] == {
        "catalog_es_recommendation": 0,
        "db_popularity_fallback": 2,
    }
    es_diagnostic, fallback_diagnostic = diagnostics["source_diagnostics"]
    assert es_diagnostic["source"] == "catalog_es_recommendation"
    assert es_diagnostic["returned_count"] == 0
    assert es_diagnostic["failure_reason"] == "catalog Elasticsearch skipped for sqlite"
    assert fallback_diagnostic["source"] == "db_popularity_fallback"
    assert fallback_diagnostic["returned_count"] == 2
    assert fallback_diagnostic["after_dedupe_count"] == 2
    assert diagnostics["fallback_used"] is True
    assert diagnostics["fallback_reason"] == "catalog Elasticsearch skipped for sqlite"
    assert diagnostics["fallback_count"] == 2
    assert diagnostics["hard_filter_total_count"] is None
    assert search_diagnostics["version"] == "search_no_result_v0"
    assert search_diagnostics["no_result_reason"] is None
    assert search_diagnostics["candidate_count"] == 2
    assert search_diagnostics["join_document_count"] == 2
    assert search_diagnostics["positive_search_match_count"] > 0
    assert search_diagnostics["needs_alias_review"] is False


def test_candidate_cache_hit_preserves_final_product_rank_and_score(monkeypatch) -> None:
    first_session = _seed_example_session()
    second_session = _seed_example_session()
    cache = _PipelineCandidateCache()
    es_call_count = 0

    def fake_elasticsearch_search(*args, **kwargs) -> ElasticsearchRecommendationCandidateResult:
        nonlocal es_call_count
        es_call_count += 1
        candidates = (_pipeline_candidate(2), _pipeline_candidate(1))
        return ElasticsearchRecommendationCandidateResult(
            candidates=candidates,
            raw_hit_count=len(candidates),
            direct_match_count=len(candidates),
            popularity_fill_count=0,
            pre_dedupe_count=len(candidates),
            deduped_count=len(candidates),
            attempted=True,
            index_alias="test_catalog_current",
            query_text="hydration recommendation",
            duration_ms=1,
            total_hit_count=len(candidates),
        )

    def cached_candidate_pool(session, intent, **kwargs):
        return candidate_pool_service.generate_candidate_pool(
            session,
            intent,
            **kwargs,
            enable_elasticsearch=True,
            elasticsearch_search=fake_elasticsearch_search,
            candidate_cache=cache,
        )

    monkeypatch.setattr(
        recommendation_pipeline,
        "generate_candidate_pool",
        cached_candidate_pool,
    )
    request = RecommendationRequest(concern_text="hydration recommendation")

    structured_intent = StructuredRecommendationIntent()
    first = create_structured_recommendation_response(
        first_session,
        request,
        structured_intent=structured_intent,
        result_limit=2,
        candidate_pool_limit=20,
        commit=False,
    )
    second = create_structured_recommendation_response(
        second_session,
        request,
        structured_intent=structured_intent,
        result_limit=2,
        candidate_pool_limit=20,
        commit=False,
    )

    assert es_call_count == 1
    assert [
        (product.product_id, product.rank, product.total_score)
        for product in first.products
    ] == [
        (product.product_id, product.rank, product.total_score)
        for product in second.products
    ]
    cached_run = _load_run(second_session, second.recommendation_id)
    assert cached_run.request_context["candidate_pool_diagnostics"]["candidate_cache_hit"] is True
    assert cached_run.request_context["candidate_pool_diagnostics"]["candidate_es_bypassed"] is True


def test_create_recommendation_response_persists_no_result_diagnostics() -> None:
    session = _seed_example_session()

    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="주름 탄력 추천"),
        result_limit=10,
        candidate_pool_limit=20,
        commit=False,
    )

    run = _load_run(session, response.recommendation_id)
    diagnostics = run.request_context["search_no_result_diagnostics"]

    assert diagnostics["version"] == "search_no_result_v0"
    assert diagnostics["no_result_reason"] == "no_positive_search_match"
    assert diagnostics["candidate_count"] == 2
    assert diagnostics["join_document_count"] == 2
    assert diagnostics["positive_search_match_count"] == 0
    assert diagnostics["alias_candidate_terms"]
    assert diagnostics["needs_alias_review"] is True


class _PipelineCandidateCache:
    def __init__(self) -> None:
        self.bundle: CachedCandidateBundle | None = None

    def read(self, *args, **kwargs) -> CandidateCacheLookup:
        return CandidateCacheLookup(
            bundle=self.bundle,
            lookup_ms=0.1,
            ttl_seconds=300,
            cache_enabled=True,
        )

    def write(self, *args, bundle: CachedCandidateBundle, **kwargs) -> CandidateCacheWrite:
        self.bundle = bundle
        return CandidateCacheWrite(write_ms=0.1, ttl_seconds=300)


def _pipeline_candidate(product_db_id: int) -> ProductCandidate:
    return ProductCandidate(
        db_product_id=product_db_id,
        product_id=f"prod_{product_db_id:03d}",
        brand_code="test_brand",
        brand="Test Brand",
        category_code="serum",
        name=f"Test Product {product_db_id}",
        thumbnail_url=None,
        lowest_price=10_000 + product_db_id,
    )


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session


def _load_run(session: Session, recommendation_code: str) -> RecommendationRun:
    return session.execute(
        select(RecommendationRun).where(
            RecommendationRun.recommendation_code == recommendation_code,
        )
    ).scalar_one()


def _count_rows(
    session: Session,
    model: type[
        RecommendationRun
        | RecommendationRunConstraint
        | RecommendationRunConcern
        | SearchCandidate
        | RecommendationResult
        | RecommendationScoreEvidence
    ],
) -> int:
    return len(session.execute(select(model.id)).scalars().all())


def _load_constraints(
    session: Session,
    recommendation_run_id: int,
) -> list[RecommendationRunConstraint]:
    return list(
        session.execute(
            select(RecommendationRunConstraint)
            .where(RecommendationRunConstraint.recommendation_run_id == recommendation_run_id)
            .order_by(RecommendationRunConstraint.id.asc())
        ).scalars()
    )


def _load_concerns(
    session: Session,
    recommendation_run_id: int,
) -> list[RecommendationRunConcern]:
    return list(
        session.execute(
            select(RecommendationRunConcern)
            .where(RecommendationRunConcern.recommendation_run_id == recommendation_run_id)
            .order_by(RecommendationRunConcern.id.asc())
        ).scalars()
    )
