import json
import logging
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from shutil import copytree

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.services.db_seed as db_seed
from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import Inventory, InventoryMovement, ProductPopularityMetric, Seller
from app.db.models.search import SearchDocument
from app.db.models.taxonomy import (
    EvidenceDiscoveryCandidate,
    Concern,
    ConcernAlias,
    Effect,
    IngredientAlias,
    Ingredient,
    IngredientEffectRange,
    IngredientEvidence,
    RiskFlag,
)
from app.db.session import make_engine
from app.models.data_contract import Ingredient as IngredientRecord
from app.models.data_contract import IngredientAlias as IngredientAliasRecord
from app.models.data_contract import IngredientCanonicalMapping as IngredientCanonicalMappingRecord
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
    assert result.popularity_metrics == 0
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
    assert _count(session, ProductPopularityMetric) == 0
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
    assert evidence_row.canonical_evidence_key is not None
    assert evidence_row.review_status == "candidate_unverified"
    assert evidence_row.result_direction == "unclear"
    assert evidence_row.score_use_level == "reference_only"
    assert evidence_row.is_representative is False
    assert evidence_row.is_current is True
    risk_row = session.execute(select(RiskFlag)).scalar_one()
    assert risk_row.applies_to == "sensitive"
    assert risk_row.severity_score is not None
    image_row = session.execute(select(ProductImage).order_by(ProductImage.id.asc())).scalars().first()
    assert image_row is not None
    assert image_row.image_type == "thumbnail"
    assert image_row.storage_key == "products/prod_001/thumbnail.jpg"
    product_row = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    assert product_row.seller_id is not None
    assert product_row.is_recommendable is True
    assert product_row.recommend_exclude_reason is None


def test_seed_catalog_persists_product_recommendation_eligibility() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    catalog_with_excluded_product = replace(
        catalog,
        products=(
            replace(
                catalog.products[0],
                is_recommendable=False,
                recommend_exclude_reason="missing_ingredients",
            ),
            catalog.products[1],
        ),
    )

    seed_catalog(session, catalog_with_excluded_product)

    excluded_product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    included_product = session.execute(select(Product).where(Product.product_code == "prod_002")).scalar_one()
    assert excluded_product.is_recommendable is False
    assert excluded_product.recommend_exclude_reason == "missing_ingredients"
    assert included_product.is_recommendable is True
    assert included_product.recommend_exclude_reason is None


def test_seed_catalog_updates_evidence_by_canonical_key() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    seed_catalog(session, catalog)
    evidence = catalog.ingredient_evidence[0]
    original = session.execute(
        select(IngredientEvidence).where(
            IngredientEvidence.canonical_evidence_key == evidence.canonical_evidence_key
        )
    ).scalar_one()
    original_id = original.id
    updated_title = f"{evidence.source_title} 수정"
    updated_catalog = replace(
        catalog,
        ingredient_evidence=(
            replace(evidence, source_title=updated_title),
            *catalog.ingredient_evidence[1:],
        ),
    )

    seed_catalog(session, updated_catalog)

    updated = session.execute(
        select(IngredientEvidence).where(
            IngredientEvidence.canonical_evidence_key == evidence.canonical_evidence_key
        )
    ).scalar_one()
    assert updated.id == original_id
    assert updated.source_title == updated_title
    assert _count(session, IngredientEvidence) == len(catalog.ingredient_evidence)


def test_seed_catalog_marks_missing_evidence_inactive_without_deleting_it() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    seed_catalog(session, catalog)
    removed = catalog.ingredient_evidence[-1]
    reduced_catalog = replace(catalog, ingredient_evidence=catalog.ingredient_evidence[:-1])

    seed_catalog(session, reduced_catalog)

    removed_row = session.execute(
        select(IngredientEvidence).where(
            IngredientEvidence.canonical_evidence_key == removed.canonical_evidence_key
        )
    ).scalar_one()
    assert removed_row.is_current is False
    assert _count(session, IngredientEvidence) == len(catalog.ingredient_evidence)


def test_seed_catalog_keeps_admin_promoted_evidence_active() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    seed_catalog(session, catalog)
    removed = catalog.ingredient_evidence[-1]
    evidence = session.execute(
        select(IngredientEvidence).where(
            IngredientEvidence.canonical_evidence_key == removed.canonical_evidence_key
        )
    ).scalar_one()
    session.add(
        EvidenceDiscoveryCandidate(
            discovery_key=f"admin-promoted:{evidence.id}",
            ingredient_id=evidence.ingredient_id,
            effect_id=evidence.effect_id,
            paper_key=evidence.canonical_evidence_key,
            pmid=evidence.pmid,
            doi=evidence.doi,
            title=evidence.source_title or "Admin promoted evidence",
            source_url=evidence.source_url or "https://example.com/evidence",
            discovery_scope="new_paper",
            review_status="accepted",
            promoted_evidence_id=evidence.id,
        )
    )
    session.flush()

    reduced_catalog = replace(catalog, ingredient_evidence=catalog.ingredient_evidence[:-1])
    seed_catalog(session, reduced_catalog)

    assert evidence.is_current is True


