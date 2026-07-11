from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.catalog_search_query import parse_catalog_search_query
from app.services.catalog_search_recovery import build_catalog_search_recovery_plan
from app.services.catalog_search_text import hangul_to_english_keys
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


def test_recovery_plan_uses_known_correction_without_replacing_original() -> None:
    session = _seed_example_session()
    parsed = parse_catalog_search_query(session, query="히알루론싼 세럼")

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert plan.corrected_query == "히알루론산 세럼"
    assert plan.confident_correction is True
    assert plan.variants[0] == "히알루론산 세럼"
    assert parsed.original_query == "히알루론싼 세럼"
    assert plan.fuzzy_enabled is False


def test_recovery_plan_allows_keyboard_conversion_only_for_dictionary_term() -> None:
    session = _seed_example_session()
    mistyped = hangul_to_english_keys("라운드랩")
    parsed = parse_catalog_search_query(session, query=mistyped)

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert plan.keyboard_conversion_used is True
    assert plan.corrected_query == "라운드랩"
    assert "라운드랩" in plan.variants


def test_recovery_plan_disables_fuzzy_for_one_or_two_characters() -> None:
    session = _seed_example_session()
    parsed = parse_catalog_search_query(session, query="수분")

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert plan.fuzzy_enabled is False


def test_recovery_plan_uses_chosung_without_fuzzy_variants() -> None:
    session = _seed_example_session()
    parsed = parse_catalog_search_query(session, query="ㄹㅇㄷㄹ")

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert plan.choseong_used is True
    assert plan.confident_correction is False
    assert plan.fuzzy_enabled is False
    assert plan.variants == ()


def test_recovery_plan_finds_one_edit_brand_dictionary_candidate() -> None:
    session = _seed_example_session()
    parsed = parse_catalog_search_query(session, query="라운드렙")

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert "라운드랩" in plan.variants
    assert plan.corrected_query == "라운드랩"


def test_recovery_plan_disables_fuzzy_for_multi_term_query() -> None:
    session = _seed_example_session()
    parsed = parse_catalog_search_query(session, query="아이폰 케이스")

    plan = build_catalog_search_recovery_plan(session, parsed)

    assert plan.fuzzy_enabled is False


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
