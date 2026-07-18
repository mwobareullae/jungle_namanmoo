"""관리자 쓰기 후 카탈로그 ES 문서를 best-effort로 동기화한다."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.services.elasticsearch_catalog_index import (
    ElasticsearchCatalogIndexError,
    reindex_catalog_product_to_elasticsearch,
)


logger = logging.getLogger(__name__)


def sync_catalog_product_after_commit(
    session: Session,
    product_code: str,
    *,
    event_prefix: str = "admin_product",
) -> None:
    """커밋된 상품 1건을 ES에 동기화한다.

    색인 실패는 DB 정합성을 깨지 않으므로 호출자의 성공 응답을 바꾸지 않는다.
    ``event_prefix`` 기본값은 기존 상품 등록·수정 로그 이름을 그대로 보존한다.
    """

    started_at = current_time()
    try:
        result = reindex_catalog_product_to_elasticsearch(session, product_id=product_code)
    except ElasticsearchCatalogIndexError as exc:
        log_performance_event(
            f"{event_prefix}_catalog_sync_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"product_id": product_code, "error": type(exc).__name__},
        )
        logger.warning(
            "catalog product sync failed",
            extra={"product_id": product_code, "error_type": type(exc).__name__},
        )
        return

    log_performance_event(
        f"{event_prefix}_catalog_sync_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={"product_id": product_code, "action": result.action},
    )
