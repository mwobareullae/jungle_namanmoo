import json
import logging
import os
import signal
import threading
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.payment_cancel_service import (
    TossPaymentCancelClient,
    cancel_requested_orders,
)
from app.services.toss_payments_client import TossPaymentsClient, TossPaymentsClientError


logger = logging.getLogger(__name__)


class _UnavailableTossCancelClient:
    def cancel_payment(self, *, payment_key: str, cancel_reason: str) -> dict:
        raise TossPaymentsClientError(
            "TOSS_SECRET_KEY_MISSING",
            "TossPayments secret key is not configured.",
        )


def process_once(*, toss_client: TossPaymentCancelClient, limit: int, reason: str):
    with SessionLocal() as session:
        try:
            result = cancel_requested_orders(
                session,
                toss_client=toss_client,
                limit=limit,
                cancel_reason=reason,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    interval_seconds = max(1.0, float(os.getenv("CANCEL_WORKER_INTERVAL_SECONDS", "5")))
    batch_size = max(1, min(500, int(os.getenv("CANCEL_WORKER_BATCH_SIZE", "20"))))
    reason = os.getenv("CANCEL_WORKER_REASON", "customer requested cancellation").strip()
    if not reason:
        raise ValueError("CANCEL_WORKER_REASON must not be blank")

    try:
        toss_client: TossPaymentCancelClient = TossPaymentsClient.from_settings()
    except TossPaymentsClientError:
        toss_client = _UnavailableTossCancelClient()

    stop_event = threading.Event()

    def stop_worker(*_args) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    logger.info("cancel worker started interval=%s batch_size=%s", interval_seconds, batch_size)

    while not stop_event.is_set():
        try:
            result = process_once(toss_client=toss_client, limit=batch_size, reason=reason)
            if result.scanned_count:
                logger.info("cancel worker result %s", json.dumps(asdict(result), ensure_ascii=False))
        except Exception:
            logger.exception("cancel worker iteration failed")
        stop_event.wait(interval_seconds)

    logger.info("cancel worker stopped")


if __name__ == "__main__":
    main()
