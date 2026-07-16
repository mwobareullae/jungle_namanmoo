from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


INGREDIENT_MAPPING_REVIEW_STATUS_VALUES = "'HELD', 'APPROVED', 'REJECTED'"


class Concern(Base):
    __tablename__ = "concerns"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ConcernAlias(Base):
    __tablename__ = "concern_aliases"
    __table_args__ = (
        UniqueConstraint("concern_id", "normalized_alias", name="uq_concern_aliases_concern_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_id: Mapped[int] = mapped_column(ForeignKey("concerns.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(80), nullable=False)


class Effect(Base):
    __tablename__ = "effects"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    effect_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class EffectAlias(Base):
    __tablename__ = "effect_aliases"
    __table_args__ = (
        UniqueConstraint("effect_id", "normalized_alias", name="uq_effect_aliases_effect_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(80), nullable=False)


class ConcernEffect(Base):
    __tablename__ = "concern_effects"
    __table_args__ = (
        UniqueConstraint("concern_id", "effect_id", name="uq_concern_effects_concern_effect"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    concern_id: Mapped[int] = mapped_column(ForeignKey("concerns.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=1, server_default="1.0")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_ko: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_alias", name="uq_ingredient_aliases_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(160), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngredientMappingReview(Base):
    __tablename__ = "ingredient_mapping_reviews"
    __table_args__ = (
        UniqueConstraint(
            "source_ingredient_id",
            "normalized_source_name",
            name="uq_ingredient_mapping_reviews_source_normalized_name",
        ),
        CheckConstraint(
            f"status in ({INGREDIENT_MAPPING_REVIEW_STATUS_VALUES})",
            name="ck_ingredient_mapping_reviews_status",
        ),
        CheckConstraint(
            "(status = 'APPROVED' and target_ingredient_id is not null) or "
            "(status in ('HELD', 'REJECTED') and target_ingredient_id is null)",
            name="ck_ingredient_mapping_reviews_status_target",
        ),
        CheckConstraint(
            "status not in ('HELD', 'REJECTED') or decision_reason is not null",
            name="ck_ingredient_mapping_reviews_status_reason",
        ),
        CheckConstraint(
            "decision_reason is null or length(trim(decision_reason)) > 0",
            name="ck_ingredient_mapping_reviews_decision_reason_not_blank",
        ),
        Index("ix_ingredient_mapping_reviews_status", "status"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    source_ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False)
    source_ingredient_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_source_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    target_ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngredientMappingReviewEvent(Base):
    __tablename__ = "ingredient_mapping_review_events"
    __table_args__ = (
        CheckConstraint(
            f"to_status in ({INGREDIENT_MAPPING_REVIEW_STATUS_VALUES})",
            name="ck_ingredient_mapping_review_events_to_status",
        ),
        CheckConstraint(
            f"from_status is null or from_status in ({INGREDIENT_MAPPING_REVIEW_STATUS_VALUES})",
            name="ck_ingredient_mapping_review_events_from_status",
        ),
        CheckConstraint(
            "(to_status = 'APPROVED' and to_target_ingredient_id is not null) or "
            "(to_status in ('HELD', 'REJECTED') and to_target_ingredient_id is null)",
            name="ck_ingredient_mapping_review_events_to_status_target",
        ),
        CheckConstraint(
            "(from_status is null and from_target_ingredient_id is null) or "
            "(from_status = 'APPROVED' and from_target_ingredient_id is not null) or "
            "(from_status in ('HELD', 'REJECTED') and from_target_ingredient_id is null)",
            name="ck_ingredient_mapping_review_events_from_status_target",
        ),
        CheckConstraint(
            "to_status not in ('HELD', 'REJECTED') or "
            "(reason is not null and length(trim(reason)) > 0)",
            name="ck_ingredient_mapping_review_events_to_status_reason",
        ),
        Index("ix_ingredient_mapping_review_events_review_created_at", "review_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("ingredient_mapping_reviews.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    from_target_ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), nullable=True)
    to_target_ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(jsonb_type(), nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngredientEffect(Base):
    __tablename__ = "ingredient_effects"
    __table_args__ = (
        UniqueConstraint("ingredient_id", "effect_id", name="uq_ingredient_effects_ingredient_effect"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    effect_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0.0")


class IngredientEffectRange(Base):
    __tablename__ = "ingredient_effect_ranges"
    __table_args__ = (
        UniqueConstraint(
            "ingredient_id",
            "effect_id",
            "unit",
            name="uq_ingredient_effect_ranges_ingredient_effect_unit",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    meaningful_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    optimal_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    optimal_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    excessive_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    range_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngredientEvidence(Base):
    __tablename__ = "ingredient_evidence"
    __table_args__ = (
        CheckConstraint(
            "review_status in ('candidate_unverified', 'accepted', 'rejected')",
            name="ck_ingredient_evidence_review_status",
        ),
        CheckConstraint(
            "result_direction in ('positive', 'negative', 'null', 'unclear')",
            name="ck_ingredient_evidence_result_direction",
        ),
        CheckConstraint(
            "score_use_level in ('primary', 'supporting', 'reference_only')",
            name="ck_ingredient_evidence_score_use_level",
        ),
        CheckConstraint(
            "representative_rank is null or representative_rank between 1 and 3",
            name="ck_ingredient_evidence_representative_rank",
        ),
        CheckConstraint(
            "is_representative = true or representative_rank is null",
            name="ck_ingredient_evidence_rank_requires_representative",
        ),
        CheckConstraint(
            "is_representative = false or "
            "(review_status = 'accepted' and is_current = true and representative_rank is not null)",
            name="ck_ingredient_evidence_representative_eligible",
        ),
        Index(
            "ix_ingredient_evidence_canonical_pair",
            "ingredient_id",
            "effect_id",
            "canonical_evidence_key",
        ),
        Index(
            "ix_ingredient_evidence_review_current",
            "review_status",
            "is_current",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int | None] = mapped_column(ForeignKey("effects.id"), nullable=True, index=True)
    evidence_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0.0")
    source_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pmid: Mapped[str | None] = mapped_column(String(40), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_authority_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    canonical_evidence_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="candidate_unverified",
        server_default="candidate_unverified",
    )
    result_direction: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unclear",
        server_default="unclear",
    )
    score_use_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="reference_only",
        server_default="reference_only",
    )
    is_representative: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    representative_rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceDiscoveryCandidate(Base):
    __tablename__ = "evidence_discovery_candidates"
    __table_args__ = (
        CheckConstraint(
            "review_status in ('candidate_unverified', 'accepted', 'rejected')",
            name="ck_evidence_discovery_candidates_review_status",
        ),
        CheckConstraint(
            "review_status != 'accepted' or promoted_evidence_id is not null",
            name="ck_evidence_discovery_candidates_accepted_promoted",
        ),
        CheckConstraint(
            "review_status != 'rejected' or promoted_evidence_id is null",
            name="ck_evidence_discovery_candidates_rejected_not_promoted",
        ),
        UniqueConstraint(
            "ingredient_id",
            "effect_id",
            "paper_key",
            name="uq_evidence_discovery_candidates_pair_paper",
        ),
        Index(
            "ix_evidence_discovery_candidates_review_seen",
            "review_status",
            "last_seen_at",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    discovery_key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    effect_id: Mapped[int] = mapped_column(ForeignKey("effects.id"), nullable=False, index=True)
    paper_key: Mapped[str] = mapped_column(String(160), nullable=False)
    pmid: Mapped[str | None] = mapped_column(String(40), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    journal: Mapped[str | None] = mapped_column(String(240), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    publication_date_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    publication_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    search_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="candidate_unverified",
        server_default="candidate_unverified",
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promoted_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredient_evidence.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvidenceDiscoveryReview(Base):
    __tablename__ = "evidence_discovery_reviews"
    __table_args__ = (
        CheckConstraint(
            "previous_status in ('candidate_unverified', 'accepted', 'rejected')",
            name="ck_evidence_discovery_reviews_previous_status",
        ),
        CheckConstraint(
            "new_status in ('accepted', 'rejected')",
            name="ck_evidence_discovery_reviews_new_status",
        ),
        CheckConstraint(
            "new_status != 'accepted' or promoted_evidence_id is not null",
            name="ck_evidence_discovery_reviews_accepted_promoted",
        ),
        CheckConstraint(
            "new_status != 'rejected' or promoted_evidence_id is null",
            name="ck_evidence_discovery_reviews_rejected_not_promoted",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_discovery_candidates.id"), nullable=False, index=True
    )
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    promoted_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredient_evidence.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RiskFlag(Base):
    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    risk_type: Mapped[str] = mapped_column(String(80), nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    severity_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    applies_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
