from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product, ProductIngredient
from app.db.models.search import SearchDocument
from app.db.session import make_engine
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect
from app.services.db_seed import seed_database
from app.services.search_index_builder import DOCUMENT_CODE_PREFIX, build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_build_product_search_index_documents_dry_run_does_not_write_documents() -> None:
    session = _seed_example_session()

    result = build_product_search_index_documents(session, dry_run=True)

    assert result.scanned == 2
    assert result.upserted == 2
    assert result.unchanged == 0
    assert result.pending_ingredients_skipped == 0
    assert result.dry_run is True
    assert _search_document_count(session) == 4


def test_build_product_search_index_documents_creates_join_documents() -> None:
    session = _seed_example_session()

    result = build_product_search_index_documents(session)

    assert result.scanned == 2
    assert result.upserted == 2
    assert result.unchanged == 0
    assert _search_document_count(session) == 6

    document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()

    assert document.document_type == "product"
    assert document.product_id is not None
    assert document.ingredient_id is None
    assert document.ingredient_evidence_id is None
    assert document.title == "라운드랩 자작나무 수분 크림"
    assert "성분 조인 요약" in document.content
    assert "판테놀" in document.content
    assert "장벽 강화" in document.content
    assert "보습" in document.content
    assert "cream" in document.keywords


def test_build_product_search_index_documents_skips_pending_ingredients() -> None:
    session = _seed_example_session()
    product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    effect = session.execute(select(Effect).where(Effect.effect_code == "effect_moisturizing")).scalar_one()
    pending_ingredients = [
        Ingredient(
            ingredient_code="ing_pending_example",
            name_ko="검증전성분",
            name_en="Pending Ingredient",
            normalized_name="검증전성분",
            is_active=True,
        ),
        Ingredient(
            ingredient_code="foreign_pending_example",
            name_ko="해외검증전성분",
            name_en="Foreign Pending Ingredient",
            normalized_name="해외검증전성분",
            is_active=True,
        ),
    ]
    session.add_all(pending_ingredients)
    session.flush()
    for display_order, pending_ingredient in enumerate(pending_ingredients, start=99):
        session.add(
            ProductIngredient(
                product_id=product.id,
                ingredient_id=pending_ingredient.id,
                ingredient_name=pending_ingredient.name_ko,
                content_confidence="low",
                display_order=display_order,
                concentration_confidence="unknown",
            )
        )
        session.add(
            IngredientEffect(
                ingredient_id=pending_ingredient.id,
                effect_id=effect.id,
                effect_score=99,
            )
        )

    result = build_product_search_index_documents(session)
    document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()

    assert result.pending_ingredients_skipped == 2
    assert "검증전성분" not in document.content
    assert "검증전성분" not in document.keywords
    assert "해외검증전성분" not in document.content
    assert "해외검증전성분" not in document.keywords


def test_build_product_search_index_documents_is_idempotent() -> None:
    session = _seed_example_session()

    build_product_search_index_documents(session)
    result = build_product_search_index_documents(session)

    assert result.scanned == 2
    assert result.upserted == 0
    assert result.unchanged == 2
    assert _search_document_count(session) == 6


def test_build_product_search_index_documents_resets_embedding_when_content_changes() -> None:
    session = _seed_example_session()
    build_product_search_index_documents(session)
    document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()
    document.embedding = "[0.1,0.2]"
    document.embedding_model = "local-test"
    document.embedding_dimensions = 2
    session.flush()

    product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    product.product_name = "자작나무 수분 크림 리뉴얼"
    result = build_product_search_index_documents(session)

    assert result.upserted == 1
    assert result.unchanged == 1
    assert document.embedding is None
    assert document.embedding_model is None
    assert document.embedding_dimensions is None
    assert document.title == "라운드랩 자작나무 수분 크림 리뉴얼"


def test_build_product_search_index_documents_preserves_unchanged_document_embedding() -> None:
    session = _seed_example_session()
    build_product_search_index_documents(session)
    changed_document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()
    unchanged_document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_002")
    ).scalar_one()
    for document in (changed_document, unchanged_document):
        document.embedding = "[0.1,0.2]"
        document.embedding_model = "local-test"
        document.embedding_dimensions = 2
    session.flush()

    product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    product.product_name = "자작나무 수분 크림 리뉴얼"
    result = build_product_search_index_documents(session)

    assert result.upserted == 1
    assert result.unchanged == 1
    assert changed_document.embedding is None
    assert changed_document.embedding_model is None
    assert changed_document.embedding_dimensions is None
    assert unchanged_document.embedding == "[0.1,0.2]"
    assert unchanged_document.embedding_model == "local-test"
    assert unchanged_document.embedding_dimensions == 2


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session


def _search_document_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(SearchDocument)).scalar_one()
