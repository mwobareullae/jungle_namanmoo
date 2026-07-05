"""add skin profile and test tables

Revision ID: 20260704_0014
Revises: 20260704_0013
Create Date: 2026-07-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260704_0014"
down_revision: str | None = "20260704_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "baumann_type_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type_code", sa.String(length=4), nullable=False),
        sa.Column("object_name", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mapped_skin_type", sa.String(length=40), nullable=False),
        sa.Column("mapped_sensitivity", sa.String(length=40), nullable=False),
        sa.Column("concern_tags", JSONB, nullable=True),
        sa.Column("recommended_effect_ids", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("avoid_hints", JSONB, nullable=True),
        sa.Column("keywords", JSONB, nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(type_code)) = 4", name="ck_baumann_type_profiles_type_code_length"),
        sa.CheckConstraint(
            "mapped_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_baumann_mapped_skin_type",
        ),
        sa.CheckConstraint(
            "mapped_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_baumann_mapped_sensitivity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("type_code"),
    )

    op.create_table(
        "skin_test_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('draft', 'active', 'archived')", name="ck_skin_test_versions_status"),
        sa.CheckConstraint("question_count > 0", name="ck_skin_test_versions_question_count_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_code"),
    )

    op.create_table(
        "skin_test_questions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("question_key", sa.String(length=40), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("axis", sa.String(length=40), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("helper_text", sa.Text(), nullable=True),
        sa.Column("skip_conditions", JSONB, nullable=True),
        sa.Column("is_required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "axis in ('OD', 'SR', 'PN', 'WT', 'CATEGORY_PREF', 'BUYING_CRITERIA', 'PRICE_PREF', 'TRIGGER_PREF')",
            name="ck_skin_test_questions_axis",
        ),
        sa.ForeignKeyConstraint(["version_id"], ["skin_test_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "question_key", name="uq_skin_test_questions_version_key"),
        sa.UniqueConstraint("version_id", "sequence", name="uq_skin_test_questions_version_sequence"),
        sa.UniqueConstraint("id", "version_id", name="uq_skin_test_questions_id_version"),
    )
    op.create_index("ix_skin_test_questions_version_id", "skin_test_questions", ["version_id"])

    op.create_table(
        "skin_test_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("option_key", sa.String(length=20), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("internal_label", sa.String(length=120), nullable=True),
        sa.Column("axis_value", sa.String(length=20), nullable=True),
        sa.Column("score_delta", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("commerce_mapping", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["skin_test_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "option_key", name="uq_skin_test_options_question_key"),
        sa.UniqueConstraint("question_id", "display_order", name="uq_skin_test_options_question_order"),
        sa.UniqueConstraint("id", "question_id", name="uq_skin_test_options_id_question"),
    )
    op.create_index("ix_skin_test_options_question_id", "skin_test_options", ["question_id"])

    op.create_table(
        "skin_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_id", sa.String(length=100), nullable=True),
        sa.Column("skin_type", sa.String(length=40), server_default="중성", nullable=False),
        sa.Column("sensitivity", sa.String(length=40), server_default="보통", nullable=False),
        sa.Column("skin_type_source", sa.String(length=40), server_default="manual", nullable=False),
        sa.Column("sensitivity_source", sa.String(length=40), server_default="manual", nullable=False),
        sa.Column("skin_type_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("sensitivity_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("explicit_skin_type", sa.String(length=40), nullable=True),
        sa.Column("explicit_sensitivity", sa.String(length=40), nullable=True),
        sa.Column("avoid_ingredients", JSONB, nullable=True),
        sa.Column("baumann_type_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("baumann_type_code", sa.String(length=4), nullable=True),
        sa.Column("baumann_inferred_skin_type", sa.String(length=40), nullable=True),
        sa.Column("baumann_inferred_sensitivity", sa.String(length=40), nullable=True),
        sa.Column("baumann_signal_weight", sa.Numeric(5, 4), server_default="0.2500", nullable=False),
        sa.Column("latest_skin_test_result_id", sa.BigInteger(), nullable=True),
        sa.Column("commerce_profile", JSONB, nullable=True),
        sa.Column("concern_profile_json", JSONB, nullable=True),
        sa.Column("source", sa.String(length=40), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("skin_type in ('건성', '지성', '복합성', '중성', '수부지')", name="ck_skin_profiles_skin_type"),
        sa.CheckConstraint("sensitivity in ('낮음', '보통', '높음', '민감')", name="ck_skin_profiles_sensitivity"),
        sa.CheckConstraint(
            "explicit_skin_type is null or explicit_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_profiles_explicit_skin_type",
        ),
        sa.CheckConstraint(
            "explicit_sensitivity is null or explicit_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_profiles_explicit_sensitivity",
        ),
        sa.CheckConstraint(
            "baumann_inferred_skin_type is null or baumann_inferred_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_profiles_baumann_skin_type",
        ),
        sa.CheckConstraint(
            "baumann_inferred_sensitivity is null or baumann_inferred_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_profiles_baumann_sensitivity",
        ),
        sa.CheckConstraint("source in ('manual', 'skin_test', 'mixed', 'import')", name="ck_skin_profiles_source"),
        sa.CheckConstraint(
            "baumann_signal_weight >= 0 and baumann_signal_weight <= 1",
            name="ck_skin_profiles_baumann_signal_weight",
        ),
        sa.ForeignKeyConstraint(["baumann_type_profile_id"], ["baumann_type_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_skin_profiles_user_id"),
    )
    op.create_index("ix_skin_profiles_anonymous_id", "skin_profiles", ["anonymous_id"])
    op.create_index("ix_skin_profiles_baumann_type_profile_id", "skin_profiles", ["baumann_type_profile_id"])
    op.create_index("ix_skin_profiles_latest_skin_test_result_id", "skin_profiles", ["latest_skin_test_result_id"])
    op.create_index("ix_skin_profiles_user_id", "skin_profiles", ["user_id"])

    op.create_table(
        "skin_test_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("result_code", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_id", sa.String(length=100), nullable=True),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("baumann_type_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("type_code", sa.String(length=4), nullable=False),
        sa.Column("mapped_skin_type", sa.String(length=40), nullable=False),
        sa.Column("mapped_sensitivity", sa.String(length=40), nullable=False),
        sa.Column("axis_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("commerce_profile", JSONB, nullable=True),
        sa.Column("recommended_effect_ids", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("avoid_hints", JSONB, nullable=True),
        sa.Column("raw_score_payload", JSONB, nullable=True),
        sa.Column("applied_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("applied_weight", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(type_code)) = 4", name="ck_skin_test_results_type_code_length"),
        sa.CheckConstraint(
            "mapped_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_test_results_mapped_skin_type",
        ),
        sa.CheckConstraint(
            "mapped_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_test_results_mapped_sensitivity",
        ),
        sa.CheckConstraint(
            "applied_weight is null or (applied_weight >= 0 and applied_weight <= 1)",
            name="ck_skin_test_results_applied_weight",
        ),
        sa.ForeignKeyConstraint(["applied_profile_id"], ["skin_profiles.id"]),
        sa.ForeignKeyConstraint(["baumann_type_profile_id"], ["baumann_type_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["skin_test_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_code", name="uq_skin_test_results_result_code"),
        sa.UniqueConstraint("id", "version_id", name="uq_skin_test_results_id_version"),
    )
    op.create_index("ix_skin_test_results_anonymous_id", "skin_test_results", ["anonymous_id"])
    op.create_index("ix_skin_test_results_applied_profile_id", "skin_test_results", ["applied_profile_id"])
    op.create_index("ix_skin_test_results_baumann_type_profile_id", "skin_test_results", ["baumann_type_profile_id"])
    op.create_index("ix_skin_test_results_user_id", "skin_test_results", ["user_id"])
    op.create_index("ix_skin_test_results_version_id", "skin_test_results", ["version_id"])

    op.create_table(
        "skin_test_answers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("result_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("option_id", sa.BigInteger(), nullable=False),
        sa.Column("answer_order", sa.Integer(), nullable=False),
        sa.Column("question_snapshot", JSONB, nullable=True),
        sa.Column("option_snapshot", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["option_id", "question_id"],
            ["skin_test_options.id", "skin_test_options.question_id"],
            name="fk_skin_test_answers_option_question",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "version_id"],
            ["skin_test_questions.id", "skin_test_questions.version_id"],
            name="fk_skin_test_answers_question_version",
        ),
        sa.ForeignKeyConstraint(
            ["result_id", "version_id"],
            ["skin_test_results.id", "skin_test_results.version_id"],
            name="fk_skin_test_answers_result_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_id", "answer_order", name="uq_skin_test_answers_result_order"),
        sa.UniqueConstraint("result_id", "question_id", name="uq_skin_test_answers_result_question"),
    )
    op.create_index("ix_skin_test_answers_option_id", "skin_test_answers", ["option_id"])
    op.create_index("ix_skin_test_answers_question_id", "skin_test_answers", ["question_id"])
    op.create_index("ix_skin_test_answers_result_id", "skin_test_answers", ["result_id"])
    op.create_index("ix_skin_test_answers_version_id", "skin_test_answers", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_skin_test_answers_version_id", table_name="skin_test_answers")
    op.drop_index("ix_skin_test_answers_result_id", table_name="skin_test_answers")
    op.drop_index("ix_skin_test_answers_question_id", table_name="skin_test_answers")
    op.drop_index("ix_skin_test_answers_option_id", table_name="skin_test_answers")
    op.drop_table("skin_test_answers")

    op.drop_index("ix_skin_test_results_version_id", table_name="skin_test_results")
    op.drop_index("ix_skin_test_results_user_id", table_name="skin_test_results")
    op.drop_index("ix_skin_test_results_baumann_type_profile_id", table_name="skin_test_results")
    op.drop_index("ix_skin_test_results_applied_profile_id", table_name="skin_test_results")
    op.drop_index("ix_skin_test_results_anonymous_id", table_name="skin_test_results")
    op.drop_table("skin_test_results")

    op.drop_index("ix_skin_profiles_user_id", table_name="skin_profiles")
    op.drop_index("ix_skin_profiles_latest_skin_test_result_id", table_name="skin_profiles")
    op.drop_index("ix_skin_profiles_baumann_type_profile_id", table_name="skin_profiles")
    op.drop_index("ix_skin_profiles_anonymous_id", table_name="skin_profiles")
    op.drop_table("skin_profiles")

    op.drop_index("ix_skin_test_options_question_id", table_name="skin_test_options")
    op.drop_table("skin_test_options")

    op.drop_index("ix_skin_test_questions_version_id", table_name="skin_test_questions")
    op.drop_table("skin_test_questions")

    op.drop_table("skin_test_versions")
    op.drop_table("baumann_type_profiles")
