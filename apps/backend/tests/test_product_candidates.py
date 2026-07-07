from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates, list_product_candidates_by_db_ids
from app.services.purchase_conditions import build_brand_aliases, parse_purchase_conditions
from tests.test_data_loader import EXAMPLES_DIR


def test_list_product_candidates_returns_seed_products_without_constraints() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions("")

    candidates = list_product_candidates(session, conditions)

    assert [candidate.product_id for candidate in candidates] == ["prod_001", "prod_002"]
    assert [candidate.lowest_price for candidate in candidates] == [19900, 22900]
    assert candidates[0].thumbnail_url == "products/prod_001/thumbnail.jpg"
    assert not candidates[0].thumbnail_url.startswith("http")


def test_list_product_candidates_applies_brand_category_and_price_max_filters() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions(
        "라운드랩 크림 2만원 이하 추천",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    candidates = list_product_candidates(session, conditions)

    assert [candidate.product_id for candidate in candidates] == ["prod_001"]
    assert candidates[0].brand == "라운드랩"
    assert candidates[0].category_code == "cream"
    assert candidates[0].lowest_price == 19900


def test_list_product_candidates_applies_price_range_to_lowest_price() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions(
        "아누아 세럼 2만원대 추천",
        brand_aliases=build_brand_aliases(("아누아",)),
    )

    candidates = list_product_candidates(session, conditions)

    assert [candidate.product_id for candidate in candidates] == ["prod_002"]
    assert candidates[0].lowest_price == 22900


def test_list_product_candidates_rejects_products_below_requested_price_range() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions(
        "라운드랩 크림 2만원대 추천",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    candidates = list_product_candidates(session, conditions)

    assert candidates == []


def test_list_product_candidates_returns_empty_when_hard_filters_conflict() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions(
        "라운드랩 세럼 추천",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    candidates = list_product_candidates(session, conditions)

    assert candidates == []


def test_list_product_candidates_by_db_ids_preserves_requested_order() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions("")

    candidates = list_product_candidates_by_db_ids(session, conditions, [2, 1, 2])

    assert [candidate.product_id for candidate in candidates] == ["prod_002", "prod_001"]


def test_list_product_candidates_by_db_ids_applies_hard_filters() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions(
        "라운드랩 크림 2만원 이하 추천",
        brand_aliases=build_brand_aliases(("라운드랩",)),
    )

    candidates = list_product_candidates_by_db_ids(session, conditions, [2, 1])

    assert [candidate.product_id for candidate in candidates] == ["prod_001"]


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