def test_seed_database_emits_seed_performance_log() -> None:
    session = _make_session()
    logs = _capture_performance_logs()

    try:
        result = seed_database(session, EXAMPLES_DIR)
    finally:
        logs.close()

    payload = next(log for log in logs.payloads() if log["event"] == "seed_database_completed")
    loaded_payload = next(log for log in logs.payloads() if log["event"] == "seed_catalog_loaded")
    phase_payloads = [log for log in logs.payloads() if log["event"] == "seed_phase_completed"]
    assert result.products == 2
    assert loaded_payload["data_dir"] == str(EXAMPLES_DIR)
    assert loaded_payload["row_counts"]["products.csv"] == 2
    assert loaded_payload["loaded_row_count"] > 0
    assert [payload["phase"] for payload in phase_payloads] == [
        "taxonomy",
        "ingredients",
        "product_catalog",
        "commerce_seed",
        "product_ingredients",
        "product_skin_profiles",
        "search_documents",
    ]
    assert phase_payloads[0]["phase_order"] == 1
    assert phase_payloads[-1]["phase_order"] == 7
    assert all(phase["phase_count"] == 7 for phase in phase_payloads)
    assert payload["data_dir"] == str(EXAMPLES_DIR)
    assert payload["row_counts"]["products.csv"] == 2
    assert payload["row_counts"]["product_ingredients.csv"] == 5
    assert payload["row_counts"]["vector_docs.csv"] == 4
    assert payload["loaded_row_count"] > 0
    assert payload["seed_counts"]["products"] == 2
    assert payload["seed_counts"]["product_ingredients"] == 5
    assert payload["seeded_entity_count"] > 0
    assert payload["error_count"] == 0
    assert payload["failed_row_sample_count"] == 0
    assert payload["counting_mode"] == "loaded_rows_and_final_seed_counts"
    assert "duration_ms" in payload


def test_seed_database_streams_product_ingredients_from_data_dir(monkeypatch) -> None:
    captured_include_flags: list[bool] = []
    original_load_data_catalog = db_seed.load_data_catalog

    def fake_load_data_catalog(data_dir, *, include_product_ingredients=True):
        captured_include_flags.append(include_product_ingredients)
        return original_load_data_catalog(
            data_dir,
            include_product_ingredients=include_product_ingredients,
        )

    monkeypatch.setattr(db_seed, "load_data_catalog", fake_load_data_catalog)
    session = _make_session()

    result = seed_database(session, EXAMPLES_DIR)

    assert captured_include_flags == [False]
    assert result.product_ingredients == 5
    assert _count(session, ProductIngredient) == 5


def test_seed_product_ingredients_emits_progress_log(monkeypatch) -> None:
    monkeypatch.setattr(db_seed, "SEED_PROGRESS_INTERVAL_ROWS", 2)
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    logs = _capture_performance_logs()

    try:
        seed_catalog(session, catalog, data_dir="example-data")
    finally:
        logs.close()

    progress_payloads = [
        log for log in logs.payloads() if log["event"] == "seed_product_ingredients_progress"
    ]
    assert [payload["processed_row_count"] for payload in progress_payloads] == [2, 4]
    assert all(payload["phase"] == "product_ingredients" for payload in progress_payloads)
    assert all(payload["total_row_count"] == 5 for payload in progress_payloads)
    assert progress_payloads[0]["data_dir"] == "example-data"
    assert progress_payloads[0]["deduplicated_pair_count"] == 2
    assert progress_payloads[0]["progress_percent"] == 40.0


def test_seed_database_emits_failure_performance_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "ingredient_aliases.csv").write_text(
        "alias,canonical_id,alias_type,confidence,source\n"
        "missing,missing_ingredient,ko,high,test\n",
        encoding="utf-8",
    )
    session = _make_session()
    logs = _capture_performance_logs()

    try:
        seed_database(session, data_dir)
    except ValueError:
        pass
    else:
        raise AssertionError("seed_database should reject missing ingredient alias references")
    finally:
        logs.close()

    payload = next(log for log in logs.payloads() if log["event"] == "seed_database_failed")
    assert payload["data_dir"] == str(data_dir)
    assert "row_counts" not in payload
    assert payload["error"] == "DataLoadError"
    assert payload["error_count"] == 1
    assert payload["failed_row_sample_count"] == 0
    assert "duration_ms" in payload


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


