"""add ingredient mapping final dispositions

Revision ID: 20260719_0053
Revises: 20260719_0052
Create Date: 2026-07-19

This is a compatibility migration. Existing M2-A decisions remain valid while
P3 action APIs are introduced in a later change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260719_0053"
down_revision: str | None = "20260719_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REVIEW_TABLE = "ingredient_mapping_reviews"
_EVENT_TABLE = "ingredient_mapping_review_events"
_NON_MAPPING_DISPOSITIONS = "'NON_INGREDIENT', 'COMPOUND_MATERIAL', 'SOURCE_ERROR', 'UNRESOLVABLE'"


def upgrade() -> None:
    op.add_column(_REVIEW_TABLE, sa.Column("final_disposition", sa.String(length=32), nullable=True))
    op.add_column(_EVENT_TABLE, sa.Column("from_final_disposition", sa.String(length=32), nullable=True))
    op.add_column(_EVENT_TABLE, sa.Column("to_final_disposition", sa.String(length=32), nullable=True))

    # Existing approved rows already have a canonical target under the prior
    # constraint, so their final P3 disposition is unambiguous.
    op.execute(sa.text("UPDATE ingredient_mapping_reviews SET final_disposition = 'MAPPED' WHERE status = 'APPROVED'"))

    _replace_review_constraints_with_p3_compatible_constraints()
    _replace_event_constraints_with_p3_compatible_constraints()


def downgrade() -> None:
    connection = op.get_bind()
    has_p3_state = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM ingredient_mapping_reviews
                WHERE status = 'NEEDS_REVIEW' OR final_disposition IS NOT NULL
            ) OR EXISTS (
                SELECT 1
                FROM ingredient_mapping_review_events
                WHERE from_status = 'NEEDS_REVIEW'
                   OR to_status = 'NEEDS_REVIEW'
                   OR from_final_disposition IS NOT NULL
                   OR to_final_disposition IS NOT NULL
            )
            """
        )
    ).scalar_one()
    if has_p3_state:
        raise RuntimeError(
            "Cannot downgrade 20260719_0053 while P3 final classifications or NEEDS_REVIEW history exist. "
            "Migrate the data explicitly before removing the schema."
        )

    _restore_legacy_event_constraints()
    _restore_legacy_review_constraints()

    op.drop_column(_EVENT_TABLE, "to_final_disposition")
    op.drop_column(_EVENT_TABLE, "from_final_disposition")
    op.drop_column(_REVIEW_TABLE, "final_disposition")


def _replace_review_constraints_with_p3_compatible_constraints() -> None:
    for constraint_name in (
        "ck_ingredient_mapping_reviews_decision_reason_not_blank",
        "ck_ingredient_mapping_reviews_status_reason",
        "ck_ingredient_mapping_reviews_status_target",
        "ck_ingredient_mapping_reviews_status",
    ):
        op.drop_constraint(constraint_name, _REVIEW_TABLE, type_="check")

    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status",
        _REVIEW_TABLE,
        "status in ('HELD', 'NEEDS_REVIEW', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status_target",
        _REVIEW_TABLE,
        "(status = 'APPROVED' and target_ingredient_id is not null) or "
        "(status in ('HELD', 'NEEDS_REVIEW', 'REJECTED') and target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status_reason",
        _REVIEW_TABLE,
        "status not in ('HELD', 'NEEDS_REVIEW', 'REJECTED') or decision_reason is not null",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_decision_reason_not_blank",
        _REVIEW_TABLE,
        "decision_reason is null or length(trim(decision_reason)) > 0",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_final_disposition",
        _REVIEW_TABLE,
        "final_disposition is null or "
        "(final_disposition = 'MAPPED' and status = 'APPROVED' and target_ingredient_id is not null) or "
        f"(final_disposition in ({_NON_MAPPING_DISPOSITIONS}) and status = 'REJECTED' and target_ingredient_id is null)",
    )


