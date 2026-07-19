from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.admin.ingredient_mapping import (
    IngredientMappingActionResponse,
    IngredientMappingBulkApprovalItem,
)
from app.schemas.common import ApiError
from app.services.admin import ingredient_mapping_bulk_approval_service as svc


def _item(*, pending_code: str = "ing_pending_a") -> IngredientMappingBulkApprovalItem:
    return IngredientMappingBulkApprovalItem(
        pending_code=pending_code,
        normalized_source_name="example",
        target_ingredient_code="ing_canonical_example",
    )


def test_bulk_approval_rejects_confirmation_count_mismatch_before_query() -> None:
    with pytest.raises(ApiError) as exc:
        svc.approve_kcia_alias_exact_batch(
            SimpleNamespace(),
            items=[_item()],
            confirmed_count=2,
            actor_user_id=1,
        )
    assert exc.value.code == "BULK_APPROVAL_CONFIRMATION_MISMATCH"


def test_bulk_approval_rejects_duplicate_group_before_query() -> None:
    with pytest.raises(ApiError) as exc:
        svc.approve_kcia_alias_exact_batch(
            SimpleNamespace(),
            items=[_item(), _item()],
            confirmed_count=2,
            actor_user_id=1,
        )
    assert exc.value.code == "BULK_APPROVAL_DUPLICATE_ITEM"


def test_bulk_approval_uses_shared_reference_and_approves_every_selected_item(monkeypatch) -> None:
    validated: list[str] = []
    approved: list[dict] = []

    monkeypatch.setattr(
        svc,
        "_require_current_kcia_alias_exact_candidate",
        lambda _session, item: validated.append(item.pending_code),
    )

    def fake_approve(_session, **kwargs):
        approved.append(kwargs)
        return IngredientMappingActionResponse(
            pending_code=kwargs["pending_code"],
            normalized_source_name=kwargs["normalized_source_name"],
            status="APPROVED",
            final_disposition="MAPPED",
            target_ingredient_code=kwargs["target_ingredient_code"],
            target_ingredient_name="예시 성분",
            decision_reason=kwargs["decision_reason"],
            reviewed_at=datetime.now(UTC),
            available_actions=["REOPEN"],
        )

    monkeypatch.setattr(svc, "approve_ingredient_mapping", fake_approve)
    result = svc.approve_kcia_alias_exact_batch(
        SimpleNamespace(),
        items=[_item(pending_code="ing_pending_a"), _item(pending_code="ing_pending_b")],
        confirmed_count=2,
        actor_user_id=7,
    )

    assert result.approved_count == 2
    assert validated == ["ing_pending_a", "ing_pending_b"]
    assert len(approved) == 2
    assert result.batch_reference.startswith(f"{svc.BULK_REFERENCE_PREFIX}:")
    assert {item["source_reference"] for item in approved} == {result.batch_reference}
    assert {item["decision_reason"] for item in approved} == {"KCIA 근거 별칭 정확 일치 일괄 승인"}