def test_seed_database_loads_optional_product_market_signals(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_market_signals.csv").write_text(
        "product_id,review_count,average_rating,sales_count,sales_rank,recent_view_count,"
        "wishlist_count,cart_add_count,source,updated_at\n"
        "prod_001,20,4.5,12,,100,8,7,mock_p2_home,2026-07-04T00:00:00+09:00\n"
        "prod_002,5,,0,3,20,2,1,mock_p2_home,2026-07-04T00:00:00+09:00\n",
        encoding="utf-8",
    )
    session = _make_session()

    result = seed_database(session, data_dir)
    seed_database(session, data_dir)

    assert result.popularity_metrics == 2
    assert _count(session, ProductPopularityMetric) == 2
    metric = session.execute(
        select(ProductPopularityMetric)
        .join(Product, ProductPopularityMetric.product_id == Product.id)
        .where(Product.product_code == "prod_001")
    ).scalar_one()
    assert metric.window_days == 7
    assert metric.view_count == 100
    assert metric.click_count == 0
    assert metric.cart_add_count == 7
    assert metric.order_count == 12
    assert metric.units_sold == 12
    assert metric.review_count == 0
    assert metric.average_rating is None
    assert metric.popularity_score > 0
    assert metric.score_version == "mock_market_signals_v1"


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


def test_seed_catalog_batches_product_ingredient_upserts(monkeypatch) -> None:
    monkeypatch.setattr(db_seed, "SEED_PRODUCT_INGREDIENT_BATCH_SIZE", 2)
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
    seed_catalog(session, catalog_with_duplicate)

    assert result.product_ingredients == 5
    assert _count(session, ProductIngredient) == 5


def test_seed_catalog_replaces_mapped_pending_product_ingredient() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    pending_code = "ing_pending_panthenol"
    pending_ingredient = IngredientRecord(
        ingredient_id=pending_code,
        name_ko="판테놀 원문",
        name_en="Panthenol raw",
        description="pending source",
        source_url=None,
    )
    source_record = replace(
        catalog.product_ingredients[0],
        ingredient_id=pending_code,
        ingredient_name="Panthenol",
    )
    source_catalog = replace(
        catalog,
        ingredients=(*catalog.ingredients, pending_ingredient),
        product_ingredients=(source_record, *catalog.product_ingredients[1:]),
    )
    seed_catalog(session, source_catalog)
    pending_row = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == pending_code)
    ).scalar_one()
    assert session.execute(
        select(ProductIngredient).where(ProductIngredient.ingredient_id == pending_row.id)
    ).scalar_one_or_none() is not None

    mapped_catalog = replace(
        source_catalog,
        ingredient_canonical_mappings=(
            IngredientCanonicalMappingRecord(
                source_ingredient_id=pending_code,
                source_ingredient_name=None,
                canonical_id="ing_panthenol",
                mapping_type="official_exact",
                confidence="high",
                source="KCIA 2026-06-30",
            ),
        ),
    )
    result = seed_catalog(session, mapped_catalog)

    target_row = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == "ing_panthenol")
    ).scalar_one()
    assert result.product_ingredients == 5
    assert session.execute(
        select(ProductIngredient).where(ProductIngredient.ingredient_id == pending_row.id)
    ).scalar_one_or_none() is None
    assert session.execute(
        select(ProductIngredient).where(ProductIngredient.ingredient_id == target_row.id)
    ).scalar_one_or_none() is not None


def test_seed_catalog_applies_exact_name_override_without_moving_other_names() -> None:
    session = _make_session()
    catalog = load_data_catalog(EXAMPLES_DIR)
    mapped_catalog = replace(
        catalog,
        ingredient_canonical_mappings=(
            IngredientCanonicalMappingRecord(
                source_ingredient_id="ing_panthenol",
                source_ingredient_name="판테놀",
                canonical_id="ing_niacinamide",
                mapping_type="exact_name_override",
                confidence="high",
                source="test",
            ),
        ),
    )

    seed_catalog(session, mapped_catalog)

    panthenol = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == "ing_panthenol")
    ).scalar_one()
    niacinamide = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == "ing_niacinamide")
    ).scalar_one()
    product = session.execute(
        select(Product).where(Product.product_code == "prod_001")
    ).scalar_one()
    assert session.execute(
        select(ProductIngredient).where(
            ProductIngredient.product_id == product.id,
            ProductIngredient.ingredient_id == panthenol.id,
        )
    ).scalar_one_or_none() is None
    assert session.execute(
        select(ProductIngredient).where(
            ProductIngredient.product_id == product.id,
            ProductIngredient.ingredient_id == niacinamide.id,
        )
    ).scalar_one_or_none() is not None


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


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def payloads(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler
