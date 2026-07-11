"""add evidence discovery candidate inbox

Revision ID: 20260711_0032
Revises: 20260711_0031
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_0032"
down_revision: str | None = "20260711_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_discovery_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("discovery_key", sa.String(length=240), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_key", sa.String(length=160), nullable=False),
        sa.Column("pmid", sa.String(length=40), nullable=True),
        sa.Column("doi", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("journal", sa.String(length=240), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("publication_date_text", sa.String(length=80), nullable=True),
        sa.Column("publication_types", sa.Text(), nullable=True),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("abstract_excerpt", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("discovery_scope", sa.String(length=40), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("search_window_start", sa.Date(), nullable=True),
        sa.Column("search_window_end", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="candidate_unverified",
            nullable=False,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "review_status in ('candidate_unverified', 'accepted', 'rejected')",
            name="ck_evidence_discovery_candidates_review_status",
        ),
        sa.CheckConstraint(
            "review_status != 'accepted' or promoted_evidence_id is not null",
            name="ck_evidence_discovery_candidates_accepted_promoted",
        ),
        sa.CheckConstraint(
            "review_status != 'rejected' or promoted_evidence_id is null",
            name="ck_evidence_discovery_candidates_rejected_not_promoted",
        ),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["promoted_evidence_id"], ["ingredient_evidence.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discovery_key"),
        sa.UniqueConstraint(
            "ingredient_id",
            "effect_id",
            "paper_key",
            name="uq_evidence_discovery_candidates_pair_paper",
        ),
    )
    op.create_index(
        "ix_evidence_discovery_candidates_effect_id",
        "evidence_discovery_candidates",
        ["effect_id"],
    )
    op.create_index(
        "ix_evidence_discovery_candidates_ingredient_id",
        "evidence_discovery_candidates",
        ["ingredient_id"],
    )
    op.create_index(
        "ix_evidence_discovery_candidates_review_seen",
        "evidence_discovery_candidates",
        ["review_status", "last_seen_at"],
    )

    op.create_table(
        "evidence_discovery_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reviewer_user_id", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("promoted_evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "previous_status in ('candidate_unverified', 'accepted', 'rejected')",
            name="ck_evidence_discovery_reviews_previous_status",
        ),
        sa.CheckConstraint(
            "new_status in ('accepted', 'rejected')",
            name="ck_evidence_discovery_reviews_new_status",
        ),
        sa.CheckConstraint(
            "new_status != 'accepted' or promoted_evidence_id is not null",
            name="ck_evidence_discovery_reviews_accepted_promoted",
        ),
        sa.CheckConstraint(
            "new_status != 'rejected' or promoted_evidence_id is null",
            name="ck_evidence_discovery_reviews_rejected_not_promoted",
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["evidence_discovery_candidates.id"]),
        sa.ForeignKeyConstraint(["promoted_evidence_id"], ["ingredient_evidence.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_discovery_reviews_candidate_id",
        "evidence_discovery_reviews",
        ["candidate_id"],
    )
    op.create_index(
        "ix_evidence_discovery_reviews_reviewer_user_id",
        "evidence_discovery_reviews",
        ["reviewer_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_discovery_reviews_reviewer_user_id",
        table_name="evidence_discovery_reviews",
    )
    op.drop_index(
        "ix_evidence_discovery_reviews_candidate_id",
        table_name="evidence_discovery_reviews",
    )
    op.drop_table("evidence_discovery_reviews")
    op.drop_index(
        "ix_evidence_discovery_candidates_review_seen",
        table_name="evidence_discovery_candidates",
    )
    op.drop_index(
        "ix_evidence_discovery_candidates_ingredient_id",
        table_name="evidence_discovery_candidates",
    )
    op.drop_index(
        "ix_evidence_discovery_candidates_effect_id",
        table_name="evidence_discovery_candidates",
    )
    op.drop_table("evidence_discovery_candidates")
