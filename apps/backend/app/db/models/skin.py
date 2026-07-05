from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


SKIN_TYPE_CHECK = "skin_type in ('건성', '지성', '복합성', '중성', '수부지')"
SENSITIVITY_CHECK = "sensitivity in ('낮음', '보통', '높음', '민감')"


class BaumannTypeProfile(Base):
    __tablename__ = "baumann_type_profiles"
    __table_args__ = (
        CheckConstraint("length(trim(type_code)) = 4", name="ck_baumann_type_profiles_type_code_length"),
        CheckConstraint(SKIN_TYPE_CHECK.replace("skin_type", "mapped_skin_type"), name="ck_baumann_mapped_skin_type"),
        CheckConstraint(
            SENSITIVITY_CHECK.replace("sensitivity", "mapped_sensitivity"),
            name="ck_baumann_mapped_sensitivity",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    type_code: Mapped[str] = mapped_column(String(4), unique=True, nullable=False)
    object_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mapped_skin_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mapped_sensitivity: Mapped[str] = mapped_column(String(40), nullable=False)
    concern_tags: Mapped[list | None] = mapped_column(jsonb_type(), nullable=True)
    recommended_effect_ids: Mapped[list] = mapped_column(jsonb_type(), nullable=False, default=list)
    avoid_hints: Mapped[list | dict | None] = mapped_column(jsonb_type(), nullable=True)
    keywords: Mapped[list | None] = mapped_column(jsonb_type(), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SkinTestVersion(Base):
    __tablename__ = "skin_test_versions"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'active', 'archived')", name="ck_skin_test_versions_status"),
        CheckConstraint("question_count > 0", name="ck_skin_test_versions_question_count_positive"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    version_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SkinTestQuestion(Base):
    __tablename__ = "skin_test_questions"
    __table_args__ = (
        UniqueConstraint("version_id", "question_key", name="uq_skin_test_questions_version_key"),
        UniqueConstraint("version_id", "sequence", name="uq_skin_test_questions_version_sequence"),
        UniqueConstraint("id", "version_id", name="uq_skin_test_questions_id_version"),
        CheckConstraint(
            "axis in ('OD', 'SR', 'PN', 'WT', 'CATEGORY_PREF', 'BUYING_CRITERIA', 'PRICE_PREF', 'TRIGGER_PREF')",
            name="ck_skin_test_questions_axis",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("skin_test_versions.id"), nullable=False, index=True)
    question_key: Mapped[str] = mapped_column(String(40), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    axis: Mapped[str] = mapped_column(String(40), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    helper_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_conditions: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SkinTestOption(Base):
    __tablename__ = "skin_test_options"
    __table_args__ = (
        UniqueConstraint("question_id", "option_key", name="uq_skin_test_options_question_key"),
        UniqueConstraint("question_id", "display_order", name="uq_skin_test_options_question_order"),
        UniqueConstraint("id", "question_id", name="uq_skin_test_options_id_question"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("skin_test_questions.id"), nullable=False, index=True)
    option_key: Mapped[str] = mapped_column(String(20), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    internal_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    axis_value: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score_delta: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    commerce_mapping: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SkinProfile(Base):
    __tablename__ = "skin_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_skin_profiles_user_id"),
        CheckConstraint(SKIN_TYPE_CHECK, name="ck_skin_profiles_skin_type"),
        CheckConstraint(SENSITIVITY_CHECK, name="ck_skin_profiles_sensitivity"),
        CheckConstraint(
            "explicit_skin_type is null or explicit_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_profiles_explicit_skin_type",
        ),
        CheckConstraint(
            "explicit_sensitivity is null or explicit_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_profiles_explicit_sensitivity",
        ),
        CheckConstraint(
            "baumann_inferred_skin_type is null or baumann_inferred_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_profiles_baumann_skin_type",
        ),
        CheckConstraint(
            "baumann_inferred_sensitivity is null or baumann_inferred_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_profiles_baumann_sensitivity",
        ),
        CheckConstraint("source in ('manual', 'skin_test', 'mixed', 'import')", name="ck_skin_profiles_source"),
        CheckConstraint(
            "baumann_signal_weight >= 0 and baumann_signal_weight <= 1",
            name="ck_skin_profiles_baumann_signal_weight",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    anonymous_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    skin_type: Mapped[str] = mapped_column(String(40), nullable=False, default="중성", server_default="중성")
    sensitivity: Mapped[str] = mapped_column(String(40), nullable=False, default="보통", server_default="보통")
    skin_type_source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", server_default="manual")
    sensitivity_source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", server_default="manual")
    skin_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sensitivity_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    explicit_skin_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    explicit_sensitivity: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avoid_ingredients: Mapped[list | None] = mapped_column(jsonb_type(), nullable=True)
    baumann_type_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("baumann_type_profiles.id"),
        nullable=True,
        index=True,
    )
    baumann_type_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    baumann_inferred_skin_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    baumann_inferred_sensitivity: Mapped[str | None] = mapped_column(String(40), nullable=True)
    baumann_signal_weight: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.2500"),
        server_default="0.2500",
    )
    latest_skin_test_result_id: Mapped[int | None] = mapped_column(big_integer_pk_type(), nullable=True, index=True)
    commerce_profile: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    concern_profile_json: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SkinTestResult(Base):
    __tablename__ = "skin_test_results"
    __table_args__ = (
        UniqueConstraint("result_code", name="uq_skin_test_results_result_code"),
        UniqueConstraint("id", "version_id", name="uq_skin_test_results_id_version"),
        CheckConstraint("length(trim(type_code)) = 4", name="ck_skin_test_results_type_code_length"),
        CheckConstraint(
            "mapped_skin_type in ('건성', '지성', '복합성', '중성', '수부지')",
            name="ck_skin_test_results_mapped_skin_type",
        ),
        CheckConstraint(
            "mapped_sensitivity in ('낮음', '보통', '높음', '민감')",
            name="ck_skin_test_results_mapped_sensitivity",
        ),
        CheckConstraint(
            "applied_weight is null or (applied_weight >= 0 and applied_weight <= 1)",
            name="ck_skin_test_results_applied_weight",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    result_code: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    anonymous_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("skin_test_versions.id"), nullable=False, index=True)
    baumann_type_profile_id: Mapped[int] = mapped_column(
        ForeignKey("baumann_type_profiles.id"),
        nullable=False,
        index=True,
    )
    type_code: Mapped[str] = mapped_column(String(4), nullable=False)
    mapped_skin_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mapped_sensitivity: Mapped[str] = mapped_column(String(40), nullable=False)
    axis_scores: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict)
    commerce_profile: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    recommended_effect_ids: Mapped[list] = mapped_column(jsonb_type(), nullable=False, default=list)
    avoid_hints: Mapped[list | dict | None] = mapped_column(jsonb_type(), nullable=True)
    raw_score_payload: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    applied_profile_id: Mapped[int | None] = mapped_column(ForeignKey("skin_profiles.id"), nullable=True, index=True)
    applied_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkinTestAnswer(Base):
    __tablename__ = "skin_test_answers"
    __table_args__ = (
        UniqueConstraint("result_id", "question_id", name="uq_skin_test_answers_result_question"),
        UniqueConstraint("result_id", "answer_order", name="uq_skin_test_answers_result_order"),
        ForeignKeyConstraint(
            ["result_id", "version_id"],
            ["skin_test_results.id", "skin_test_results.version_id"],
            name="fk_skin_test_answers_result_version",
        ),
        ForeignKeyConstraint(
            ["question_id", "version_id"],
            ["skin_test_questions.id", "skin_test_questions.version_id"],
            name="fk_skin_test_answers_question_version",
        ),
        ForeignKeyConstraint(
            ["option_id", "question_id"],
            ["skin_test_options.id", "skin_test_options.question_id"],
            name="fk_skin_test_answers_option_question",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(big_integer_pk_type(), nullable=False, index=True)
    version_id: Mapped[int] = mapped_column(big_integer_pk_type(), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(big_integer_pk_type(), nullable=False, index=True)
    option_id: Mapped[int] = mapped_column(big_integer_pk_type(), nullable=False, index=True)
    answer_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question_snapshot: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    option_snapshot: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
