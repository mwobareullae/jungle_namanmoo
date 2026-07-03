import os
from pathlib import Path
from shutil import copytree

import pytest

from app.services.data_loader import DataLoadError, load_data_catalog
from app.services.repository import DataRepository, load_repository


def _resolve_examples_dir() -> Path:
    if os.getenv("DATA_EXAMPLES_DIR"):
        return Path(os.environ["DATA_EXAMPLES_DIR"])

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "examples"
        if candidate.exists():
            return candidate

    return Path("/data/examples")


EXAMPLES_DIR = _resolve_examples_dir()


def test_load_data_catalog_reads_example_files() -> None:
    catalog = load_data_catalog(EXAMPLES_DIR)

    assert catalog.products[0].product_id == "prod_001"
    assert catalog.products[0].category == "cream"
    assert catalog.products[0].skin_type_tags == ("건성", "중성", "수부지")
    assert catalog.products[0].functional_cosmetic_status == "NOT_FUNCTIONAL"
    assert catalog.products[0].functional_claim_confidence == "not_applicable"
    assert catalog.products[1].functional_cosmetic_status == "FUNCTIONAL_CONFIRMED"
    assert catalog.products[1].functional_claim_confidence == "unknown"
    assert catalog.product_prices[0].price == 19900
    assert catalog.product_prices[0].mall_name == "올리브영"
    assert catalog.product_prices[0].is_lowest is True
    assert catalog.product_ingredients[0].ingredient_id == "ing_panthenol"
    assert catalog.product_ingredients[-1].concentration_text == "나이아신아마이드 5%"
    assert catalog.product_ingredients[-1].concentration_value == 5.0
    assert catalog.product_ingredients[-1].normalized_concentration_unit == "%"
    assert catalog.product_skin_profiles[0].product_id == "prod_001"
    assert catalog.product_skin_profiles[0].dry_fit == pytest.approx(0.9)
    assert catalog.product_skin_profiles[0].sensitive_fit == pytest.approx(0.8)
    assert catalog.ingredients[0].name_ko == "판테놀"
    assert catalog.ingredient_aliases == ()
    assert catalog.ingredient_effects[0].effect_score == 90
    assert catalog.ingredient_effect_ranges[0].ingredient_id == "ing_niacinamide"
    assert catalog.ingredient_effect_ranges[0].optimal_min == pytest.approx(4.0)
    assert catalog.ingredient_effect_ranges[0].excessive_min == pytest.approx(10.0)
    assert catalog.ingredient_evidence[0].evidence_level == "high"
    assert catalog.ingredient_evidence[0].source_type == "paper"
    assert catalog.ingredient_evidence[0].source_authority_score == pytest.approx(0.9)
    assert catalog.ingredient_evidence[0].summary
    assert catalog.risk_flags[0].severity == "medium"
    assert catalog.risk_flags[0].severity_score == pytest.approx(0.6)
    assert catalog.risk_flags[0].applies_to == ("sensitive",)
    assert catalog.concern_tags[0].synonyms
    assert catalog.concern_effects[0].weight == 1.0
    assert catalog.search_documents[0].text


def test_load_data_catalog_reads_optional_ingredient_aliases(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "ingredient_aliases.csv").write_text(
        "alias,canonical_id,alias_type,confidence,source\n"
        "판테놀,ing_panthenol,ko,high,식약처\n"
        "Panthenol,ing_panthenol,inci,high,INCI\n"
        "비타민B5,ing_panthenol,synonym,med,common\n",
        encoding="utf-8",
    )

    catalog = load_data_catalog(data_dir)

    assert len(catalog.ingredient_aliases) == 3
    assert catalog.ingredient_aliases[2].ingredient_id == "ing_panthenol"
    assert catalog.ingredient_aliases[2].alias == "비타민B5"
    assert catalog.ingredient_aliases[2].confidence == "medium"


