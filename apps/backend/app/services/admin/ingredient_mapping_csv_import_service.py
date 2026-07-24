"""운영 DB 성분 매핑 CSV의 dry-run, 원자적 배치 적용, export."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models.catalog import ProductIngredient
from app.db.models.taxonomy import Ingredient, IngredientMappingReview
from app.schemas.admin.ingredient_mapping_csv_import import (
    IngredientMappingCsvApplyResponse,
    IngredientMappingCsvPreviewResponse,
    IngredientMappingCsvPreviewRow,
    IngredientMappingCsvPreviewSummary,
    IngredientMappingCsvRowInput,
)
from app.schemas.common import ApiError
from app.services.admin.ingredient_mapping_mutation_service import approve_ingredient_mapping


BATCH_REFERENCE_PREFIX = "CSV_INGREDIENT_MAPPING"
DEFAULT_DECISION_REASON = "관리자 CSV 일괄 매핑"
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class _RowContext:
    row: IngredientMappingCsvRowInput
    source: Ingredient | None
    target: Ingredient | None
    product_rows: list[ProductIngredient]
    already_applied: bool


@dataclass
class CsvApplyOutcome:
    response: IngredientMappingCsvApplyResponse
    affected_product_ids: set[int]


def normalize_source_name(value: str | None) -> str:
    return _WHITESPACE_RE.sub("", value or "").lower()


def preview_digest(rows: list[IngredientMappingCsvRowInput]) -> str:
    payload = [row.model_dump(mode="json") for row in rows]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preview_csv_mapping_batch(
    session: Session, rows: list[IngredientMappingCsvRowInput]
) -> IngredientMappingCsvPreviewResponse:
    response, _ = _validate_rows(session, rows)
    return response


def apply_csv_mapping_batch(
    session: Session,
    *,
    rows: list[IngredientMappingCsvRowInput],
    expected_preview_digest: str,
    confirmed_count: int,
    actor_user_id: int,
) -> CsvApplyOutcome:
    if confirmed_count != len(rows):
        raise ApiError(
            400,
            "CSV_MAPPING_CONFIRMATION_MISMATCH",
            "Confirmed count must match the number of CSV rows.",
        )
    response, contexts = _validate_rows(session, rows)
    if response.preview_digest != expected_preview_digest:
        raise ApiError(409, "CSV_MAPPING_PREVIEW_STALE", "CSV preview has changed. Run dry-run again.")
    if response.summary.invalid:
        raise ApiError(
            409,
            "CSV_MAPPING_BATCH_INVALID",
            "One or more CSV rows are invalid. Nothing was applied.",
        )

    batch_reference = f"{BATCH_REFERENCE_PREFIX}:{uuid4()}"
    affected_product_ids: set[int] = set()
    created_targets: dict[str, Ingredient] = {}
    applied = moved = collapsed = created = 0

    for context in contexts:
        if context.already_applied:
            continue
        source = context.source
        if source is None:
            raise ApiError(409, "CSV_MAPPING_SOURCE_CHANGED", "Pending ingredient changed after preview.")
        target = context.target or created_targets.get(context.row.target_ingredient_code)
        if target is None:
            target = Ingredient(
                ingredient_code=context.row.target_ingredient_code,
                name_ko=(context.row.target_name_ko or "").strip(),
                name_en=(context.row.target_name_en or "").strip() or None,
                normalized_name=normalize_source_name(context.row.target_name_ko),
                description=f"관리자 CSV에서 생성된 canonical 성분. {context.row.source_reference}",
                source_url=None,
                is_active=True,
            )
            session.add(target)
            session.flush()
            created_targets[target.ingredient_code] = target
            created += 1

        approve_ingredient_mapping(
            session,
            pending_code=context.row.pending_code,
            normalized_source_name=context.row.normalized_source_name,
            target_ingredient_code=target.ingredient_code,
            decision_reason=context.row.decision_reason or DEFAULT_DECISION_REASON,
            actor_user_id=actor_user_id,
            source_reference=f"{batch_reference};{context.row.source_reference or 'admin-csv'}",
        )

        product_ids = {int(product_row.product_id) for product_row in context.product_rows}
        existing_target_product_ids = set(
            session.execute(
                select(ProductIngredient.product_id).where(
                    ProductIngredient.product_id.in_(product_ids),
                    ProductIngredient.ingredient_id == target.id,
                )
            ).scalars()
        ) if product_ids else set()

        for product_row in context.product_rows:
            affected_product_ids.add(int(product_row.product_id))
            if product_row.product_id in existing_target_product_ids:
                session.delete(product_row)
                collapsed += 1
            else:
                product_row.ingredient_id = target.id
                moved += 1
        session.flush()
        applied += 1

    return CsvApplyOutcome(
        response=IngredientMappingCsvApplyResponse(
            batch_reference=batch_reference,
            total=len(rows),
            applied=applied,
            already_applied=response.summary.already_applied,
            moved_connections=moved,
            collapsed_duplicates=collapsed,
            created_canonicals=created,
            affected_products=len(affected_product_ids),
            review_refresh="NOT_REQUIRED",
            search_reindex_required=applied > 0,
        ),
        affected_product_ids=affected_product_ids,
    )


def iter_pending_mapping_csv(session: Session):
    """현재 미분류 그룹을 UTF-8 BOM CSV로 스트리밍한다."""

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "action",
            "pending_code",
            "raw_name",
            "normalized_source_name",
            "expected_connection_count",
            "target_ingredient_code",
            "target_name_ko",
            "target_name_en",
            "decision_reason",
            "source_reference",
        ]
    )
    yield "\ufeff" + output.getvalue()
    output.seek(0)
    output.truncate(0)

    result = session.execute(
        text(
            """
            select g.pending_code, g.raw_name, g.normalized_source_name, g.connection_count
            from ingredient_mapping_pending_groups g
            left join ingredient_mapping_reviews rev
              on rev.source_ingredient_id = g.source_ingredient_id
             and rev.normalized_source_name = g.normalized_source_name
            where rev.id is null or rev.status in ('HELD', 'NEEDS_REVIEW')
            order by g.pending_code, g.normalized_source_name
            """
        ).execution_options(stream_results=True)
    )
    buffered = 0
    for row in result:
        writer.writerow(
            [
                "MAP_EXISTING",
                row.pending_code,
                row.raw_name,
                row.normalized_source_name,
                int(row.connection_count),
                "",
                "",
                "",
                DEFAULT_DECISION_REASON,
                "",
            ]
        )
        buffered += 1
        if buffered >= 500:
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            buffered = 0
    if output.tell():
        yield output.getvalue()


def _validate_rows(
    session: Session, rows: list[IngredientMappingCsvRowInput]
) -> tuple[IngredientMappingCsvPreviewResponse, list[_RowContext]]:
    source_codes = {row.pending_code.strip() for row in rows}
    target_codes = {row.target_ingredient_code.strip() for row in rows}
    sources = {
        ingredient.ingredient_code: ingredient
        for ingredient in session.execute(
            select(Ingredient).where(Ingredient.ingredient_code.in_(source_codes))
        ).scalars()
    }
    targets = {
        ingredient.ingredient_code: ingredient
        for ingredient in session.execute(
            select(Ingredient).where(Ingredient.ingredient_code.in_(target_codes))
        ).scalars()
    }
    source_ids = [source.id for source in sources.values()]
    product_rows = list(
        session.execute(
            select(ProductIngredient).where(ProductIngredient.ingredient_id.in_(source_ids))
        ).scalars()
    ) if source_ids else []
    grouped_rows: dict[tuple[int, str], list[ProductIngredient]] = {}
    for product_row in product_rows:
        grouped_rows.setdefault(
            (int(product_row.ingredient_id), normalize_source_name(product_row.ingredient_name)), []
        ).append(product_row)

    reviews = list(
        session.execute(
            select(IngredientMappingReview).where(IngredientMappingReview.source_ingredient_id.in_(source_ids))
        ).scalars()
    ) if source_ids else []
    reviews_by_key = {
        (int(review.source_ingredient_id), review.normalized_source_name): review for review in reviews
    }
    identity_counts: dict[tuple[str, str], int] = {}
    create_definitions: dict[str, tuple[str, str]] = {}
    for row in rows:
        key = (row.pending_code.strip(), row.normalized_source_name)
        identity_counts[key] = identity_counts.get(key, 0) + 1
        if row.action == "CREATE_AND_MAP":
            definition = ((row.target_name_ko or "").strip(), (row.target_name_en or "").strip())
            previous = create_definitions.setdefault(row.target_ingredient_code.strip(), definition)
            if previous != definition:
                create_definitions[row.target_ingredient_code.strip()] = ("__CONFLICT__", "")

    preview_rows: list[IngredientMappingCsvPreviewRow] = []
    contexts: list[_RowContext] = []
    for row in rows:
        source = sources.get(row.pending_code.strip())
        target = targets.get(row.target_ingredient_code.strip())
        matched_rows = (
            grouped_rows.get((int(source.id), row.normalized_source_name), []) if source is not None else []
        )
        review = (
            reviews_by_key.get((int(source.id), row.normalized_source_name)) if source is not None else None
        )
        status = "VALID"
        error_code = message = None
        already_applied = False

        def invalidate(code: str, detail: str) -> None:
            nonlocal status, error_code, message
            if status == "VALID":
                status, error_code, message = "INVALID", code, detail

        if identity_counts[(row.pending_code.strip(), row.normalized_source_name)] > 1:
            invalidate("DUPLICATE_MAPPING_GROUP", "같은 pending 그룹이 파일에 중복되어 있습니다.")
        if row.normalized_source_name != normalize_source_name(row.normalized_source_name):
            invalidate(
                "INVALID_NORMALIZED_SOURCE_NAME",
                "normalized_source_name은 export 원문을 수정하지 않고 사용해야 합니다.",
            )
        if source is None:
            invalidate("PENDING_NOT_FOUND", "운영 DB에서 pending 성분을 찾을 수 없습니다.")
        elif not source.ingredient_code.startswith(("ing_pending_", "foreign_pending_")):
            invalidate("SOURCE_NOT_PENDING", "source 성분이 pending 상태가 아닙니다.")

        if row.action == "MAP_EXISTING":
            if target is None:
                invalidate("TARGET_NOT_FOUND", "기존 canonical 성분을 찾을 수 없습니다.")
        else:
            if not row.target_ingredient_code.startswith("ing_") or row.target_ingredient_code.startswith("ing_pending_"):
                invalidate("INVALID_NEW_CANONICAL_CODE", "신규 canonical 코드는 ing_로 시작해야 합니다.")
            if not (row.target_name_ko or "").strip():
                invalidate("TARGET_NAME_REQUIRED", "신규 canonical의 target_name_ko가 필요합니다.")
            if not (row.source_reference or "").strip():
                invalidate("SOURCE_REFERENCE_REQUIRED", "신규 canonical 생성 근거가 필요합니다.")
            if create_definitions.get(row.target_ingredient_code.strip()) == ("__CONFLICT__", ""):
                invalidate("NEW_CANONICAL_DEFINITION_CONFLICT", "같은 canonical 코드의 이름 정의가 서로 다릅니다.")
            if target is not None and target.name_ko != (row.target_name_ko or "").strip():
                invalidate("TARGET_CODE_CONFLICT", "기존 canonical 코드의 이름이 CSV와 다릅니다.")

        if target is not None and (
            not target.is_active or target.ingredient_code.startswith(("ing_pending_", "foreign_pending_"))
        ):
            invalidate("TARGET_NOT_AVAILABLE", "활성 canonical 성분만 연결할 수 있습니다.")
        if review is not None and review.status == "APPROVED":
            if target is not None and review.target_ingredient_id == target.id and not matched_rows:
                status, error_code, message, already_applied = (
                    "ALREADY_APPLIED",
                    None,
                    "이미 같은 canonical로 적용된 행입니다.",
                    True,
                )
            elif target is not None and review.target_ingredient_id != target.id:
                invalidate("APPROVED_TARGET_CONFLICT", "이미 다른 canonical로 승인된 그룹입니다.")
        if not matched_rows and not already_applied:
            invalidate("MAPPING_GROUP_NOT_FOUND", "현재 운영 DB에 해당 원문 그룹이 없습니다.")
        if matched_rows and len(matched_rows) != row.expected_connection_count:
            invalidate("CONNECTION_COUNT_CHANGED", "연결 수가 export 시점과 달라졌습니다. 다시 export해 주세요.")

        target_name = target.name_ko if target is not None else (row.target_name_ko or None)
        preview_rows.append(
            IngredientMappingCsvPreviewRow(
                row_number=row.row_number,
                status=status,
                action=row.action,
                pending_code=row.pending_code,
                normalized_source_name=row.normalized_source_name,
                target_ingredient_code=row.target_ingredient_code,
                target_ingredient_name=target_name,
                expected_connection_count=row.expected_connection_count,
                current_connection_count=len(matched_rows),
                error_code=error_code,
                message=message,
            )
        )
        contexts.append(_RowContext(row, source, target, matched_rows, already_applied))

    summary = IngredientMappingCsvPreviewSummary(
        total=len(rows),
        valid=sum(item.status == "VALID" for item in preview_rows),
        invalid=sum(item.status == "INVALID" for item in preview_rows),
        already_applied=sum(item.status == "ALREADY_APPLIED" for item in preview_rows),
        connection_count=sum(item.current_connection_count for item in preview_rows if item.status == "VALID"),
    )
    return (
        IngredientMappingCsvPreviewResponse(
            preview_digest=preview_digest(rows), summary=summary, rows=preview_rows
        ),
        contexts,
    )
