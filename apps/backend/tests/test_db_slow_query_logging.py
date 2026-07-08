import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.performance_logging import reset_current_request_id, set_current_request_id
from app.db.slow_query_logging import configure_db_slow_query_logging


def test_db_slow_query_logging_emits_request_scoped_summary() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_db_slow_query_logging(engine, threshold_ms=0)

    logs = _capture_performance_logs()
    request_id_token = set_current_request_id("slow-query-request")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT :secret_value AS value"), {"secret_value": "do-not-log"})
    finally:
        reset_current_request_id(request_id_token)
        logs.close()
        engine.dispose()

    payload = next(
        line
        for line in logs.json_lines
        if line["event"] == "db_slow_query" and line["statement_type"] == "SELECT"
    )
    assert payload["request_id"] == "slow-query-request"
    assert payload["db_system"] == "sqlite"
    assert payload["duration_ms"] >= 0
    assert payload["sql"].startswith("SELECT")
    assert "do-not-log" not in payload["sql"]
    assert "parameters" not in payload
    assert payload["error"] is None


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    logger.setLevel(logging.INFO)
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler
