"""normalize sensitivity enum

Revision ID: 20260709_0028
Revises: 20260707_0027
Create Date: 2026-07-09
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260709_0028"
down_revision: str | None = "20260707_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


THREE_LEVEL_SENSITIVITY = "sensitivity in ('낮음', '보통', '높음')"
THREE_LEVEL_MAPPED_SENSITIVITY = "mapped_sensitivity in ('낮음', '보통', '높음')"
THREE_LEVEL_EXPLICIT_SENSITIVITY = (
    "explicit_sensitivity is null or explicit_sensitivity in ('낮음', '보통', '높음')"
)
THREE_LEVEL_BAUMANN_SENSITIVITY = (
    "baumann_inferred_sensitivity is null or baumann_inferred_sensitivity in ('낮음', '보통', '높음')"
)

LEGACY_SENSITIVITY = "sensitivity in ('낮음', '보통', '높음', '민감')"
LEGACY_MAPPED_SENSITIVITY = "mapped_sensitivity in ('낮음', '보통', '높음', '민감')"
LEGACY_EXPLICIT_SENSITIVITY = (
    "explicit_sensitivity is null or explicit_sensitivity in ('낮음', '보통', '높음', '민감')"
)
LEGACY_BAUMANN_SENSITIVITY = (
    "baumann_inferred_sensitivity is null or baumann_inferred_sensitivity in ('낮음', '보통', '높음', '민감')"
)


def upgrade() -> None:
    op.execute(
        "update baumann_type_profiles set mapped_sensitivity = '높음' "
        "where mapped_sensitivity = '민감'"
    )
    op.execute("update skin_profiles set sensitivity = '높음' where sensitivity = '민감'")
    op.execute(
        "update skin_profiles set explicit_sensitivity = '높음' "
        "where explicit_sensitivity = '민감'"
    )
    op.execute(
        "update skin_profiles set baumann_inferred_sensitivity = '높음' "
        "where baumann_inferred_sensitivity = '민감'"
    )
    op.execute(
        "update skin_test_results set mapped_sensitivity = '높음' "
        "where mapped_sensitivity = '민감'"
    )

    op.drop_constraint("ck_baumann_mapped_sensitivity", "baumann_type_profiles", type_="check")
    op.create_check_constraint(
        "ck_baumann_mapped_sensitivity",
        "baumann_type_profiles",
        THREE_LEVEL_MAPPED_SENSITIVITY,
    )

    op.drop_constraint("ck_skin_profiles_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_sensitivity",
        "skin_profiles",
        THREE_LEVEL_SENSITIVITY,
    )
    op.drop_constraint("ck_skin_profiles_explicit_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_explicit_sensitivity",
        "skin_profiles",
        THREE_LEVEL_EXPLICIT_SENSITIVITY,
    )
    op.drop_constraint("ck_skin_profiles_baumann_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_baumann_sensitivity",
        "skin_profiles",
        THREE_LEVEL_BAUMANN_SENSITIVITY,
    )

    op.drop_constraint("ck_skin_test_results_mapped_sensitivity", "skin_test_results", type_="check")
    op.create_check_constraint(
        "ck_skin_test_results_mapped_sensitivity",
        "skin_test_results",
        THREE_LEVEL_MAPPED_SENSITIVITY,
    )


def downgrade() -> None:
    op.drop_constraint("ck_baumann_mapped_sensitivity", "baumann_type_profiles", type_="check")
    op.create_check_constraint(
        "ck_baumann_mapped_sensitivity",
        "baumann_type_profiles",
        LEGACY_MAPPED_SENSITIVITY,
    )

    op.drop_constraint("ck_skin_profiles_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_sensitivity",
        "skin_profiles",
        LEGACY_SENSITIVITY,
    )
    op.drop_constraint("ck_skin_profiles_explicit_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_explicit_sensitivity",
        "skin_profiles",
        LEGACY_EXPLICIT_SENSITIVITY,
    )
    op.drop_constraint("ck_skin_profiles_baumann_sensitivity", "skin_profiles", type_="check")
    op.create_check_constraint(
        "ck_skin_profiles_baumann_sensitivity",
        "skin_profiles",
        LEGACY_BAUMANN_SENSITIVITY,
    )

    op.drop_constraint("ck_skin_test_results_mapped_sensitivity", "skin_test_results", type_="check")
    op.create_check_constraint(
        "ck_skin_test_results_mapped_sensitivity",
        "skin_test_results",
        LEGACY_MAPPED_SENSITIVITY,
    )
