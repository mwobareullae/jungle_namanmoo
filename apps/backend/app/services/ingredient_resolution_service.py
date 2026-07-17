"""신규 상품 성분 입력 공통 해소 서비스 (P1-M3-B Chunk 1 + M2-A2).

계약: docs/admin/admin-ingredient-input-minimum-contract.md
- §4 정규화: resolution_normalized_name = casefold + 공백 제거,
             review_lookup_name = lower + 공백 제거 (§5-2 키 분리)
- §5 순서: (1) 결정적 pending code 계산 (2) M2 판정 조회
           (3) canonical exact (4) high alias exact
           (5) 서로 다른 canonical 1개면 자동 연결 (6) 나머지는 pending
- §6 pending code: ing_pending_admin_<sha256(resolution_normalized)[:32]>
- §7 중복 제거: 해소된 ingredient_id 기준 첫 등장만 유지, display_order 재부여
- §8 트랜잭션: 서비스는 flush()까지만. commit/rollback은 호출자.
- §10 카운터, §11 오류 코드.

성능: 캐시·Redis는 이번 Chunk 밖. batch 조회로 N+1 회피.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import String, and_, column, func, or_, select, values
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.common import ApiError
from app.db.models.taxonomy import (
    Ingredient,
    IngredientAlias,
    IngredientMappingReview,
)


PENDING_ADMIN_PREFIX = "ing_pending_admin_"
_LEGACY_PENDING_PREFIXES = ("ing_pending_", "foreign_pending_")

MAX_RAW_NAME_LENGTH = 255
MAX_INGREDIENTS_PER_PRODUCT = 500
ALLOWED_CONFIDENCES = ("high", "medium", "low", "unknown")


MATCH_CANONICAL_NAME = "CANONICAL_NAME"
MATCH_ALIAS = "ALIAS"
MATCH_ADMIN_APPROVED = "ADMIN_APPROVED"
MATCH_EXISTING_PENDING = "EXISTING_PENDING"
MATCH_CREATED_PENDING = "CREATED_PENDING"

STATUS_CANONICAL = "CANONICAL"
STATUS_PENDING = "PENDING"


@dataclass(frozen=True)
class ResolutionInput:
    raw_name: str
    content_confidence: str = "unknown"


@dataclass(frozen=True)
class ResolutionResult:
    raw_name: str
    normalized_name: str
    ingredient_id: int
    ingredient_code: str
    resolution_status: str
    match_source: str
    display_order: int
    content_confidence: str


@dataclass
class ResolutionOutcome:
    results: list[ResolutionResult]
    counters: dict[str, int] = field(default_factory=dict)


def normalize_for_resolution(raw: str) -> str:
    """§4: casefold + 모든 공백 제거."""
    return "".join(raw.casefold().split())


def normalize_for_review_lookup(raw: str) -> str:
    """PostgreSQL이 아닌 테스트 환경용 review 키 fallback."""
    return "".join(raw.lower().split())


def compute_pending_code(resolution_normalized_name: str) -> str:
    """§6: 결정적 pending code. 같은 정규화 입력은 항상 같은 code."""
    digest = hashlib.sha256(resolution_normalized_name.encode("utf-8")).hexdigest()
    return f"{PENDING_ADMIN_PREFIX}{digest[:32]}"


def _is_legacy_pending(ingredient_code: str) -> bool:
    return ingredient_code.startswith(_LEGACY_PENDING_PREFIXES)


def _validate_inputs(inputs: list[ResolutionInput]) -> list[tuple[ResolutionInput, str]]:
    """§11 INVALID_INGREDIENT_INPUT: 빈 이름·255자 초과·500개 초과·허용 안 된 confidence.

    trim된 raw_name과 함께 반환한다. 빈 입력 목록은 그대로 통과한다.
    """
    if len(inputs) > MAX_INGREDIENTS_PER_PRODUCT:
        raise ApiError(
            400,
            "INVALID_INGREDIENT_INPUT",
            f"성분 입력은 최대 {MAX_INGREDIENTS_PER_PRODUCT}개까지 허용합니다.",
        )
    trimmed: list[tuple[ResolutionInput, str]] = []
    for index, item in enumerate(inputs):
        if item.content_confidence not in ALLOWED_CONFIDENCES:
            raise ApiError(
                400,
                "INVALID_INGREDIENT_INPUT",
                f"허용되지 않은 content_confidence: {item.content_confidence!r} (index={index}).",
            )
        raw = (item.raw_name or "").strip()
        if not raw:
            raise ApiError(
                400,
                "INVALID_INGREDIENT_INPUT",
                f"빈 성분 이름 (index={index}).",
            )
        if len(raw) > MAX_RAW_NAME_LENGTH:
            raise ApiError(
                400,
                "INVALID_INGREDIENT_INPUT",
                f"성분 이름은 {MAX_RAW_NAME_LENGTH}자 이하여야 합니다 (index={index}).",
            )
        trimmed.append((item, raw))
    return trimmed


def _load_pending_by_code(session: Session, codes: set[str]) -> dict[str, Ingredient]:
    if not codes:
        return {}
    rows = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code.in_(codes))
    ).scalars().all()
    return {row.ingredient_code: row for row in rows}


def _load_reviews(
    session: Session,
    source_ids: set[int],
    review_lookup_names: set[str],
) -> dict[tuple[int, str], IngredientMappingReview]:
    if not source_ids or not review_lookup_names:
        return {}
    rows = session.execute(
        select(IngredientMappingReview).where(
            and_(
                IngredientMappingReview.source_ingredient_id.in_(source_ids),
                IngredientMappingReview.normalized_source_name.in_(review_lookup_names),
            )
        )
    ).scalars().all()
    return {(row.source_ingredient_id, row.normalized_source_name): row for row in rows}


def _load_active_ingredients_by_ids(
    session: Session, ids: set[int]
) -> dict[int, Ingredient]:
    if not ids:
        return {}
    rows = session.execute(
        select(Ingredient).where(
            and_(
                Ingredient.id.in_(ids),
                Ingredient.is_active.is_(True),
                ~or_(
                    Ingredient.ingredient_code.like("ing_pending_%"),
                    Ingredient.ingredient_code.like("foreign_pending_%"),
                ),
            )
        )
    ).scalars().all()
    return {row.id: row for row in rows}


def _postgres_review_lookup_expression(raw_name: object):
    """0048 matview와 동일한 PostgreSQL review 키 식."""
    return func.lower(
        func.regexp_replace(
            func.coalesce(raw_name, ""),
            r"\s+",
            "",
            "g",
        )
    )


def _compute_review_lookup_names(
    session: Session, raw_names: set[str]
) -> dict[str, str]:
    """원문마다 M2 review·matview와 동일한 키를 한 번에 계산한다.

    운영 PostgreSQL에서는 0048의 ``lower(regexp_replace(...))`` 식을 그대로
    실행한다. SQLite focused test에서는 해당 함수가 없으므로, 같은 의도의
    Python fallback을 사용한다.
    """
    if not raw_names:
        return {}

    if session.get_bind().dialect.name != "postgresql":
        return {raw_name: normalize_for_review_lookup(raw_name) for raw_name in raw_names}

    input_rows = (
        values(
            column("raw_name", String(255)),
            name="ingredient_review_lookup_inputs",
        )
        .data([(raw_name,) for raw_name in raw_names])
        .alias("ingredient_review_lookup_inputs")
    )
    rows = session.execute(
        select(
            input_rows.c.raw_name,
            _postgres_review_lookup_expression(input_rows.c.raw_name).label(
                "review_lookup_name"
            ),
        )
    ).all()
    return {raw_name: review_lookup_name for raw_name, review_lookup_name in rows}


def _load_canonical_by_normalized(
    session: Session, normalized_names: set[str]
) -> dict[str, list[Ingredient]]:
    """§5-3: 활성 canonical 중 normalized_name 일치. pending prefix는 제외."""
    if not normalized_names:
        return {}
    rows = session.execute(
        select(Ingredient).where(
            and_(
                Ingredient.is_active.is_(True),
                Ingredient.normalized_name.in_(normalized_names),
                ~or_(
                    Ingredient.ingredient_code.like("ing_pending_%"),
                    Ingredient.ingredient_code.like("foreign_pending_%"),
                ),
            )
        )
    ).scalars().all()
    grouped: dict[str, list[Ingredient]] = defaultdict(list)
    for row in rows:
        if row.normalized_name is not None:
            grouped[row.normalized_name].append(row)
    return grouped


def _load_high_alias_by_normalized(
    session: Session, normalized_names: set[str]
) -> dict[str, list[Ingredient]]:
    """§5-4: confidence='high' alias가 가리키는 활성 canonical. alias_type 무관.

    (사람이 high로 검증한 abbrev/typo도 포함 — 실측 근거: BHA, AHA, PHA, 징크PCA 등)
    """
    if not normalized_names:
        return {}
    stmt = (
        select(Ingredient, IngredientAlias.normalized_alias)
        .join(IngredientAlias, IngredientAlias.ingredient_id == Ingredient.id)
        .where(
            and_(
                IngredientAlias.confidence == "high",
                IngredientAlias.normalized_alias.in_(normalized_names),
                Ingredient.is_active.is_(True),
                ~or_(
                    Ingredient.ingredient_code.like("ing_pending_%"),
                    Ingredient.ingredient_code.like("foreign_pending_%"),
                ),
            )
        )
    )
    grouped: dict[str, list[Ingredient]] = defaultdict(list)
    for ingredient, normalized_alias in session.execute(stmt).all():
        grouped[normalized_alias].append(ingredient)
    return grouped


def _create_pending(
    session: Session,
    *,
    pending_code: str,
    raw_name: str,
    resolution_normalized_name: str,
) -> Ingredient:
    """§6 신규 pending: name_ko=trim(raw), name_en=null, is_active=true."""
    pending = Ingredient(
        ingredient_code=pending_code,
        name_ko=raw_name,
        name_en=None,
        normalized_name=resolution_normalized_name,
        is_active=True,
    )
    session.add(pending)
    session.flush()
    return pending


def _create_or_reuse_pending(
    session: Session,
    *,
    pending_code: str,
    raw_name: str,
    resolution_normalized_name: str,
) -> tuple[Ingredient, bool]:
    """결정적 pending을 만들거나, 동시 생성된 동일 행을 안전하게 재사용한다.

    별도 관리자 요청이 같은 code를 동시에 만들면 PostgreSQL unique 제약이
    최종 방어선이 된다. savepoint 안에서 충돌을 분리한 뒤 행을 다시 읽어
    재사용하므로 호출자의 상품 트랜잭션 전체를 rollback하지 않는다.
    """
    try:
        with session.begin_nested():
            pending = _create_pending(
                session,
                pending_code=pending_code,
                raw_name=raw_name,
                resolution_normalized_name=resolution_normalized_name,
            )
        return pending, True
    except IntegrityError as error:
        pending = _load_pending_by_code(session, {pending_code}).get(pending_code)
        if pending is None:
            raise error
        if pending.normalized_name != resolution_normalized_name:
            raise ApiError(
                409,
                "INGREDIENT_PENDING_CODE_CONFLICT",
                f"pending code {pending_code}의 normalized_name이 계산값과 다릅니다.",
            ) from error
        return pending, False


def resolve_many(
    session: Session, inputs: Iterable[ResolutionInput]
) -> ResolutionOutcome:
    """상품 하나의 성분 입력 목록을 계약 §5 순서로 해소한다.

    호출자는 반환된 결과의 (raw_name, ingredient_id, display_order 등)로
    ProductIngredient를 저장한다. 서비스는 pending 생성까지 flush 만 한다.
    """
    input_list = list(inputs)
    validated = _validate_inputs(input_list)
    input_count = len(input_list)

    if not validated:
        return ResolutionOutcome(
            results=[],
            counters={
                "input_count": 0,
                "saved_count": 0,
                "canonical_count": 0,
                "pending_count": 0,
                "duplicate_count": 0,
                "created_pending_count": 0,
            },
        )

    # (1) 각 입력의 두 키와 pending code 계산.
    per_input: list[dict] = []
    raw_names: set[str] = set()
    pending_codes: set[str] = set()
    for item, raw in validated:
        resolution = normalize_for_resolution(raw)
        code = compute_pending_code(resolution)
        per_input.append(
            {
                "input": item,
                "raw": raw,
                "resolution": resolution,
                "pending_code": code,
            }
        )
        raw_names.add(raw)
        pending_codes.add(code)

    review_lookup_by_raw = _compute_review_lookup_names(session, raw_names)
    review_names = set(review_lookup_by_raw.values())
    for entry in per_input:
        entry["review"] = review_lookup_by_raw[entry["raw"]]

    # (2) 결정적 pending 배치 조회. code가 이미 있으면 normalized_name 검증 — §6.
    existing_pendings = _load_pending_by_code(session, pending_codes)
    for entry in per_input:
        candidate = existing_pendings.get(entry["pending_code"])
        if candidate is not None and candidate.normalized_name != entry["resolution"]:
            raise ApiError(
                409,
                "INGREDIENT_PENDING_CODE_CONFLICT",
                (
                    f"pending code {entry['pending_code']}의 normalized_name이"
                    " 계산값과 다릅니다."
                ),
            )

    # (3) M2-A2: 이미 존재하는 pending에 대해서만 판정 조회.
    existing_source_ids = {row.id for row in existing_pendings.values()}
    reviews = _load_reviews(session, existing_source_ids, review_names)

    # APPROVED target 활성 canonical 검증용 — 필요한 id만 모아 배치 조회.
    target_ids: set[int] = set()
    for entry in per_input:
        pending = existing_pendings.get(entry["pending_code"])
        if pending is None:
            continue
        review = reviews.get((pending.id, entry["review"]))
        if review and review.status == "APPROVED" and review.target_ingredient_id is not None:
            target_ids.add(review.target_ingredient_id)
    target_ingredients = _load_active_ingredients_by_ids(session, target_ids)

    # (4a) 1차: 판정 우선 결정. 판정으로 결정된 항목은 자동 룩업을 건너뛴다 (§5 순서).
    per_input_result: list[dict | None] = [None] * len(per_input)
    for index, entry in enumerate(per_input):
        pending = existing_pendings.get(entry["pending_code"])
        if pending is None:
            continue
        review = reviews.get((pending.id, entry["review"]))
        if review is None:
            continue
        if review.status == "APPROVED":
            target = target_ingredients.get(review.target_ingredient_id)
            if target is not None:
                per_input_result[index] = {
                    "entry": entry,
                    "ingredient": target,
                    "resolution_status": STATUS_CANONICAL,
                    "match_source": MATCH_ADMIN_APPROVED,
                }
            else:
                # target이 비활성/pending이면 자동 해소하지 않고 pending 유지 (§5 원칙).
                per_input_result[index] = {
                    "entry": entry,
                    "ingredient": pending,
                    "resolution_status": STATUS_PENDING,
                    "match_source": MATCH_EXISTING_PENDING,
                }
        elif review.status in ("HELD", "REJECTED"):
            # 관리자 재검토 전 자동 해소하지 않는다.
            per_input_result[index] = {
                "entry": entry,
                "ingredient": pending,
                "resolution_status": STATUS_PENDING,
                "match_source": MATCH_EXISTING_PENDING,
            }

    # (4b) 판정으로 결정되지 않은 입력의 정규화 키만으로 canonical·high alias 조회.
    undecided_resolutions = {
        per_input[i]["resolution"]
        for i, decided in enumerate(per_input_result)
        if decided is None
    }
    canonical_by_norm = _load_canonical_by_normalized(session, undecided_resolutions)
    alias_by_norm = _load_high_alias_by_normalized(session, undecided_resolutions)

    # (5·6) 2차: 나머지 결정. 필요 시 신규 pending 생성.
    created_pending_count = 0
    for index, entry in enumerate(per_input):
        if per_input_result[index] is not None:
            continue

        canonical_hits = canonical_by_norm.get(entry["resolution"], [])
        alias_hits = alias_by_norm.get(entry["resolution"], [])
        unique_ids: dict[int, tuple[Ingredient, str]] = {}
        for hit in canonical_hits:
            unique_ids[hit.id] = (hit, MATCH_CANONICAL_NAME)
        for hit in alias_hits:
            # canonical 이름과 alias가 같은 canonical → CANONICAL_NAME 로 기록 (§5 표 아래 규칙).
            if hit.id not in unique_ids:
                unique_ids[hit.id] = (hit, MATCH_ALIAS)

        if len(unique_ids) == 1:
            ingredient, source = next(iter(unique_ids.values()))
            per_input_result[index] = {
                "entry": entry,
                "ingredient": ingredient,
                "resolution_status": STATUS_CANONICAL,
                "match_source": source,
            }
            continue

        # 0개 또는 2개 이상 → pending 사용/생성.
        pending = existing_pendings.get(entry["pending_code"])
        if pending is not None:
            per_input_result[index] = {
                "entry": entry,
                "ingredient": pending,
                "resolution_status": STATUS_PENDING,
                "match_source": MATCH_EXISTING_PENDING,
            }
        else:
            new_pending, created = _create_or_reuse_pending(
                session,
                pending_code=entry["pending_code"],
                raw_name=entry["raw"],
                resolution_normalized_name=entry["resolution"],
            )
            # 같은 요청 안에서 같은 code가 이어지면 재사용할 수 있게 캐시에 넣는다.
            existing_pendings[entry["pending_code"]] = new_pending
            if created:
                created_pending_count += 1
            per_input_result[index] = {
                "entry": entry,
                "ingredient": new_pending,
                "resolution_status": STATUS_PENDING,
                "match_source": MATCH_CREATED_PENDING if created else MATCH_EXISTING_PENDING,
            }

    # (7) §7 중복 제거: 해소된 ingredient_id 기준 첫 등장만 유지, display_order 재부여.
    seen: set[int] = set()
    results: list[ResolutionResult] = []
    duplicate_count = 0
    display_order = 0
    canonical_count = 0
    pending_count = 0
    for row in per_input_result:
        ingredient = row["ingredient"]
        if ingredient.id in seen:
            duplicate_count += 1
            continue
        seen.add(ingredient.id)
        display_order += 1
        if row["resolution_status"] == STATUS_CANONICAL:
            canonical_count += 1
        else:
            pending_count += 1
        entry = row["entry"]
        results.append(
            ResolutionResult(
                raw_name=entry["raw"],
                normalized_name=entry["resolution"],
                ingredient_id=ingredient.id,
                ingredient_code=ingredient.ingredient_code,
                resolution_status=row["resolution_status"],
                match_source=row["match_source"],
                display_order=display_order,
                content_confidence=entry["input"].content_confidence,
            )
        )

    return ResolutionOutcome(
        results=results,
        counters={
            "input_count": input_count,
            "saved_count": len(results),
            "canonical_count": canonical_count,
            "pending_count": pending_count,
            "duplicate_count": duplicate_count,
            "created_pending_count": created_pending_count,
        },
    )
