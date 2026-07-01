from dataclasses import replace
from pathlib import Path
from shutil import copytree

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductSkinProfile
from app.db.models.search import SearchDocument
from app.db.models.taxonomy import (
    Concern,
    ConcernAlias,
    Effect,
    IngredientAlias,
    IngredientEffectRange,
    IngredientEvidence,
    RiskFlag,
)
from app.db.session import make_engine
from app.models.data_contract import IngredientAlias as IngredientAliasRecord
from app.services.data_loader import load_data_catalog
from app.services.db_seed import seed_catalog, seed_database
from tests.test_data_loader import EXAMPLES_DIR


def test_seed_database_loads_example_catalog_into_db() -> None:
    session = _make_session()

    result = seed_database(session, EXAMPLES_DIR)

    assert result.products == 2
    assert result.product_skin_profiles == 2
    assert result.ingredient_aliases == 0
    assert result.ingredient_effect_ranges == 2
    assert result.search_documents == 4
    assert _count(session, Concern) == 4
    assert _count(session, Effect) == 5
    assert _count(session, Brand) == 2
    assert _count(session, ProductCategory) == 2
    assert _count(session, Product) == 2
    assert _count(session, ProductIngredient) == 5
    assert _count(session, ProductSkinProfile) == 2
    assert _count(session, IngredientAlias) == 0
    assert _count(session, IngredientEffectRange) == 2
    assert _count(session, IngredientEvidence) == 6
    assert _count(session, RiskFlag) == 1
    assert _count(session, SearchDocument) == 4
    niacinamide_row = session.execute(
        select(ProductIngredient).where(ProductIngredient.ingredient_name == "나이아신아마이드")
    ).scalar_one()
    assert niacinamide_row.concentration_text == "나이아신아마이드 5%"
    assert niacinamide_row.normalized_concentration_unit == "%"
    evidence_row = session.execute(select(IngredientEvidence)).scalars().first()
    assert evidence_row is not None
    assert evidence_row.source_type == "paper"
    assert evidence_row.source_authority_score is not None
    risk_row = session.execute(select(RiskFlag)).scalar_one()
    assert risk_row.applies_to == "sensitive"
    assert risk_row.severity_score is not None


def test_seed_database_is_idempotent_for_example_catalog() -> None:
    session = _make_session()

    seed_database(session, EXAMPLES_DIR)
    seed_database(session, EXAMPLES_DIR)

    assert _count(session, Product) == 2
    assert _count(session, ProductIngredient) == 5
    assert _count(session, ProductSkinProfile) == 2
    assert _count(session, IngredientEffectRange) == 2
    assert _count(session, IngredientAlias) == 0
    assert _count(session, ConcernAlias) == 19
    assert _count(session, SearchDocument) == 4


def test_seed_database_deduplicates_existing_risk_flags() -> None:
    session = _make_session()
    seed_database(session, EXAMPLES_DIR)
    risk_row = session.execute(select(RiskFlag)).scalar_one()
    session.add(
        RiskFlag(
            ingredient_id=risk_row.ingredient_id,
            risk_type=risk_row.risk_type,
            display_text=risk_row.display_text,
            severity=risk_row.severity,
            severity_score=risk_row.severity_score,
            applies_to=risk_row.applies_to,
            condition=risk_row.condition,
            source_type=risk_row.source_type,
            source_url=risk_row.source_url,
        )
    )
    session.flush()

    assert _count(session, RiskFlag) == 2

    seed_database(session, EXAMPLES_DIR)

    assert _count(session, RiskFlag) == 1


def test_seed_database_loads_optional_ingredient_aliases(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "ingredient_aliases.csv").write_text(
        "alias,canonical_id,alias_type,confidence,source\n"
        "판테놀,ing_panthenol,ko,high,식약처\n"
        "Panthenol,ing_panthenol,inci,high,INCI\n"
        "비타민B5,ing_panthenol,synonym,med,common\n",
        encoding="utf-8",
    )
    session = _make_session()

    result = seed_database(session, data_dir)
    seed_database(session, data_dir)

    assert result.ingredient_aliases == 3
    assert _count(session, IngredientAlias) == 3
    alias_row = session.execute(
        select(IngredientAlias).where(IngredientAlias.normalized_alias == "비타민b5")
    ).scalar_one()
    assert alias_row.alias == "비타민B5"
    assert alias_row.confidence == "medium"


def test_seed_catalog_reports_missing_ingredient_alias_reference() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    catalog_with_missing_alias_reference = replace(
        catalog,
        ingredient_aliases=(
            IngredientAliasRecord(
                ingredient_id="missing_ingredient",
                alias="없는성분",
                alias_type="ko",
                confidence="high",
                source="식약처",
            ),
        ),
    )

    try:
        seed_catalog(session, catalog_with_missing_alias_reference)
    except ValueError as exc:
        assert "ingredient_aliases.csv의 canonical_id 참조를 찾을 수 없습니다" in str(exc)
    else:
        raise AssertionError("seed_catalog should reject missing ingredient alias references")


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
