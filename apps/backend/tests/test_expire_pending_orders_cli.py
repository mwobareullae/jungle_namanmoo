from app.cli.expire_pending_orders import _exit_code_for
from app.services.payment_expiry_service import ExpirePendingOrdersResult


def test_exit_code_is_zero_when_no_orders_failed() -> None:
    result = ExpirePendingOrdersResult(expired_count=3, order_codes=["a", "b", "c"])
    assert _exit_code_for(result) == 0


def test_exit_code_is_nonzero_when_any_order_failed() -> None:
    """일부 주문만 실패해도(나머지는 정상 커밋되어도) 스케줄러가 연속 실패로 잡아낼 수 있도록
    종료 코드는 실패로 표시해야 한다(Codex 지적 사항, 2026-07-14)."""
    result = ExpirePendingOrdersResult(
        expired_count=2,
        order_codes=["a", "b"],
        failed_count=1,
        failed_order_codes=["c"],
    )
    assert _exit_code_for(result) == 1
