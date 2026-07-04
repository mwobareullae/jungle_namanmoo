from dataclasses import replace
from pathlib import Path
from shutil import copytree

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import Inventory, InventoryMovement, Seller
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
from app.models.data_contract import Product as ProductRecord
from app.services.data_loader import load_data_catalog
from app.services.db_seed import seed_catalog, seed_database
from tests.test_data_loader import EXAMPLES_DIR


def test_seed_database_loads_example_catalog_into_db() -> None:
    session = _make_session()

    result = seed_database(session, EXAMPLES_DIR)

    assert result.products == 2
    assert result.sellers == 1
    assert result.inventories == 0
    assert result.product_skin_profiles == 2
    assert result.ingredient_aliases == 0
    assert result.ingredient_effect_ranges == 2
    assert result.search_documents == 4
    assert _count(session, Concern) == 4
    assert _count(session, Effect) == 5
    assert _count(session, Brand) == 2
    assert _count(session, ProductCategory) == 2
    assert _count(session, Seller) == 1
    assert _count(session, Product) == 2
    assert _count(session, Inventory) == 0
    assert _count(session, ProductImage) == 4
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
    image_row = session.execute(select(ProductImage).order_by(ProductImage.id.asc())).scalars().first()
    assert image_row is not None
    assert image_row.image_type == "thumbnail"
    assert image_row.storage_key == "products/prod_001/thumbnail.jpg"
    product_row = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    assert product_row.seller_id is not None


def test_seed_database_is_idempotent_for_example_catalog() -> None:
    session = _make_session()

    seed_database(session, EXAMPLES_DIR)
    seed_database(session, EXAMPLES_DIR)

    assert _count(session, Product) == 2
    assert _count(session, Seller) == 1
    assert _count(session, ProductIngredient) == 5
    assert _count(session, ProductSkinProfile) == 2
    assert _count(session, IngredientEffectRange) == 2
    assert _count(session, IngredientAlias) == 0
    assert _count(session, ConcernAlias) == 19
    assert _count(session, SearchDocument) == 4


def test_seed_database_loads_optional_product_inventory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_inventory.csv").write_text(
        "product_id,stock_quantity,sales_status,safety_stock,inventory_source,updated_at\n"
        "prod_001,12,ON_SALE,2,AUTO_SEED,2026-07-03T00:00:00Z\n"
        "prod_002,0,SOLD_OUT,1,AUTO_SEED,2026-07-03T00:00:00Z\n",
        encoding="utf-8",
    )
    session = _make_session()

    result = seed_database(session, data_dir)
    seed_database(session, data_dir)

    assert result.inventories == 2
    assert _count(session, Inventory) == 2
    assert _count(session, InventoryMovement) == 2
    inventory = session.execute(
        select(Inventory).join(Product, Inventory.product_id == Product.id).where(Product.product_code == "prod_001")
    ).scalar_one()
    assert inventory.stock_quantity == 12
    assert inventory.sales_status == "ON_SALE"


def test_seed_database_upserts_product_images_by_display_slot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_image_assets.csv").write_text(
        "product_id,image_type,display_order,storage_key\n"
        "prod_001,thumbnail,0,products/prod_001/thumb.jpg\n"
        "prod_001,detail,1,products/prod_001/detail_old.jpg\n"
        "prod_001,detail,1,products/prod_001/detail_new.jpg\n",
        encoding="utf-8",
    )
    session = _make_session()

    seed_database(session, data_dir)
    seed_database(session, data_dir)

    detail_rows = (
        session.execute(
            select(ProductImage)
            .join(Product, ProductImage.product_id == Product.id)
            .where(
                Product.product_code == "prod_001",
                ProductImage.image_type == "detail",
                ProductImage.display_order == 1,
            )
        )
        .scalars()
        .all()
    )
    assert len(detail_rows) == 1
    assert detail_rows[0].storage_key == "products/prod_001/detail_new.jpg"


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


def test_seed_catalog_deduplicates_normalized_brand_codes() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    extra_product = ProductRecord(
        product_id="prod_dupe_brand",
        brand="아 누아",
        name="브랜드 표기 중복 상품",
        category="serum",
        skin_type_tags=(),
        thumbnail_url=None,
        image_urls=(),
        functional_review_text=None,
        functional_cosmetic_status=None,
        functional_cosmetic_claims=(),
        functional_claim_confidence=None,
        functional_claim_basis=None,
    )
    catalog_with_duplicate_brand = replace(
        catalog,
        products=(*catalog.products, extra_product),
    )

    seed_catalog(session, catalog_with_duplicate_brand)

    anua_brands = session.execute(select(Brand).where(Brand.brand_code == "아누아")).scalars().all()
    assert len(anua_brands) == 1


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
