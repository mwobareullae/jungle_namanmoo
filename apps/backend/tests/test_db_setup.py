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
        "agent_tool_calls",
        "auth_accounts",
        "auth_sessions",
        "baumann_type_profiles",
        "brand_aliases",
        "brands",
        "cart_items",
        "carts",
        "concern_aliases",
        "concern_effects",
        "concerns",
        "effect_aliases",
        "effects",
        "evidence_discovery_candidates",
        "evidence_discovery_reviews",
        "event_logs",
        "ingredient_aliases",
        "ingredient_effects",
        "ingredient_effect_ranges",
        "ingredient_evidence",
        "ingredients",
        "inventories",
        "inventory_movements",
        "order_items",
        "order_shipping_addresses",
        "order_shipping_groups",
        "orders",
        "password_reset_tokens",
            "payment_events",
            "payment_attempts",
            "payments",
        "product_categories",
        "product_category_aliases",
        "product_images",
        "product_ingredients",
        "product_popularity_metrics",
        "product_prices",
        "product_review_metrics",
        "product_review_profile_labels",
        "product_review_segment_metrics",
        "product_reviews",
        "product_skin_profiles",
        "products",
        "recommendation_results",
        "recommendation_run_concerns",
        "recommendation_run_constraints",
        "recommendation_runs",
        "recommendation_score_evidence",
        "recent_views",
        "refresh_tokens",
        "risk_flags",
            "search_candidates",
            "search_documents",
            "sellers",
            "seller_shipping_policies",
            "skin_profiles",
        "skin_test_answers",
        "skin_test_options",
        "skin_test_questions",
        "skin_test_results",
        "skin_test_versions",
        "terms_versions",
        "user_addresses",
        "user_consents",
        "users",
        "wishlists",
    }

    assert set(Base.metadata.tables) == expected_tables


