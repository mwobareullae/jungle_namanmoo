"""관리자 성분 매핑 pending 그룹 요약표를 수동으로 갱신한다."""

import json

from app.db.session import engine
from app.services.admin.ingredient_mapping_pending_groups import (
    PendingIngredientGroupsRefreshError,
    PENDING_GROUPS_VIEW_NAME,
    refresh_pending_ingredient_mapping_groups,
)


def main() -> None:
    try:
        duration_ms = refresh_pending_ingredient_mapping_groups(engine)
    except PendingIngredientGroupsRefreshError as exc:
        raise SystemExit(
            "Ingredient mapping pending-group refresh failed. "
            "Retry: python -m app.cli.refresh_ingredient_mapping_pending_groups"
        ) from exc

    print(
        json.dumps(
            {"materialized_view": PENDING_GROUPS_VIEW_NAME, "duration_ms": round(duration_ms, 2)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
