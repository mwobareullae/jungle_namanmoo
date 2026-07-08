import re
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.performance_logging import (
    current_time,
    elapsed_ms,
    get_current_request_id,
    log_performance_event,
)


_START_TIME_STACK_KEY = "mwobareullae_query_start_time_stack"
_SQL_MAX_LENGTH = 500


def configure_db_slow_query_logging(
    engine: Engine,
    *,
    threshold_ms: float | None = None,
) -> None:
    if not settings.enable_db_slow_query_logging:
        return
    if getattr(engine, "_mwobareullae_slow_query_logging_configured", False):
        return

    setattr(engine, "_mwobareullae_slow_query_logging_configured", True)
    normalized_threshold_ms = (
        settings.db_slow_query_threshold_ms if threshold_ms is None else max(0.0, threshold_ms)
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        conn.info.setdefault(_START_TIME_STACK_KEY, []).append(current_time())

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        started_at = _pop_start_time(conn)
        if started_at is None:
            return
        duration_ms = elapsed_ms(started_at)
        if duration_ms < normalized_threshold_ms:
            return
        _log_query(
            engine,
            statement,
            duration_ms=duration_ms,
            rowcount=_cursor_rowcount(cursor),
            executemany=executemany,
            error=None,
        )

    @event.listens_for(engine, "handle_error")
    def _handle_error(exception_context) -> None:
        connection = getattr(exception_context, "connection", None)
        if connection is None:
            return
        started_at = _pop_start_time(connection)
        if started_at is None:
            return
        duration_ms = elapsed_ms(started_at)
        if duration_ms < normalized_threshold_ms:
            return
        original_exception = getattr(exception_context, "original_exception", None)
        _log_query(
            engine,
            getattr(exception_context, "statement", None),
            duration_ms=duration_ms,
            rowcount=None,
            executemany=False,
            error=type(original_exception).__name__ if original_exception is not None else "DatabaseError",
        )


def _pop_start_time(conn) -> float | None:
    stack = conn.info.get(_START_TIME_STACK_KEY)
    if not stack:
        return None
    return stack.pop()


def _log_query(
    engine: Engine,
    statement: str | None,
    *,
    duration_ms: float,
    rowcount: int | None,
    executemany: bool,
    error: str | None,
) -> None:
    normalized_sql = _normalize_sql(statement)
    log_performance_event(
        "db_slow_query",
        request_id=get_current_request_id(),
        duration_ms=duration_ms,
        metadata={
            "db_system": engine.dialect.name,
            "statement_type": _statement_type(normalized_sql),
            "sql": normalized_sql,
            "sql_length": len(normalized_sql),
            "rowcount": rowcount,
            "executemany": bool(executemany),
            "error": error,
        },
    )


def _cursor_rowcount(cursor: Any) -> int | None:
    rowcount = getattr(cursor, "rowcount", None)
    if rowcount is None or rowcount < 0:
        return None
    return int(rowcount)


def _normalize_sql(statement: str | None) -> str:
    if not statement:
        return ""
    compact = re.sub(r"\s+", " ", statement).strip()
    if len(compact) <= _SQL_MAX_LENGTH:
        return compact
    return f"{compact[:_SQL_MAX_LENGTH]}..."


def _statement_type(sql: str) -> str | None:
    if not sql:
        return None
    first_word = sql.split(" ", 1)[0].upper()
    return first_word or None
