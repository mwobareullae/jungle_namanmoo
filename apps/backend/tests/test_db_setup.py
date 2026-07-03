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
        "auth_accounts",
        "brand_aliases",
        "brands",
        "concern_aliases",
        "concern_effects",
        "concerns",
        "effect_aliases",
        "effects",
        "ingredient_aliases",
        "ingredient_effects",
        "ingredient_effect_ranges",
        "ingredient_evidence",
        "ingredients",
        "inventories",
        "inventory_movements",
        "password_reset_tokens",
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
        "refresh_tokens",
        "risk_flags",
        "search_candidates",
        "search_documents",
        "sellers",
        "users",
    }

    assert set(Base.metadata.tables) == expected_tables


def test_mvp_schema_contains_hard_filter_and_search_columns() -> None:
    products = Base.metadata.tables["products"]
    recommendation_run_constraints = Base.metadata.tables["recommendation_run_constraints"]
    search_documents = Base.metadata.tables["search_documents"]
    recommendation_results = Base.metadata.tables["recommendation_results"]
    ingredient_aliases = Base.metadata.tables["ingredient_aliases"]
    ingredient_evidence = Base.metadata.tables["ingredient_evidence"]
    product_images = Base.metadata.tables["product_images"]
    risk_flags = Base.metadata.tables["risk_flags"]
    inventories = Base.metadata.tables["inventories"]
    users = Base.metadata.tables["users"]
    auth_accounts = Base.metadata.tables["auth_accounts"]
    refresh_tokens = Base.metadata.tables["refresh_tokens"]
    password_reset_tokens = Base.metadata.tables["password_reset_tokens"]

    assert {"seller_id", "brand_id", "category_id"}.issubset(products.columns.keys())
    assert {
        "functional_review_text",
        "functional_cosmetic_status",
        "functional_cosmetic_claims",
        "functional_claim_confidence",
        "functional_claim_basis",
    }.issubset(products.columns.keys())
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
    assert {"ingredient_id", "alias", "normalized_alias", "alias_type", "confidence", "source"}.issubset(
        ingredient_aliases.columns.keys()
    )
    assert {"image_type", "storage_key", "display_order"}.issubset(product_images.columns.keys())
    assert "image_url" not in product_images.columns.keys()
    assert {"source_type", "pmid", "doi", "source_authority_score"}.issubset(
        ingredient_evidence.columns.keys()
    )
    assert {"severity_score", "applies_to", "condition", "source_type"}.issubset(risk_flags.columns.keys())
    assert {"product_id", "stock_quantity", "reserved_quantity", "safety_stock", "sales_status"}.issubset(
        inventories.columns.keys()
    )
    assert {"email", "display_name", "phone", "status", "role", "last_login_at"}.issubset(users.columns.keys())
    assert {
        "user_id",
        "provider",
        "provider_account_id",
        "provider_email",
        "password_hash",
        "is_verified",
    }.issubset(auth_accounts.columns.keys())
    assert {"user_id", "token_hash", "family_id", "expires_at", "revoked_at"}.issubset(
        refresh_tokens.columns.keys()
    )
    assert {"user_id", "token_hash", "requested_email", "expires_at", "used_at"}.issubset(
        password_reset_tokens.columns.keys()
    )


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
