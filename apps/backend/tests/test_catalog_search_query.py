from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_query import parse_catalog_search_query
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


def test_catalog_query_parser_extracts_brand_category_price_and_sort() -> None:
    session = _seed_example_session()

    parsed = parse_catalog_search_query(
        session,
        query="2만원 이하 라운드랩 수분크림 인기순",
    )

    assert parsed.text_query == "라운드랩 수분크림"
    assert parsed.filters.brand_codes == ("라운드랩",)
    assert parsed.filters.category_codes == ("cream",)
    assert parsed.filters.max_price == 20_000
    assert parsed.sort == CatalogSearchSort.POPULAR


def test_catalog_query_parser_extracts_rating_stock_and_price_band() -> None:
    session = _seed_example_session()

    parsed = parse_catalog_search_query(
        session,
        query="1만원대 4점 이상 재고 있는 세럼",
    )

    assert parsed.text_query == "세럼"
    assert parsed.filters.category_codes == ("serum",)
    assert parsed.filters.min_price == 10_000
    assert parsed.filters.max_price == 19_999
    assert parsed.filters.min_rating == 4.0
    assert parsed.filters.in_stock is True


def test_explicit_catalog_filters_override_query_filters() -> None:
    session = _seed_example_session()

    parsed = parse_catalog_search_query(
        session,
        query="2만원 이하 라운드랩 수분크림 인기순",
        brands=("아누아",),
        categories=("serum",),
        max_price=30_000,
        in_stock=False,
        sort=CatalogSearchSort.NEWEST,
        sort_is_explicit=True,
    )

    assert parsed.filters.brand_codes == ("아누아",)
    assert parsed.filters.category_codes == ("serum",)
    assert parsed.filters.max_price == 30_000
    assert parsed.filters.in_stock is False
    assert parsed.sort == CatalogSearchSort.NEWEST


def test_explicit_feature_and_skin_type_filters_are_preserved() -> None:
    session = _seed_example_session()

    parsed = parse_catalog_search_query(
        session,
        query="수분 크림",
        features=("moisturizing_calming",),
        skin_types=("dehydrated_oily",),
    )

    assert parsed.filters.features == ("moisturizing_calming",)
    assert parsed.filters.skin_types == ("dehydrated_oily",)


def test_brand_detection_requires_complete_token_phrases() -> None:
    session = _seed_example_session()

    smith = parse_catalog_search_query(session, query="Smith's Rosebud Trio")
    pencil = parse_catalog_search_query(
        session,
        query="Brow Wiz Precision Eyebrow Pencil - Soft Brown",
    )

    assert smith.filters.brand_codes == ()
    assert pencil.filters.brand_codes == ()


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