def _replace_event_constraints_with_p3_compatible_constraints() -> None:
    for constraint_name in (
        "ck_ingredient_mapping_review_events_to_status_reason",
        "ck_ingredient_mapping_review_events_from_status_target",
        "ck_ingredient_mapping_review_events_to_status_target",
        "ck_ingredient_mapping_review_events_from_status",
        "ck_ingredient_mapping_review_events_to_status",
    ):
        op.drop_constraint(constraint_name, _EVENT_TABLE, type_="check")

    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status",
        _EVENT_TABLE,
        "to_status in ('HELD', 'NEEDS_REVIEW', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_from_status",
        _EVENT_TABLE,
        "from_status is null or from_status in ('HELD', 'NEEDS_REVIEW', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status_target",
        _EVENT_TABLE,
        "(to_status = 'APPROVED' and to_target_ingredient_id is not null) or "
        "(to_status in ('HELD', 'NEEDS_REVIEW', 'REJECTED') and to_target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_from_status_target",
        _EVENT_TABLE,
        "(from_status is null and from_target_ingredient_id is null) or "
        "(from_status = 'APPROVED' and from_target_ingredient_id is not null) or "
        "(from_status in ('HELD', 'NEEDS_REVIEW', 'REJECTED') and from_target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status_reason",
        _EVENT_TABLE,
        "to_status not in ('HELD', 'NEEDS_REVIEW', 'REJECTED') or "
        "(reason is not null and length(trim(reason)) > 0)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_final_disposition",
        _EVENT_TABLE,
        "to_final_disposition is null or "
        "(to_final_disposition = 'MAPPED' and to_status = 'APPROVED' and to_target_ingredient_id is not null) or "
        f"(to_final_disposition in ({_NON_MAPPING_DISPOSITIONS}) and to_status = 'REJECTED' and to_target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_from_final_disposition",
        _EVENT_TABLE,
        "from_final_disposition is null or "
        "(from_final_disposition = 'MAPPED' and from_status = 'APPROVED' and from_target_ingredient_id is not null) or "
        f"(from_final_disposition in ({_NON_MAPPING_DISPOSITIONS}) and from_status = 'REJECTED' and from_target_ingredient_id is null)",
    )


def _restore_legacy_review_constraints() -> None:
    for constraint_name in (
        "ck_ingredient_mapping_reviews_final_disposition",
        "ck_ingredient_mapping_reviews_decision_reason_not_blank",
        "ck_ingredient_mapping_reviews_status_reason",
        "ck_ingredient_mapping_reviews_status_target",
        "ck_ingredient_mapping_reviews_status",
    ):
        op.drop_constraint(constraint_name, _REVIEW_TABLE, type_="check")

    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status",
        _REVIEW_TABLE,
        "status in ('HELD', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status_target",
        _REVIEW_TABLE,
        "(status = 'APPROVED' and target_ingredient_id is not null) or "
        "(status in ('HELD', 'REJECTED') and target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_status_reason",
        _REVIEW_TABLE,
        "status not in ('HELD', 'REJECTED') or decision_reason is not null",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_reviews_decision_reason_not_blank",
        _REVIEW_TABLE,
        "decision_reason is null or length(trim(decision_reason)) > 0",
    )


def _restore_legacy_event_constraints() -> None:
    for constraint_name in (
        "ck_ingredient_mapping_review_events_from_final_disposition",
        "ck_ingredient_mapping_review_events_to_final_disposition",
        "ck_ingredient_mapping_review_events_to_status_reason",
        "ck_ingredient_mapping_review_events_from_status_target",
        "ck_ingredient_mapping_review_events_to_status_target",
        "ck_ingredient_mapping_review_events_from_status",
        "ck_ingredient_mapping_review_events_to_status",
    ):
        op.drop_constraint(constraint_name, _EVENT_TABLE, type_="check")

    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status",
        _EVENT_TABLE,
        "to_status in ('HELD', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_from_status",
        _EVENT_TABLE,
        "from_status is null or from_status in ('HELD', 'APPROVED', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status_target",
        _EVENT_TABLE,
        "(to_status = 'APPROVED' and to_target_ingredient_id is not null) or "
        "(to_status in ('HELD', 'REJECTED') and to_target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_from_status_target",
        _EVENT_TABLE,
        "(from_status is null and from_target_ingredient_id is null) or "
        "(from_status = 'APPROVED' and from_target_ingredient_id is not null) or "
        "(from_status in ('HELD', 'REJECTED') and from_target_ingredient_id is null)",
    )
    op.create_check_constraint(
        "ck_ingredient_mapping_review_events_to_status_reason",
        _EVENT_TABLE,
        "to_status not in ('HELD', 'REJECTED') or (reason is not null and length(trim(reason)) > 0)",
    )
