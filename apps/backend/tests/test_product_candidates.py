from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory
from app.db.models.commerce import ProductPopularityMetric
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import (
    list_product_candidates,
    list_product_candidates_by_db_ids,
    list_recommendation_fallback_candidates,
)
from app.services.purchase_conditions import (
    MatchedBrand,
    MatchedCategory,
    ParsedPurchaseConditions,
    build_brand_aliases,
    parse_purchase_conditions,
)
from tests.test_data_loader import EXAMPLES_DIR


def test_list_product_candidates_returns_seed_products_without_constraints() -> None:
    session = _seed_example_session()
    conditions = parse_purchase_conditions("")

    candidates = list_product_candidates(session, conditions)

    assert [candidate.product_id for candidate in candidates] == ["prod_001", "prod_002"]
    assert [candidate.lowest_price for candidate in candidates] == [19900, 22900]
    assert candidates[0].thumbnail_url == "products/prod_001/thumbnail.jpg"
    assert not candidates[0].thumbnail_url.startswith("http")


def test_list_product_candidates_excludes_non_recommendable_products_by_default() -> None:
    session = _seed_example_session()
    product = session.query(Product).filter(Product.product_code == "prod_002").one()
    product.is_recommendable = False
    product.recommend_exclude_reason = "missing_ingredients"
    conditions = parse_purchase_conditions("")

    candidates = list_product_candidates(session, conditions)
    candidates_by_ids = list_product_candidates_by_db_ids(session, conditions, [2, 1, 2])
    catalog_candidates = list_product_candidates(session, conditions, recommendable_only=False)

    assert [candidate.product_id for candidate in candidates] == ["prod_001"]
    assert [candidate.product_id for candidate in candidates_by_ids] == ["prod_001"]
    assert [candidate.product_id for candidate in catalog_candidates] == ["prod_001", "prod_002"]


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


def test_recommendation_fallback_orders_by_popularity_without_thumbnail(
    monkeypatch,
) -> None:
    session = _seed_example_session()
    products = session.scalars(select(Product).order_by(Product.id.asc())).all()
    first, second = products
    session.add_all(
        [
            ProductPopularityMetric(
                product_id=first.id,
                window_days=7,
                popularity_score=10,
            ),
            ProductPopularityMetric(
                product_id=second.id,
                window_days=7,
                popularity_score=100,
            ),
        ]
    )
    session.flush()
    monkeypatch.setattr(
        "app.services.product_candidates.load_thumbnail_storage_keys",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("fallback candidate stage must not load thumbnails")
        ),
    )

    candidates = list_recommendation_fallback_candidates(
        session,
        parse_purchase_conditions(""),
        avoid_ingredients=[],
        limit=20,
    )

    assert [candidate.product_id for candidate in candidates] == [
        "prod_002",
        "prod_001",
    ]
    assert all(candidate.thumbnail_url is None for candidate in candidates)


def test_recommendation_fallback_applies_hard_filters_and_avoid_ingredients() -> None:
    session = _seed_example_session()
    product, brand, category = session.execute(
        select(Product, Brand, ProductCategory)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .where(Product.product_code == "prod_001")
    ).one()
    conditions = ParsedPurchaseConditions(
        categories=(
            MatchedCategory(
                category_code=category.category_code,
                name=category.name,
                matched_text=category.name,
            ),
        ),
        brands=(
            MatchedBrand(
                brand_code=brand.brand_code,
                name=brand.name,
                matched_text=brand.name,
            ),
        ),
        price_min=19_000,
        price_max=20_000,
        price_text="19000 to 20000",
        price_max_text="20000",
    )

    candidates = list_recommendation_fallback_candidates(
        session,
        conditions,
        avoid_ingredients=[],
        limit=20,
    )
    avoided_candidates = list_recommendation_fallback_candidates(
        session,
        conditions,
        avoid_ingredients=["Panthenol"],
        limit=20,
    )

    assert [candidate.product_id for candidate in candidates] == [product.product_code]
    assert avoided_candidates == []


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
