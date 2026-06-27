"""create mvp schema

Revision ID: 20260627_0001
Revises:
Create Date: 2026-06-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260627_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("brand_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_code"),
    )
    op.create_table(
        "product_categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["product_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_code"),
    )
    op.create_index("ix_product_categories_parent_id", "product_categories", ["parent_id"])

    op.create_table(
        "brand_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("normalized_alias", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "normalized_alias", name="uq_brand_aliases_brand_normalized_alias"),
    )
    op.create_index("ix_brand_aliases_brand_id", "brand_aliases", ["brand_id"])
    op.create_table(
        "product_category_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("normalized_alias", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "category_id",
            "normalized_alias",
            name="uq_product_category_aliases_category_normalized_alias",
        ),
    )
    op.create_index("ix_product_category_aliases_category_id", "product_category_aliases", ["category_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("skin_type_tags", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_code"),
    )
    op.create_index("ix_products_brand_id", "products", ["brand_id"])
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_table(
        "product_images",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])
    op.create_table(
        "product_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("mall_name", sa.String(length=80), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("product_url", sa.Text(), nullable=False),
        sa.Column("is_lowest", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_prices_product_id", "product_prices", ["product_id"])

    op.create_table(
        "concerns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("concern_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concern_code"),
    )
    op.create_table(
        "effects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("effect_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("effect_code"),
    )
    op.create_table(
        "ingredients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_code", sa.String(length=64), nullable=False),
        sa.Column("name_ko", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=160), nullable=True),
        sa.Column("normalized_name", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingredient_code"),
    )

    op.create_table(
        "concern_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("concern_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("normalized_alias", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["concern_id"], ["concerns.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concern_id", "normalized_alias", name="uq_concern_aliases_concern_normalized_alias"),
    )
    op.create_index("ix_concern_aliases_concern_id", "concern_aliases", ["concern_id"])
    op.create_table(
        "effect_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("normalized_alias", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("effect_id", "normalized_alias", name="uq_effect_aliases_effect_normalized_alias"),
    )
    op.create_index("ix_effect_aliases_effect_id", "effect_aliases", ["effect_id"])
    op.create_table(
        "concern_effects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("concern_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("weight", sa.Numeric(5, 4), server_default="1.0", nullable=False),
        sa.ForeignKeyConstraint(["concern_id"], ["concerns.id"]),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concern_id", "effect_id", name="uq_concern_effects_concern_effect"),
    )
    op.create_index("ix_concern_effects_concern_id", "concern_effects", ["concern_id"])
    op.create_index("ix_concern_effects_effect_id", "concern_effects", ["effect_id"])
    op.create_table(
        "ingredient_effects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_score", sa.Numeric(6, 2), server_default="0.0", nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingredient_id", "effect_id", name="uq_ingredient_effects_ingredient_effect"),
    )
    op.create_index("ix_ingredient_effects_effect_id", "ingredient_effects", ["effect_id"])
    op.create_index("ix_ingredient_effects_ingredient_id", "ingredient_effects", ["ingredient_id"])
    op.create_table(
        "ingredient_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_level", sa.String(length=40), nullable=True),
        sa.Column("evidence_score", sa.Numeric(6, 2), server_default="0.0", nullable=False),
        sa.Column("source_title", sa.String(length=240), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingredient_evidence_effect_id", "ingredient_evidence", ["effect_id"])
    op.create_index("ix_ingredient_evidence_ingredient_id", "ingredient_evidence", ["ingredient_id"])
    op.create_table(
        "product_ingredients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_name", sa.String(length=160), nullable=True),
        sa.Column("content_confidence", sa.String(length=40), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("concentration_text", sa.String(length=80), nullable=True),
        sa.Column("concentration_value", sa.Numeric(8, 4), nullable=True),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "ingredient_id", name="uq_product_ingredients_product_ingredient"),
    )
    op.create_index("ix_product_ingredients_ingredient_id", "product_ingredients", ["ingredient_id"])
    op.create_index("ix_product_ingredients_product_id", "product_ingredients", ["product_id"])
    op.create_table(
        "risk_flags",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("risk_type", sa.String(length=80), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_flags_ingredient_id", "risk_flags", ["ingredient_id"])

    op.create_table(
        "search_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_code", sa.String(length=80), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("ingredient_evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ingredient_evidence_id"], ["ingredient_evidence.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_code"),
    )
    op.create_index("ix_search_documents_document_type", "search_documents", ["document_type"])
    op.create_index("ix_search_documents_ingredient_evidence_id", "search_documents", ["ingredient_evidence_id"])
    op.create_index("ix_search_documents_ingredient_id", "search_documents", ["ingredient_id"])
    op.create_index("ix_search_documents_product_id", "search_documents", ["product_id"])

    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_code", sa.String(length=80), nullable=False),
        sa.Column("concern_text", sa.Text(), nullable=False),
        sa.Column("skin_type", sa.String(length=40), server_default="중성", nullable=False),
        sa.Column("sensitivity", sa.String(length=40), server_default="보통", nullable=False),
        sa.Column("avoid_ingredients", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parser_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scoring_version", sa.String(length=40), server_default="v0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_code"),
    )
    op.create_table(
        "recommendation_run_concerns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("concern_id", sa.BigInteger(), nullable=False),
        sa.Column("matched_text", sa.String(length=120), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.ForeignKeyConstraint(["concern_id"], ["concerns.id"]),
        sa.ForeignKeyConstraint(["recommendation_run_id"], ["recommendation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_run_id",
            "concern_id",
            name="uq_recommendation_run_concerns_run_concern",
        ),
    )
    op.create_index("ix_recommendation_run_concerns_concern_id", "recommendation_run_concerns", ["concern_id"])
    op.create_index(
        "ix_recommendation_run_concerns_recommendation_run_id",
        "recommendation_run_concerns",
        ["recommendation_run_id"],
    )
    op.create_table(
        "recommendation_run_constraints",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("constraint_type", sa.String(length=40), nullable=False),
        sa.Column("operator", sa.String(length=20), nullable=False),
        sa.Column("raw_text", sa.String(length=120), nullable=True),
        sa.Column("normalized_value", sa.String(length=120), nullable=True),
        sa.Column("brand_id", sa.BigInteger(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("numeric_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_hard", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"]),
        sa.ForeignKeyConstraint(["recommendation_run_id"], ["recommendation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_run_constraints_brand_id", "recommendation_run_constraints", ["brand_id"])
    op.create_index("ix_recommendation_run_constraints_category_id", "recommendation_run_constraints", ["category_id"])
    op.create_index(
        "ix_recommendation_run_constraints_constraint_type",
        "recommendation_run_constraints",
        ["constraint_type"],
    )
    op.create_index(
        "ix_recommendation_run_constraints_recommendation_run_id",
        "recommendation_run_constraints",
        ["recommendation_run_id"],
    )
    op.create_table(
        "search_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword_score", sa.Numeric(6, 4), server_default="0.0", nullable=False),
        sa.Column("vector_score", sa.Numeric(6, 4), server_default="0.0", nullable=False),
        sa.Column("search_match_score", sa.Numeric(6, 4), server_default="0.0", nullable=False),
        sa.Column("rank_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["recommendation_run_id"], ["recommendation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_run_id", "product_id", name="uq_search_candidates_run_product"),
    )
    op.create_index("ix_search_candidates_product_id", "search_candidates", ["product_id"])
    op.create_index("ix_search_candidates_recommendation_run_id", "search_candidates", ["recommendation_run_id"])
    op.create_table(
        "recommendation_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("rank_order", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=True),
        sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["recommendation_run_id"], ["recommendation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_run_id", "product_id", name="uq_recommendation_results_run_product"),
        sa.UniqueConstraint("recommendation_run_id", "rank_order", name="uq_recommendation_results_run_rank"),
    )
    op.create_index("ix_recommendation_results_product_id", "recommendation_results", ["product_id"])
    op.create_index("ix_recommendation_results_recommendation_run_id", "recommendation_results", ["recommendation_run_id"])
    op.create_table(
        "recommendation_score_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recommendation_result_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("effect_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("contribution_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["ingredient_evidence.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["recommendation_result_id"], ["recommendation_results.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_score_evidence_effect_id", "recommendation_score_evidence", ["effect_id"])
    op.create_index("ix_recommendation_score_evidence_evidence_id", "recommendation_score_evidence", ["evidence_id"])
    op.create_index("ix_recommendation_score_evidence_ingredient_id", "recommendation_score_evidence", ["ingredient_id"])
    op.create_index(
        "ix_recommendation_score_evidence_recommendation_result_id",
        "recommendation_score_evidence",
        ["recommendation_result_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendation_score_evidence_recommendation_result_id", table_name="recommendation_score_evidence")
    op.drop_index("ix_recommendation_score_evidence_ingredient_id", table_name="recommendation_score_evidence")
    op.drop_index("ix_recommendation_score_evidence_evidence_id", table_name="recommendation_score_evidence")
    op.drop_index("ix_recommendation_score_evidence_effect_id", table_name="recommendation_score_evidence")
    op.drop_table("recommendation_score_evidence")
    op.drop_index("ix_recommendation_results_recommendation_run_id", table_name="recommendation_results")
    op.drop_index("ix_recommendation_results_product_id", table_name="recommendation_results")
    op.drop_table("recommendation_results")
    op.drop_index("ix_search_candidates_recommendation_run_id", table_name="search_candidates")
    op.drop_index("ix_search_candidates_product_id", table_name="search_candidates")
    op.drop_table("search_candidates")
    op.drop_index("ix_recommendation_run_constraints_recommendation_run_id", table_name="recommendation_run_constraints")
    op.drop_index("ix_recommendation_run_constraints_constraint_type", table_name="recommendation_run_constraints")
    op.drop_index("ix_recommendation_run_constraints_category_id", table_name="recommendation_run_constraints")
    op.drop_index("ix_recommendation_run_constraints_brand_id", table_name="recommendation_run_constraints")
    op.drop_table("recommendation_run_constraints")
    op.drop_index("ix_recommendation_run_concerns_recommendation_run_id", table_name="recommendation_run_concerns")
    op.drop_index("ix_recommendation_run_concerns_concern_id", table_name="recommendation_run_concerns")
    op.drop_table("recommendation_run_concerns")
    op.drop_table("recommendation_runs")
    op.drop_index("ix_search_documents_product_id", table_name="search_documents")
    op.drop_index("ix_search_documents_ingredient_id", table_name="search_documents")
    op.drop_index("ix_search_documents_ingredient_evidence_id", table_name="search_documents")
    op.drop_index("ix_search_documents_document_type", table_name="search_documents")
    op.drop_table("search_documents")
    op.drop_index("ix_risk_flags_ingredient_id", table_name="risk_flags")
    op.drop_table("risk_flags")
    op.drop_index("ix_product_ingredients_product_id", table_name="product_ingredients")
    op.drop_index("ix_product_ingredients_ingredient_id", table_name="product_ingredients")
    op.drop_table("product_ingredients")
    op.drop_index("ix_ingredient_evidence_ingredient_id", table_name="ingredient_evidence")
    op.drop_index("ix_ingredient_evidence_effect_id", table_name="ingredient_evidence")
    op.drop_table("ingredient_evidence")
    op.drop_index("ix_ingredient_effects_ingredient_id", table_name="ingredient_effects")
    op.drop_index("ix_ingredient_effects_effect_id", table_name="ingredient_effects")
    op.drop_table("ingredient_effects")
    op.drop_index("ix_concern_effects_effect_id", table_name="concern_effects")
    op.drop_index("ix_concern_effects_concern_id", table_name="concern_effects")
    op.drop_table("concern_effects")
    op.drop_index("ix_effect_aliases_effect_id", table_name="effect_aliases")
    op.drop_table("effect_aliases")
    op.drop_index("ix_concern_aliases_concern_id", table_name="concern_aliases")
    op.drop_table("concern_aliases")
    op.drop_table("ingredients")
    op.drop_table("effects")
    op.drop_table("concerns")
    op.drop_index("ix_product_prices_product_id", table_name="product_prices")
    op.drop_table("product_prices")
    op.drop_index("ix_product_images_product_id", table_name="product_images")
    op.drop_table("product_images")
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_index("ix_products_brand_id", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_product_category_aliases_category_id", table_name="product_category_aliases")
    op.drop_table("product_category_aliases")
    op.drop_index("ix_brand_aliases_brand_id", table_name="brand_aliases")
    op.drop_table("brand_aliases")
    op.drop_index("ix_product_categories_parent_id", table_name="product_categories")
    op.drop_table("product_categories")
    op.drop_table("brands")
