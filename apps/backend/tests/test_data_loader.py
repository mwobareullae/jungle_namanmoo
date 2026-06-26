from pathlib import Path
from shutil import copytree

import pytest

from app.services.data_loader import DataLoadError, load_data_catalog
from app.services.repository import DataRepository, load_repository


EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "data" / "examples"


def test_load_data_catalog_reads_example_files() -> None:
    catalog = load_data_catalog(EXAMPLES_DIR)

    assert catalog.products[0].product_id == "prod_001"
    assert catalog.products[0].category == "cream"
    assert catalog.products[0].skin_type_tags == ("건성", "중성", "수부지")
    assert catalog.product_prices[0].price == 19900
    assert catalog.product_prices[0].mall_name == "올리브영"
    assert catalog.product_prices[0].is_lowest is True
    assert catalog.product_ingredients[0].ingredient_id == "ing_panthenol"
    assert catalog.ingredients[0].name_ko == "판테놀"
    assert catalog.ingredient_effects[0].effect_score == 90
    assert catalog.ingredient_evidence[0].evidence_level == "high"
    assert catalog.ingredient_evidence[0].summary
    assert catalog.risk_flags[0].severity == "medium"
    assert catalog.concern_tags[0].synonyms
    assert catalog.concern_effects[0].weight == 1.0
    assert catalog.search_documents[0].text


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

    with pytest.raises(DataLoadError, match="products.csv 필수 컬럼이 없습니다: skin_type_tags"):
        load_data_catalog(data_dir)


def test_loader_reports_invalid_product_reference(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    copytree(EXAMPLES_DIR, data_dir)
    (data_dir / "product_ingredients.csv").write_text(
        "product_id,ingredient_id,ingredient_name,content_confidence,display_order\n"
        "missing_product,ing_panthenol,판테놀,high,1\n",
        encoding="utf-8",
    )

    with pytest.raises(DataLoadError, match="product_id 참조를 찾을 수 없습니다"):
        load_data_catalog(data_dir)