def test_mvp_schema_contains_hard_filter_and_search_columns() -> None:
    products = Base.metadata.tables["products"]
    recommendation_run_constraints = Base.metadata.tables["recommendation_run_constraints"]
    search_documents = Base.metadata.tables["search_documents"]
    recommendation_results = Base.metadata.tables["recommendation_results"]
    ingredient_aliases = Base.metadata.tables["ingredient_aliases"]
    ingredient_evidence = Base.metadata.tables["ingredient_evidence"]
    evidence_discovery_candidates = Base.metadata.tables["evidence_discovery_candidates"]
    evidence_discovery_reviews = Base.metadata.tables["evidence_discovery_reviews"]
    product_images = Base.metadata.tables["product_images"]
    product_popularity_metrics = Base.metadata.tables["product_popularity_metrics"]
    product_reviews = Base.metadata.tables["product_reviews"]
    product_review_profile_labels = Base.metadata.tables["product_review_profile_labels"]
    product_review_metrics = Base.metadata.tables["product_review_metrics"]
    product_review_segment_metrics = Base.metadata.tables["product_review_segment_metrics"]
    wishlists = Base.metadata.tables["wishlists"]
    recent_views = Base.metadata.tables["recent_views"]
    carts = Base.metadata.tables["carts"]
    cart_items = Base.metadata.tables["cart_items"]
    risk_flags = Base.metadata.tables["risk_flags"]
    inventories = Base.metadata.tables["inventories"]
    seller_shipping_policies = Base.metadata.tables["seller_shipping_policies"]
    user_addresses = Base.metadata.tables["user_addresses"]
    orders = Base.metadata.tables["orders"]
    order_items = Base.metadata.tables["order_items"]
    order_shipping_addresses = Base.metadata.tables["order_shipping_addresses"]
    order_shipping_groups = Base.metadata.tables["order_shipping_groups"]
    payments = Base.metadata.tables["payments"]
    payment_events = Base.metadata.tables["payment_events"]
    event_logs = Base.metadata.tables["event_logs"]
    agent_tool_calls = Base.metadata.tables["agent_tool_calls"]
    users = Base.metadata.tables["users"]
    auth_accounts = Base.metadata.tables["auth_accounts"]
    auth_sessions = Base.metadata.tables["auth_sessions"]
    refresh_tokens = Base.metadata.tables["refresh_tokens"]
    password_reset_tokens = Base.metadata.tables["password_reset_tokens"]
    terms_versions = Base.metadata.tables["terms_versions"]
    user_consents = Base.metadata.tables["user_consents"]
    skin_profiles = Base.metadata.tables["skin_profiles"]
    skin_test_results = Base.metadata.tables["skin_test_results"]
    skin_test_answers = Base.metadata.tables["skin_test_answers"]
    baumann_type_profiles = Base.metadata.tables["baumann_type_profiles"]

    assert {"seller_id", "brand_id", "category_id"}.issubset(products.columns.keys())
    assert {
        "functional_review_text",
        "functional_cosmetic_status",
        "functional_cosmetic_claims",
        "functional_claim_confidence",
        "functional_claim_basis",
        "is_recommendable",
        "recommend_exclude_reason",
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
    assert {
        "product_id",
        "window_days",
        "view_count",
        "click_count",
        "cart_add_count",
        "order_count",
        "units_sold",
        "wishlist_add_count",
        "checkout_start_count",
        "paid_order_count",
        "home_product_impression_count",
        "home_product_click_count",
        "search_result_impression_count",
        "search_result_click_count",
        "wishlist_remove_count",
        "cart_remove_count",
        "cart_quantity_change_count",
        "payment_failed_count",
        "order_cancel_count",
        "review_count",
        "average_rating",
        "popularity_score",
        "score_version",
        "computed_at",
    }.issubset(product_popularity_metrics.columns.keys())
    assert {
        "review_code",
        "product_id",
        "user_id",
        "order_item_id",
        "parent_review_id",
        "source",
        "source_review_id",
        "status",
        "review_type",
        "rating",
        "review_text",
        "reviewed_at",
        "is_repurchase_review",
        "verified_purchase",
        "helpful_count",
        "source_has_photo",
        "source_content_hash",
        "profile_mapping_version",
    }.issubset(product_reviews.columns.keys())
    assert {
        "review_id",
        "dimension",
        "value_code",
        "source_label",
        "mapping_source",
        "mapping_confidence",
    }.issubset(product_review_profile_labels.columns.keys())
    assert {
        "product_id",
        "review_count",
        "average_rating",
        "bayesian_rating",
        "rating_effective_sample_size",
        "repurchase_effective_sample_size",
        "month_use_effective_sample_size",
        "confidence",
        "review_quality_score",
        "score_version",
        "computed_at",
    }.issubset(product_review_metrics.columns.keys())
    assert {
        "product_id",
        "dimension",
        "value_code",
        "review_count",
        "bayesian_rating",
        "effective_sample_size",
        "rating_affinity_score",
        "repurchase_affinity_score",
        "total_affinity_score",
        "score_version",
    }.issubset(product_review_segment_metrics.columns.keys())
    assert {"user_id", "product_id", "added_at"}.issubset(wishlists.columns.keys())
    assert {"user_id", "product_id", "viewed_at", "updated_at"}.issubset(recent_views.columns.keys())
    assert {"user_id", "anonymous_cart_id", "status", "expires_at", "merged_into_cart_id"}.issubset(
        carts.columns.keys()
    )
    assert {
        "cart_id",
        "product_id",
        "seller_id",
        "quantity",
        "unit_price_snapshot",
        "currency",
        "source",
        "recommendation_id",
        "recommendation_rank",
    }.issubset(cart_items.columns.keys())
    assert {
        "source_type",
        "pmid",
        "doi",
        "source_authority_score",
        "canonical_evidence_key",
        "review_status",
        "result_direction",
        "score_use_level",
        "is_representative",
        "representative_rank",
        "is_current",
        "review_note",
        "reviewed_by",
        "reviewed_at",
    }.issubset(
        ingredient_evidence.columns.keys()
    )
    assert {
        "discovery_key",
        "ingredient_id",
        "effect_id",
        "paper_key",
        "pmid",
        "doi",
        "title",
        "publication_date_text",
        "first_seen_at",
        "last_seen_at",
        "review_status",
        "review_note",
        "reviewed_by_user_id",
        "promoted_evidence_id",
    }.issubset(evidence_discovery_candidates.columns.keys())
    assert {
        "candidate_id",
        "previous_status",
        "new_status",
        "reviewer_user_id",
        "note",
        "promoted_evidence_id",
        "created_at",
    }.issubset(evidence_discovery_reviews.columns.keys())
    assert {"severity_score", "applies_to", "condition", "source_type"}.issubset(risk_flags.columns.keys())
    assert {"product_id", "stock_quantity", "reserved_quantity", "safety_stock", "sales_status"}.issubset(
        inventories.columns.keys()
    )
    assert {"seller_id", "policy_name", "base_shipping_fee", "free_shipping_threshold", "is_active"}.issubset(
        seller_shipping_policies.columns.keys()
    )
    assert {
        "user_id",
        "recipient_name",
        "phone",
        "postal_code",
        "address1",
        "address2",
        "delivery_memo",
        "is_default",
    }.issubset(user_addresses.columns.keys())
    assert {
        "order_code",
        "user_id",
        "cart_id",
        "idempotency_key",
        "status",
        "subtotal_amount",
        "shipping_fee",
        "discount_amount",
        "total_amount",
        "currency",
        "item_count",
        "total_quantity",
        "payment_expires_at",
    }.issubset(orders.columns.keys())
    assert {
        "order_id",
        "cart_item_id",
        "product_id",
        "seller_id",
        "product_name_snapshot",
        "brand_name_snapshot",
        "seller_name_snapshot",
        "thumbnail_storage_key_snapshot",
        "unit_price",
        "quantity",
        "line_subtotal",
        "line_discount_amount",
        "line_total",
        "status",
        "recommendation_id",
        "recommendation_rank",
        "source",
    }.issubset(order_items.columns.keys())
    assert {
        "order_id",
        "user_address_id",
        "recipient_name",
        "phone",
        "postal_code",
        "address1",
        "address2",
        "delivery_memo",
    }.issubset(order_shipping_addresses.columns.keys())
    assert {
        "order_id",
        "seller_id",
        "seller_name_snapshot",
        "item_subtotal",
        "shipping_fee",
        "free_shipping_threshold_snapshot",
        "shipping_policy_snapshot_json",
    }.issubset(order_shipping_groups.columns.keys())
    assert {
        "payment_code",
        "order_id",
        "provider",
        "status",
        "amount",
        "currency",
        "provider_payment_key",
        "provider_order_id",
    }.issubset(payments.columns.keys())
    assert {
        "payment_id",
        "order_id",
        "event_type",
        "event_id",
        "provider",
        "provider_payment_key",
        "provider_order_id",
        "amount",
        "status_before",
        "status_after",
        "raw_payload_json",
    }.issubset(payment_events.columns.keys())
    assert {
        "event_id",
        "event_name",
        "occurred_at",
        "user_id",
        "anonymous_user_id",
        "session_id",
        "request_id",
        "recommendation_id",
        "product_id",
        "rank",
        "source",
        "page",
        "cart_id",
        "order_id",
        "metadata_json",
    }.issubset(event_logs.columns.keys())
    assert {
        "tool_call_id",
        "conversation_id",
        "user_id",
        "anonymous_user_id",
        "session_id",
        "request_id",
        "tool_name",
        "status",
        "confirmation_required",
        "confirmed_at",
        "executed_at",
        "expires_at",
        "input_json",
        "output_json",
        "error_code",
        "error_message",
        "latency_ms",
    }.issubset(agent_tool_calls.columns.keys())
    assert {"email", "display_name", "phone", "status", "role", "last_login_at"}.issubset(users.columns.keys())
    assert {
        "user_id",
        "provider",
        "provider_account_id",
        "provider_email",
        "password_hash",
        "is_verified",
    }.issubset(auth_accounts.columns.keys())
    assert {"user_id", "token_hash", "expires_at", "revoked_at", "last_used_at"}.issubset(
        auth_sessions.columns.keys()
    )
    assert {"user_id", "token_hash", "family_id", "expires_at", "revoked_at"}.issubset(
        refresh_tokens.columns.keys()
    )
    assert {
        "user_id",
        "token_hash",
        "requested_email",
        "expires_at",
        "used_at",
        "failed_attempt_count",
        "last_attempt_at",
    }.issubset(password_reset_tokens.columns.keys())
    assert {"terms_key", "version", "title", "is_required", "is_active"}.issubset(
        terms_versions.columns.keys()
    )
    assert {"user_id", "terms_version_id", "consent_key", "agreed", "consented_at"}.issubset(
        user_consents.columns.keys()
    )
    assert {"type_code", "title", "subtitle", "image_storage_key", "keywords"}.issubset(
        baumann_type_profiles.columns.keys()
    )
    assert {
        "user_id",
        "skin_type",
        "sensitivity",
        "explicit_skin_type",
        "explicit_sensitivity",
        "baumann_type_code",
        "baumann_signal_weight",
        "latest_skin_test_result_id",
    }.issubset(skin_profiles.columns.keys())
    assert {
        "result_code",
        "user_id",
        "version_id",
        "type_code",
        "mapped_skin_type",
        "mapped_sensitivity",
        "axis_scores",
        "commerce_profile",
        "applied_profile_id",
    }.issubset(skin_test_results.columns.keys())
    assert {"result_id", "version_id", "question_id", "option_id", "answer_order"}.issubset(
        skin_test_answers.columns.keys()
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


def test_settings_exposes_dev_infra_urls() -> None:
    assert settings.redis_url
    assert settings.redis_key_prefix
    assert settings.search_backend_mode in {"auto", "postgres", "elasticsearch"}
    assert settings.elasticsearch_url
    assert settings.elasticsearch_index_prefix
    assert settings.elasticsearch_products_alias
    assert settings.elasticsearch_catalog_products_alias
    assert settings.elasticsearch_timeout_seconds > 0
    assert settings.elasticsearch_max_retries >= 0
    assert settings.elasticsearch_circuit_breaker_seconds > 0