def test_load_data_catalog_reads_optional_product_image_assets(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_image_assets.csv").write_text(
        "product_id,image_type,display_order,source_image_url,storage_key,public_url,upload_status\n"
        "prod_001,thumbnail,0,https://example.com/source.jpg,products/prod_001/thumb.jpg,,PENDING_UPLOAD\n"
        "prod_001,detail,1,https://example.com/detail.jpg,products/prod_001/detail_001.jpg,,PENDING_UPLOAD\n",
        encoding="utf-8",
    )

    catalog = load_data_catalog(data_dir)

    assert len(catalog.product_image_assets) == 2
    assert catalog.product_image_assets[0].image_type == "thumbnail"
    assert catalog.product_image_assets[0].storage_key == "products/prod_001/thumb.jpg"


def test_load_data_catalog_reads_optional_product_inventory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_inventory.csv").write_text(
        "product_id,stock_quantity,sales_status,safety_stock,inventory_source,updated_at\n"
        "prod_001,12,ON_SALE,2,AUTO_SEED,2026-07-03T00:00:00Z\n"
        "prod_002,0,SOLD_OUT,1,AUTO_SEED,2026-07-03T00:00:00Z\n",
        encoding="utf-8",
    )

    catalog = load_data_catalog(data_dir)

    assert len(catalog.product_inventories) == 2
    assert catalog.product_inventories[0].stock_quantity == 12
    assert catalog.product_inventories[0].sales_status == "ON_SALE"


def test_load_data_catalog_reports_missing_ingredient_alias_reference(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "ingredient_aliases.csv").write_text(
        "alias,canonical_id,alias_type,confidence,source\n"
        "없는성분,missing_ingredient,ko,high,식약처\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="canonical_id 참조를 찾을 수 없습니다"):
        load_data_catalog(data_dir)


def test_loader_reports_ingredient_alias_conflict(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "ingredient_aliases.csv").write_text(
        "alias,canonical_id,alias_type,confidence,source\n"
        "동일별칭,ing_panthenol,ko,high,식약처\n"
        "동일 별칭,ing_glycerin,ko,high,식약처\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="둘 이상의 canonical_id"):
        load_data_catalog(data_dir)


def test_repository_exposes_lookup_methods() -> None:
    repository = load_repository(EXAMPLES_DIR)

    assert isinstance(repository, DataRepository)
    assert repository.list_products()[0].product_id == "prod_001"
    assert repository.get_product("prod_001").name == "자작나무 수분 크림"
    assert repository.get_product("missing") is None
    assert repository.get_product_prices("prod_001")[0].currency == "KRW"
    assert repository.get_product_ingredients("prod_001")[0].display_order == 1
    assert repository.get_ingredient("ing_panthenol").name_en == "Panthenol"
    assert repository.get_effects_for_concern("concern_pore")[0].effect_name == "피지 조절"
    assert repository.get_evidence_for_ingredient("ing_panthenol")[0].source_title
    assert repository.list_search_documents()[0].doc_id == "doc_prod_001"


def test_loader_reports_missing_csv_header(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "products.csv").write_text(
        "product_id,brand,name,category,thumbnail_url,image_urls\n"
        "prod_001,예시브랜드,예시 상품,,\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError) as exc_info:
        load_data_catalog(data_dir)
    assert "products.csv 필수 컬럼이 없습니다" in str(exc_info.value)
    assert "skin_type_tags" in str(exc_info.value)


def test_loader_reports_invalid_product_skin_profile_reference(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_skin_profiles.csv").write_text(
        "product_id,dry_fit,oily_fit,combination_fit,normal_fit,dehydrated_oily_fit,"
        "sensitive_fit,sensitivity_tag,confidence,reason\n"
        "missing_product,0.9,0.3,0.6,0.8,0.9,0.8,민감가능,medium,missing\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="product_id"):
        load_data_catalog(data_dir)


def test_loader_reports_invalid_product_reference(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_ingredients.csv").write_text(
        "product_id,ingredient_id,ingredient_name,content_confidence,display_order,"
        "concentration_text,concentration_value,concentration_unit,concentration_confidence,"
        "normalized_concentration_value,normalized_concentration_unit\n"
        "missing_product,ing_panthenol,판테놀,high,1,,,,unknown,,\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="product_id 참조를 찾을 수 없습니다"):
        load_data_catalog(data_dir)
