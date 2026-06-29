from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

import app.db.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.db.session import make_engine, normalize_database_url


def test_database_url_uses_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://user:pass@db:5432/app") == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )
    assert normalize_database_url("postgresql+psycopg://user:pass@db:5432/app") == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )


def test_sqlalchemy_engine_can_execute_sqlite_smoke_query() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")

    with engine.connect() as connection:
        result = connection.execute(text("select 1")).scalar_one()

    assert result == 1


def test_declarative_base_metadata_is_available() -> None:
    expected_tables = {
        "brand_aliases",
        "brands",
        "concern_aliases",
        "concern_effects",
        "concerns",
        "effect_aliases",
        "effects",
        "ingredient_effects",
        "ingredient_evidence",
        "ingredients",
        "product_categories",
        "product_category_aliases",
        "product_images",
        "product_ingredients",
        "product_prices",
        "product_skin_profiles",
        "products",
        "recommendation_results",
        "recommendation_run_concerns",
        "recommendation_run_constraints",
        "recommendation_runs",
        "recommendation_score_evidence",
        "risk_flags",
        "search_candidates",
        "search_documents",
    }

    assert set(Base.metadata.tables) == expected_tables


def test_mvp_schema_contains_hard_filter_and_search_columns() -> None:
    products = Base.metadata.tables["products"]
    recommendation_run_constraints = Base.metadata.tables["recommendation_run_constraints"]
    search_documents = Base.metadata.tables["search_documents"]
    recommendation_results = Base.metadata.tables["recommendation_results"]

    assert {"brand_id", "category_id"}.issubset(products.columns.keys())
    assert {"brand_id", "category_id", "numeric_value", "is_hard"}.issubset(
        recommendation_run_constraints.columns.keys()
    )
    assert {
        "product_id",
        "ingredient_id",
        "ingredient_evidence_id",
        "embedding_model",
        "embedding_dimensions",
        "embedding_updated_at",
    }.issubset(
        search_documents.columns.keys()
    )
    assert "score_breakdown" in recommendation_results.columns.keys()


def test_mvp_schema_can_create_all_with_sqlite() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    with engine.connect() as connection:
        result = connection.execute(
            text("select name from sqlite_master where type = 'table' and name = 'products'")
        ).scalar_one()

    assert result == "products"


def test_alembic_config_points_to_migrations() -> None:
    config = Config("alembic.ini")
    script_location = config.get_main_option("script_location")

    assert script_location is not None
    assert Path(script_location).name == "migrations"


def test_settings_exposes_database_url() -> None:
    assert settings.database_url
