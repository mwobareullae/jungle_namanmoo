from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient
from app.db.models.search import SearchDocument
from app.db.models.taxonomy import Concern, ConcernAlias, Effect, IngredientEvidence
from app.db.session import make_engine
from app.services.data_loader import load_data_catalog
from app.services.db_seed import seed_catalog, seed_database
from tests.test_data_loader import EXAMPLES_DIR


def test_seed_database_loads_example_catalog_into_db() -> None:
    session = _make_session()

    result = seed_database(session, EXAMPLES_DIR)

    assert result.products == 2
    assert result.search_documents == 4
    assert _count(session, Concern) == 4
    assert _count(session, Effect) == 5
    assert _count(session, Brand) == 2
    assert _count(session, ProductCategory) == 2
    assert _count(session, Product) == 2
    assert _count(session, ProductIngredient) == 5
    assert _count(session, IngredientEvidence) == 6
    assert _count(session, SearchDocument) == 4
    niacinamide_row = session.execute(
        select(ProductIngredient).where(ProductIngredient.ingredient_name == "나이아신아마이드")
    ).scalar_one()
    assert niacinamide_row.concentration_text == "나이아신아마이드 5%"
    assert niacinamide_row.normalized_concentration_unit == "%"


def test_seed_database_is_idempotent_for_example_catalog() -> None:
    session = _make_session()

    seed_database(session, EXAMPLES_DIR)
    seed_database(session, EXAMPLES_DIR)

    assert _count(session, Product) == 2
    assert _count(session, ProductIngredient) == 5
    assert _count(session, ConcernAlias) == 19
    assert _count(session, SearchDocument) == 4


def test_seed_catalog_skips_duplicate_product_ingredient_pairs() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    catalog_with_duplicate = replace(
        catalog,
        product_ingredients=(
            *catalog.product_ingredients,
            catalog.product_ingredients[0],
        ),
    )

    result = seed_catalog(session, catalog_with_duplicate)

    assert result.product_ingredients == 5
    assert _count(session, ProductIngredient) == 5


def test_seed_database_links_search_documents_to_source_rows() -> None:
    session = _make_session()

    seed_database(session, EXAMPLES_DIR)

    product_document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == "doc_prod_001")
    ).scalar_one()
    ingredient_document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == "doc_ing_panthenol")
    ).scalar_one()

    assert product_document.product_id is not None
    assert product_document.ingredient_id is None
    assert ingredient_document.ingredient_id is not None
    assert ingredient_document.product_id is None


def _make_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()
