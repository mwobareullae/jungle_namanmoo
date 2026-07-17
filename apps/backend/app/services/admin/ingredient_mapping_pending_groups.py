"""관리자 성분 매핑 pending 그룹 materialized view 갱신 도구."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.performance_logging import (
    current_time,
    elapsed_ms,
    log_error_event,
    log_performance_event,
)


PENDING_GROUPS_VIEW_NAME = "ingredient_mapping_pending_groups"
_REFRESH_SQL = text(f"refresh materialized view concurrently {PENDING_GROUPS_VIEW_NAME}")


class PendingIngredientGroupsRefreshError(RuntimeError):
    """pending 그룹 요약표 refresh 실패를 호출자에게 명확히 전달한다."""


def refresh_pending_ingredient_mapping_groups(engine: Engine) -> float:
    """상품-성분 연결 변경 뒤 pending 그룹 요약표를 비차단 방식으로 갱신한다.

    PostgreSQL은 ``REFRESH MATERIALIZED VIEW CONCURRENTLY``를 트랜잭션 안에서
    실행할 수 없다. 별도 AUTOCOMMIT 연결을 사용해, refresh 중에도 기존 관리자
    목록이 계속 조회되도록 한다.
    """

    if engine.dialect.name != "postgresql":
        raise PendingIngredientGroupsRefreshError(
            "Pending ingredient group refresh requires PostgreSQL."
        )

    started_at = current_time()
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(_REFRESH_SQL)
    except Exception as exc:
        log_error_event(
            "ingredient_mapping_pending_groups_refresh_failed",
            started_at=started_at,
            metadata={"materialized_view": PENDING_GROUPS_VIEW_NAME},
            exc=exc,
        )
        raise PendingIngredientGroupsRefreshError(
            "Pending ingredient mapping groups refresh failed."
        ) from exc

    duration_ms = elapsed_ms(started_at)
    log_performance_event(
        "ingredient_mapping_pending_groups_refreshed",
        duration_ms=duration_ms,
        metadata={"materialized_view": PENDING_GROUPS_VIEW_NAME},
    )
    return duration_ms
