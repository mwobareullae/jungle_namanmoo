"""관리자 성분 매핑 검수 조회 서비스 (P1-M2-A, 조회 전용).

DB에는 관리자 판정(`ingredient_mapping_reviews`)만 저장한다. 목록·summary는
`ingredient_mapping_pending_groups` materialized view를 읽고, 상세만 원본
`product_ingredients`에서 단일 pending 성분을 조회한다. review를 LEFT JOIN 해
상태(없으면 파생 PENDING)를 붙인다. 추천(`suggestion`)은 조회
시점의 읽기 전용 정보로 alias/canonical 이름 정확 일치만 소스로 쓴다.

정규화 정합성(중요): 목록 그룹핑과 판정 저장(`normalized_source_name`)은 모두
PostgreSQL `lower`(대소문자 무시 + 공백 제거) 기준으로 통일한다. Python 쪽
동일 규칙은 `normalize_source_name()`. suggestion 매칭은 seed 가 casefold 로
저장한 alias/canonical 과 비교하므로 라틴 합자 등 극소수 원문에서 추천이 드물게
누락될 수 있으나(읽기 전용·무시 가능), 판정 정확성에는 영향이 없다. 상세 계약은
`docs/admin/admin-m2a-ingredient-mapping-api-contract.md` 참조.
"""

import base64
import binascii
import json

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.schemas.admin.ingredient_mapping import (
    IngredientMappingDecision,
    IngredientMappingCandidate,
    IngredientMappingDetail,
    IngredientMappingEvent,
    IngredientMappingListItem,
    CanonicalIngredientSearchItem,
    CanonicalIngredientSearchResponse,
    IngredientMappingListResponse,
    IngredientMappingRawNameVariant,
    IngredientMappingSampleProduct,
    IngredientMappingSuggestion,
    IngredientMappingSummary,
)
from app.schemas.common import ApiError


DEFAULT_LIMIT = 50
MAX_LIMIT = 100
DEFAULT_SORT = "CODE_ASC"
VALID_SORTS = frozenset({"CODE_ASC", "CONNECTION_DESC"})
VALID_CANDIDATE_TYPES = frozenset({"CANONICAL_EXACT_MATCH", "ALIAS_EXACT_MATCH", "EXACT_MATCH_CONFLICT", "NO_EXACT_MATCH"})

CANONICAL_SEARCH_DEFAULT_LIMIT = 20
CANONICAL_SEARCH_MAX_LIMIT = 50

VALID_STATUS_FILTERS = frozenset({"PENDING", "HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"})
STORED_STATUSES = frozenset({"HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"})
VALID_FINAL_DISPOSITION_FILTERS = frozenset(
    {"MAPPED", "NON_INGREDIENT", "COMPOUND_MATERIAL", "SOURCE_ERROR", "UNRESOLVABLE"}
)

CURSOR_VERSION = 2
LIST_CURSOR_VERSION = 4

# 목록·상세·판정 저장이 공유하는 정규화 SQL. lower + 모든 공백 제거.
# Python normalize_source_name() 과 반드시 동일 결과를 내야 한다(정규화 정합성).
_NORMALIZE_SQL = r"lower(regexp_replace(coalesce({col}, ''), '\s+', '', 'g'))"

# pending 성분 판별. 기존 컨벤션(search_index_builder._is_pending_code)과 동일 접두어.
_PENDING_PREDICATE = (
    "(i.ingredient_code like 'ing_pending_%' or i.ingredient_code like 'foreign_pending_%')"
)

_ACTIONS_BY_STATUS: dict[str, list[str]] = {
    "PENDING": ["APPROVE", "HOLD", "REJECT"],
    "HELD": ["APPROVE", "REJECT"],
    "NEEDS_REVIEW": ["APPROVE", "HOLD", "REJECT"],
    "APPROVED": ["REOPEN"],
    "REJECTED": ["REOPEN"],
}


def normalize_source_name(raw_name: str | None) -> str:
    """목록 그룹핑 SQL(`_NORMALIZE_SQL`)과 동일 규칙의 Python 정규화.

    lower + 모든 공백 제거. 판정 저장 시 review 키도 이 값을 쓴다.
    """

    return "".join((raw_name or "").lower().split())


# --- 커서 -----------------------------------------------------------------

def _encode_cursor(
    pending_code: str,
    normalized_source_name: str,
    *,
    status: str | None,
    final_disposition: str | None,
    q: str,
    sort: str = DEFAULT_SORT,
    candidate_type: str | None = None,
    connection_count: int = 0,
) -> str:
    payload = {
        "v": LIST_CURSOR_VERSION,
        "pc": pending_code,
        "nsn": normalized_source_name,
        "st": status or "",
        "fd": final_disposition or "",
        "q": q,
        "so": sort,
        "ct": candidate_type or "",
        "cc": connection_count,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(
    cursor: str,
    *,
    status: str | None,
    final_disposition: str | None,
    q: str,
    sort: str = DEFAULT_SORT,
    candidate_type: str | None = None,
) -> tuple[str, str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}".encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.") from exc
    if not isinstance(payload, dict) or payload.get("v") != LIST_CURSOR_VERSION:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    pending_code = payload.get("pc")
    normalized_source_name = payload.get("nsn")
    connection_count = payload.get("cc")
    if (
        not isinstance(pending_code, str)
        or not isinstance(normalized_source_name, str)
        or not isinstance(connection_count, int)
        or connection_count < 0
    ):
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    # 필터가 페이지 사이에 바뀌면 커서 위치가 무의미하므로 거부한다(계약 §4).
    if (
        payload.get("st") != (status or "")
        or payload.get("fd") != (final_disposition or "")
        or payload.get("q") != q
        or payload.get("so") != sort
        or payload.get("ct") != (candidate_type or "")
    ):
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    return pending_code, normalized_source_name, connection_count


# --- 검증 -----------------------------------------------------------------

def _normalize_status_filter(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().upper()
    if not normalized:
        return None
    if normalized not in VALID_STATUS_FILTERS:
        raise ApiError(400, "INVALID_INGREDIENT_MAPPING_STATUS", "Invalid status filter.")
    return normalized


def _normalize_final_disposition_filter(final_disposition: str | None) -> str | None:
    if final_disposition is None:
        return None
    normalized = final_disposition.strip().upper()
    if not normalized:
        return None
    if normalized not in VALID_FINAL_DISPOSITION_FILTERS:
        raise ApiError(400, "INVALID_INGREDIENT_MAPPING_FINAL_DISPOSITION", "Invalid final disposition filter.")
    return normalized


def _normalize_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError(400, "INVALID_LIMIT", "Invalid limit.")
    return limit


def _normalize_sort(sort: str | None) -> str:
    normalized = (sort or DEFAULT_SORT).strip().upper()
    if not normalized:
        return DEFAULT_SORT
    if normalized not in VALID_SORTS:
        raise ApiError(400, "INVALID_INGREDIENT_MAPPING_SORT", "Invalid ingredient mapping sort.")
    return normalized


def _normalize_candidate_type(candidate_type: str | None) -> str | None:
    if candidate_type is None:
        return None
    normalized = candidate_type.strip().upper()
    if not normalized:
        return None
    if normalized not in VALID_CANDIDATE_TYPES:
        raise ApiError(400, "INVALID_INGREDIENT_MAPPING_CANDIDATE", "Invalid ingredient mapping candidate.")
    return normalized


def _normalize_q(q: str | None) -> str:
    return (q or "").strip()


# --- 그룹/판정 매핑 --------------------------------------------------------

def _build_suggestion(
    normalized_source_name: str,
    alias_hits: dict[str, tuple[int, str, str]],
    canonical_hits: dict[str, tuple[int, str, str]],
) -> IngredientMappingSuggestion | None:
    """alias/canonical 정확 일치를 병합해 단일 추천을 만든다(계약 §3-1).

    alias 후보(전역 UNIQUE라 ≤1) 우선. 서로 다른 canonical 이 둘 이상이면 None.
    """

    alias = alias_hits.get(normalized_source_name)
    canonical = canonical_hits.get(normalized_source_name)
    if alias is not None:
        # alias 와 canonical 이 다른 target 을 가리키면 오매핑 방지로 None.
        if canonical is not None and canonical[0] != alias[0]:
            return None
        target_id, code, name = alias
        return IngredientMappingSuggestion(
            target_ingredient_id=target_id,
            target_ingredient_code=code,
            target_ingredient_name=name,
            match_source="ALIAS_EXACT",
        )
    if canonical is not None:
        target_id, code, name = canonical
        return IngredientMappingSuggestion(
            target_ingredient_id=target_id,
            target_ingredient_code=code,
            target_ingredient_name=name,
            match_source="CANONICAL_NAME_EXACT",
        )
    return None


def _build_candidate(
    normalized_source_name: str,
    alias_hits: dict[str, tuple[int, str, str]],
    canonical_hits: dict[str, tuple[int, str, str]],
    canonical_conflicts: set[str],
) -> IngredientMappingCandidate:
    """정확 일치 정보만으로 읽기 전용 처리 후보와 근거를 만든다."""

    alias = alias_hits.get(normalized_source_name)
    canonical = canonical_hits.get(normalized_source_name)
    if normalized_source_name in canonical_conflicts or (
        alias is not None and canonical is not None and alias[0] != canonical[0]
    ):
        return IngredientMappingCandidate(
            candidate_type="EXACT_MATCH_CONFLICT",
            evidence="정규화 원문과 정확히 일치하는 정식명 또는 별칭 후보가 서로 충돌합니다.",
        )
    if alias is not None:
        return IngredientMappingCandidate(
            candidate_type="ALIAS_EXACT_MATCH",
            evidence="정규화 원문이 등록된 성분 별칭과 정확히 일치합니다.",
        )
    if canonical is not None:
        return IngredientMappingCandidate(
            candidate_type="CANONICAL_EXACT_MATCH",
            evidence="정규화 원문이 활성 정식 성분명과 정확히 일치합니다.",
        )
    return IngredientMappingCandidate(
        candidate_type="NO_EXACT_MATCH",
        evidence="등록된 정식 성분명 또는 별칭의 정확 일치가 없어 근거 확인이 필요합니다.",
    )


def _decision_from_row(row: object) -> IngredientMappingDecision | None:
    status = getattr(row, "review_status", None)
    if status is None:
        return None
    return IngredientMappingDecision(
        status=status,
        final_disposition=getattr(row, "final_disposition", None),
        target_ingredient_code=getattr(row, "target_ingredient_code", None),
        target_ingredient_name=getattr(row, "target_ingredient_name", None),
        decision_reason=getattr(row, "decision_reason", None),
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=row.reviewed_at,
    )


def _effective_status(review_status: str | None) -> str:
    return review_status if review_status in STORED_STATUSES else "PENDING"


def _load_page_suggestions(
    session: Session, normalized_names: list[str]
) -> tuple[dict[str, tuple[int, str, str]], dict[str, tuple[int, str, str]], set[str]]:
    """현재 페이지 정규화명들의 alias/canonical 정확 일치를 묶음 조회(고정 2쿼리)."""

    if not normalized_names:
        return {}, {}, set()
    unique_names = list(dict.fromkeys(normalized_names))

    alias_stmt = text(
        """
        select a.normalized_alias as nsn, ing.id as target_id,
               ing.ingredient_code as target_code, ing.name_ko as target_name
        from ingredient_aliases a
        join ingredients ing on ing.id = a.ingredient_id
        where a.normalized_alias in :names
          and ing.is_active = true
          and ing.ingredient_code not like 'ing_pending_%'
          and ing.ingredient_code not like 'foreign_pending_%'
        """
    ).bindparams(bindparam("names", expanding=True))
    canonical_stmt = text(
        """
        select ing.normalized_name as nsn, ing.id as target_id,
               ing.ingredient_code as target_code, ing.name_ko as target_name
        from ingredients ing
        where ing.normalized_name in :names
          and ing.is_active = true
          and ing.ingredient_code not like 'ing_pending_%'
          and ing.ingredient_code not like 'foreign_pending_%'
        """
    ).bindparams(bindparam("names", expanding=True))

    alias_hits: dict[str, tuple[int, str, str]] = {}
    for r in session.execute(alias_stmt, {"names": unique_names}):
        # 전역 UNIQUE normalized_alias 라 정규화명당 최대 1행.
        alias_hits[r.nsn] = (int(r.target_id), r.target_code, r.target_name)

    canonical_hits: dict[str, tuple[int, str, str]] = {}
    canonical_conflicts: set[str] = set()
    for r in session.execute(canonical_stmt, {"names": unique_names}):
        # normalized_name 은 전역 UNIQUE 가 아니다. 서로 다른 target 이 2개 이상이면
        # 오매핑 방지로 추천을 만들지 않는다(sentinel 로 표시).
        existing = canonical_hits.get(r.nsn)
        target_id = int(r.target_id)
        if existing is not None and existing[0] != target_id:
            canonical_hits[r.nsn] = (-1, "", "")  # 충돌 sentinel → _build_suggestion 에서 무시
            canonical_conflicts.add(r.nsn)
            continue
        if existing is None:
            canonical_hits[r.nsn] = (target_id, r.target_code, r.target_name)
    # 충돌 sentinel 제거(서로 다른 canonical 2개 이상 → suggestion 없음)
    canonical_hits = {k: v for k, v in canonical_hits.items() if v[0] != -1}
    return alias_hits, canonical_hits, canonical_conflicts


# --- 목록 -----------------------------------------------------------------

_LIST_CANDIDATE_SQL = text(
    """
    select g.pending_code, g.normalized_source_name as nsn, g.connection_count,
           g.raw_name,
           rev.id as review_id, rev.status as review_status,
           rev.target_ingredient_id, rev.final_disposition, rev.decision_reason,
           rev.reviewed_by_user_id, rev.reviewed_at,
           tgt.ingredient_code as target_ingredient_code, tgt.name_ko as target_ingredient_name
    from ingredient_mapping_pending_groups g
    left join ingredient_mapping_reviews rev
           on rev.source_ingredient_id = g.source_ingredient_id
          and rev.normalized_source_name = g.normalized_source_name
    left join ingredients tgt on tgt.id = rev.target_ingredient_id
    left join lateral (
        select ing.id as target_id
        from ingredient_aliases a
        join ingredients ing on ing.id = a.ingredient_id
        where a.normalized_alias = g.normalized_source_name
          and ing.is_active = true
          and ing.ingredient_code not like 'ing_pending_%'
          and ing.ingredient_code not like 'foreign_pending_%'
        limit 1
    ) alias_match on true
    left join lateral (
        select count(*)::integer as match_count, min(ing.id) as target_id
        from ingredients ing
        where ing.normalized_name = g.normalized_source_name
          and ing.is_active = true
          and ing.ingredient_code not like 'ing_pending_%'
          and ing.ingredient_code not like 'foreign_pending_%'
    ) canonical_match on true
    cross join lateral (
        select case
            when canonical_match.match_count > 1
              or (alias_match.target_id is not null
                  and canonical_match.match_count = 1
                  and alias_match.target_id <> canonical_match.target_id)
                then 'EXACT_MATCH_CONFLICT'
            when alias_match.target_id is not null then 'ALIAS_EXACT_MATCH'
            when canonical_match.match_count = 1 then 'CANONICAL_EXACT_MATCH'
            else 'NO_EXACT_MATCH'
        end as candidate_type
    ) candidate_match
    where
        (cast(:status as text) is null
         or (cast(:status as text) = 'PENDING' and rev.id is null)
         or (cast(:status as text) <> 'PENDING' and rev.status = cast(:status as text)))
        and (cast(:final_disposition as text) is null
             or rev.final_disposition = cast(:final_disposition as text))
        and (cast(:status as text) is not null
             or cast(:final_disposition as text) is not null
             or rev.id is null
             or rev.status in ('HELD', 'NEEDS_REVIEW'))
        and (cast(:q as text) = ''
             or g.pending_code ilike cast(:q_like as text)
             or g.normalized_source_name ilike cast(:q_like as text)
             or g.raw_name ilike cast(:q_like as text))
        and (cast(:candidate_type as text) is null
             or candidate_match.candidate_type = cast(:candidate_type as text))
        and (cast(:cursor_pc as text) is null
             or (
                 (:sort = 'CODE_ASC' and (g.pending_code, g.normalized_source_name) > (
                     cast(:cursor_pc as text), cast(:cursor_nsn as text)
                 ))
                 or (
                     :sort = 'CONNECTION_DESC'
                     and (
                         g.connection_count < cast(:cursor_connection_count as integer)
                         or (
                             g.connection_count = cast(:cursor_connection_count as integer)
                             and (g.pending_code, g.normalized_source_name) > (
                                 cast(:cursor_pc as text), cast(:cursor_nsn as text)
                             )
                         )
                     )
                 )
             ))
    order by
        case when :sort = 'CONNECTION_DESC' then g.connection_count end desc,
        g.pending_code asc,
        g.normalized_source_name asc
    limit :limit_plus_one
    """
)

_LIST_SQL = text(
    """
    select g.pending_code, g.normalized_source_name as nsn, g.connection_count,
           g.raw_name,
           rev.id as review_id, rev.status as review_status,
           rev.target_ingredient_id, rev.final_disposition, rev.decision_reason,
           rev.reviewed_by_user_id, rev.reviewed_at,
           tgt.ingredient_code as target_ingredient_code, tgt.name_ko as target_ingredient_name
    from ingredient_mapping_pending_groups g
    left join ingredient_mapping_reviews rev
           on rev.source_ingredient_id = g.source_ingredient_id
          and rev.normalized_source_name = g.normalized_source_name
    left join ingredients tgt on tgt.id = rev.target_ingredient_id
    where
        (cast(:status as text) is null
         or (cast(:status as text) = 'PENDING' and rev.id is null)
         or (cast(:status as text) <> 'PENDING' and rev.status = cast(:status as text)))
        and (cast(:final_disposition as text) is null
             or rev.final_disposition = cast(:final_disposition as text))
        and (cast(:status as text) is not null
             or cast(:final_disposition as text) is not null
             or rev.id is null
             or rev.status in ('HELD', 'NEEDS_REVIEW'))
        and (cast(:q as text) = ''
             or g.pending_code ilike cast(:q_like as text)
             or g.normalized_source_name ilike cast(:q_like as text)
             or g.raw_name ilike cast(:q_like as text))
        and (cast(:cursor_pc as text) is null
             or (
                 (:sort = 'CODE_ASC' and (g.pending_code, g.normalized_source_name) > (
                     cast(:cursor_pc as text), cast(:cursor_nsn as text)
                 ))
                 or (
                     :sort = 'CONNECTION_DESC'
                     and (
                         g.connection_count < cast(:cursor_connection_count as integer)
                         or (
                             g.connection_count = cast(:cursor_connection_count as integer)
                             and (g.pending_code, g.normalized_source_name) > (
                                 cast(:cursor_pc as text), cast(:cursor_nsn as text)
                             )
                         )
                     )
                 )
             ))
    order by
        case when :sort = 'CONNECTION_DESC' then g.connection_count end desc,
        g.pending_code asc,
        g.normalized_source_name asc
    limit :limit_plus_one
    """
)

_SUMMARY_SQL = text(
    """
    select
        count(*) filter (where rev.status is null) as pending_count,
        count(*) filter (where rev.status = 'HELD') as held_count,
        count(*) filter (where rev.status = 'NEEDS_REVIEW') as needs_review_count,
        count(*) filter (where rev.status is null or rev.status in ('HELD', 'NEEDS_REVIEW')) as unclassified_count,
        count(*) filter (where rev.status = 'APPROVED') as approved_count,
        count(*) filter (where rev.status = 'REJECTED') as rejected_count
    from ingredient_mapping_pending_groups g
    left join ingredient_mapping_reviews rev
           on rev.source_ingredient_id = g.source_ingredient_id
          and rev.normalized_source_name = g.normalized_source_name
    """
)


def list_ingredient_mappings(
    session: Session,
    *,
    status: str | None,
    q: str | None,
    limit: int,
    cursor: str | None,
    final_disposition: str | None = None,
    sort: str | None = None,
    candidate_type: str | None = None,
) -> IngredientMappingListResponse:
    normalized_status = _normalize_status_filter(status)
    normalized_final_disposition = _normalize_final_disposition_filter(final_disposition)
    normalized_limit = _normalize_limit(limit)
    normalized_sort = _normalize_sort(sort)
    normalized_candidate_type = _normalize_candidate_type(candidate_type)
    normalized_q = _normalize_q(q)

    cursor_pc: str | None = None
    cursor_nsn: str | None = None
    cursor_connection_count: int | None = None
    if cursor is not None and cursor.strip():
        cursor_pc, cursor_nsn, cursor_connection_count = _decode_cursor(
            cursor,
            status=normalized_status,
            final_disposition=normalized_final_disposition,
            q=normalized_q,
            sort=normalized_sort,
            candidate_type=normalized_candidate_type,
        )

    q_like = f"%{_escape_like(normalized_q)}%" if normalized_q else ""
    list_sql = _LIST_CANDIDATE_SQL if normalized_candidate_type is not None else _LIST_SQL
    rows = list(
        session.execute(
            list_sql,
            {
                "status": normalized_status,
                "final_disposition": normalized_final_disposition,
                "q": normalized_q,
                "q_like": q_like,
                "sort": normalized_sort,
                "candidate_type": normalized_candidate_type,
                "cursor_pc": cursor_pc,
                "cursor_nsn": cursor_nsn,
                "cursor_connection_count": cursor_connection_count,
                "limit_plus_one": normalized_limit + 1,
            },
        )
    )

    has_more = len(rows) > normalized_limit
    page_rows = rows[:normalized_limit]

    alias_hits, canonical_hits, canonical_conflicts = _load_page_suggestions(
        session, [r.nsn for r in page_rows]
    )

    items = [
        _to_list_item(r, alias_hits, canonical_hits, canonical_conflicts) for r in page_rows
    ]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[normalized_limit - 1]
        next_cursor = _encode_cursor(
            last.pending_code,
            last.nsn,
            status=normalized_status,
            final_disposition=normalized_final_disposition,
            q=normalized_q,
            sort=normalized_sort,
            candidate_type=normalized_candidate_type,
            connection_count=int(last.connection_count),
        )

    summary_row = session.execute(_SUMMARY_SQL).one()
    summary = IngredientMappingSummary(
        pending_count=summary_row.pending_count,
        held_count=summary_row.held_count,
        needs_review_count=summary_row.needs_review_count,
        unclassified_count=summary_row.unclassified_count,
        approved_count=summary_row.approved_count,
        rejected_count=summary_row.rejected_count,
    )

    return IngredientMappingListResponse(items=items, summary=summary, next_cursor=next_cursor)


def _to_list_item(
    row: object,
    alias_hits: dict[str, tuple[int, str, str]],
    canonical_hits: dict[str, tuple[int, str, str]],
    canonical_conflicts: set[str],
) -> IngredientMappingListItem:
    status = _effective_status(getattr(row, "review_status", None))
    connection_count = int(row.connection_count)
    return IngredientMappingListItem(
        pending_code=row.pending_code,
        raw_name=row.raw_name,
        normalized_source_name=row.nsn,
        product_count=connection_count,
        connection_count=connection_count,
        status=status,
        candidate=_build_candidate(row.nsn, alias_hits, canonical_hits, canonical_conflicts),
        suggestion=_build_suggestion(row.nsn, alias_hits, canonical_hits),
        decision=_decision_from_row(row),
        available_actions=list(_ACTIONS_BY_STATUS[status]),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- 상세 -----------------------------------------------------------------

MAX_RAW_NAME_VARIANTS = 20
MAX_SAMPLE_PRODUCTS = 20

_DETAIL_GROUP_SQL = text(
    f"""
    with variant as (
        select i.id as source_id, i.ingredient_code as pending_code, i.name_ko as pending_name,
               {_NORMALIZE_SQL.format(col="pi.ingredient_name")} as nsn,
               pi.ingredient_name as raw_name, pi.product_id as product_id
        from product_ingredients pi
        join ingredients i on i.id = pi.ingredient_id
        where i.ingredient_code = :pending_code and {_PENDING_PREDICATE}
    ),
    scoped as (
        select * from variant where nsn = :nsn
    ),
    rep as (
        select raw_name, count(*) as c
        from scoped group by raw_name
        order by c desc, raw_name asc
        limit 1
    )
    select s.source_id, s.pending_code, s.pending_name, s.nsn,
           (select raw_name from rep) as raw_name,
           count(*) as connection_count,
           rev.id as review_id, rev.status as review_status,
           rev.target_ingredient_id, rev.final_disposition, rev.decision_reason,
           rev.reviewed_by_user_id, rev.reviewed_at,
           tgt.ingredient_code as target_ingredient_code, tgt.name_ko as target_ingredient_name
    from scoped s
    left join ingredient_mapping_reviews rev
           on rev.source_ingredient_id = s.source_id and rev.normalized_source_name = s.nsn
    left join ingredients tgt on tgt.id = rev.target_ingredient_id
    group by s.source_id, s.pending_code, s.pending_name, s.nsn,
             rev.id, rev.status, rev.target_ingredient_id, rev.final_disposition, rev.decision_reason,
             rev.reviewed_by_user_id, rev.reviewed_at,
             tgt.ingredient_code, tgt.name_ko
    """
)

_DETAIL_VARIANTS_SQL = text(
    f"""
    select pi.ingredient_name as raw_name, count(*) as connection_count
    from product_ingredients pi
    join ingredients i on i.id = pi.ingredient_id
    where i.ingredient_code = :pending_code
      and {_NORMALIZE_SQL.format(col="pi.ingredient_name")} = :nsn
    group by pi.ingredient_name
    order by count(*) desc, pi.ingredient_name asc
    limit :limit
    """
)

_DETAIL_SAMPLES_SQL = text(
    f"""
    select p.product_code, p.product_name, pi.ingredient_name as raw_name,
           pi.display_order, pi.concentration_text
    from product_ingredients pi
    join ingredients i on i.id = pi.ingredient_id
    join products p on p.id = pi.product_id
    where i.ingredient_code = :pending_code
      and {_NORMALIZE_SQL.format(col="pi.ingredient_name")} = :nsn
    order by pi.display_order asc nulls last, p.product_code asc
    limit :limit
    """
)

_DETAIL_EVENTS_SQL = text(
    """
    select e.from_status, e.to_status, e.from_final_disposition, e.to_final_disposition,
           e.actor_id, e.reason, e.metadata_json, e.created_at,
           ft.ingredient_code as from_target_code, tt.ingredient_code as to_target_code
    from ingredient_mapping_review_events e
    left join ingredients ft on ft.id = e.from_target_ingredient_id
    left join ingredients tt on tt.id = e.to_target_ingredient_id
    where e.review_id = :review_id
    order by e.created_at desc, e.id desc
    """
)


def get_ingredient_mapping_detail(
    session: Session,
    *,
    pending_code: str,
    normalized_source_name: str | None,
) -> IngredientMappingDetail:
    code = (pending_code or "").strip()
    if not code:
        raise ApiError(404, "PENDING_INGREDIENT_NOT_FOUND", "Pending ingredient not found.")
    nsn = normalized_source_name
    if nsn is None or not nsn.strip():
        # 원문 그룹 식별 필수(전체 범위 조회는 M2-A 불허, 계약 §5).
        raise ApiError(400, "NORMALIZED_SOURCE_NAME_REQUIRED", "normalized_source_name is required.")

    group_row = session.execute(
        _DETAIL_GROUP_SQL, {"pending_code": code, "nsn": nsn}
    ).first()
    if group_row is None:
        # pending code 자체가 없으면 404, code 는 있으나 그 원문 그룹이 없으면 404 로 구분.
        exists = session.execute(
            text(f"select 1 from ingredients i where i.ingredient_code = :pc and {_PENDING_PREDICATE} limit 1"),
            {"pc": code},
        ).first()
        if exists is None:
            raise ApiError(404, "PENDING_INGREDIENT_NOT_FOUND", "Pending ingredient not found.")
        raise ApiError(404, "INGREDIENT_MAPPING_GROUP_NOT_FOUND", "Ingredient mapping group not found.")

    alias_hits, canonical_hits, canonical_conflicts = _load_page_suggestions(session, [nsn])

    variants = [
        IngredientMappingRawNameVariant(
            raw_name=r.raw_name,
            product_count=int(r.connection_count),
            connection_count=int(r.connection_count),
        )
        for r in session.execute(
            _DETAIL_VARIANTS_SQL,
            {"pending_code": code, "nsn": nsn, "limit": MAX_RAW_NAME_VARIANTS},
        )
    ]
    samples = [
        IngredientMappingSampleProduct(
            product_code=r.product_code,
            product_name=r.product_name,
            raw_name=r.raw_name,
            display_order=r.display_order,
            concentration_text=r.concentration_text,
        )
        for r in session.execute(
            _DETAIL_SAMPLES_SQL,
            {"pending_code": code, "nsn": nsn, "limit": MAX_SAMPLE_PRODUCTS},
        )
    ]

    events: list[IngredientMappingEvent] = []
    review_id = getattr(group_row, "review_id", None)
    if review_id is not None:
        events = [
            IngredientMappingEvent(
                from_status=r.from_status,
                to_status=r.to_status,
                from_final_disposition=r.from_final_disposition,
                to_final_disposition=r.to_final_disposition,
                from_target_ingredient_code=r.from_target_code,
                to_target_ingredient_code=r.to_target_code,
                actor_id=r.actor_id,
                reason=r.reason,
                evidence_source_url=(r.metadata_json or {}).get("final_disposition_evidence_source_url"),
                source_reference=(r.metadata_json or {}).get("final_disposition_source_reference"),
                created_at=r.created_at,
            )
            for r in session.execute(_DETAIL_EVENTS_SQL, {"review_id": review_id})
        ]

    status = _effective_status(getattr(group_row, "review_status", None))
    connection_count = int(group_row.connection_count)
    return IngredientMappingDetail(
        pending_code=group_row.pending_code,
        raw_name=group_row.raw_name,
        normalized_source_name=group_row.nsn,
        product_count=connection_count,
        connection_count=connection_count,
        status=status,
        candidate=_build_candidate(nsn, alias_hits, canonical_hits, canonical_conflicts),
        suggestion=_build_suggestion(nsn, alias_hits, canonical_hits),
        decision=_decision_from_row(group_row),
        available_actions=list(_ACTIONS_BY_STATUS[status]),
        pending_ingredient_name=group_row.pending_name,
        raw_name_variants=variants,
        sample_products=samples,
        events=events,
    )


# --- canonical 검색 (승인 target 선택용, §6) --------------------------------

_CANONICAL_SEARCH_SQL = text(
    """
    select ingredient_code, name_ko, name_en, normalized_name, source_url,
           case when normalized_name = :nq then 0 else 1 end as exact_rank
    from ingredients
    where is_active = true
      and ingredient_code not like 'ing_pending_%'
      and ingredient_code not like 'foreign_pending_%'
      and (
        ingredient_code ilike :q_like
        or name_ko ilike :q_like
        or coalesce(name_en, '') ilike :q_like
        or coalesce(normalized_name, '') ilike :q_like
      )
    order by exact_rank asc, name_ko asc, ingredient_code asc
    offset :offset
    limit :limit_plus_one
    """
)


def search_canonical_ingredients(
    session: Session, *, q: str | None, limit: int, cursor: str | None
) -> CanonicalIngredientSearchResponse:
    normalized_q = (q or "").strip()
    if not (1 <= len(normalized_q) <= 100):
        raise ApiError(400, "INVALID_INPUT", "q must be 1~100 characters.")
    if limit < 1 or limit > CANONICAL_SEARCH_MAX_LIMIT:
        raise ApiError(400, "INVALID_LIMIT", "Invalid limit.")

    offset = _decode_offset_cursor(cursor)
    q_like = f"%{_escape_like(normalized_q)}%"
    rows = list(
        session.execute(
            _CANONICAL_SEARCH_SQL,
            {
                "nq": normalize_source_name(normalized_q),
                "q_like": q_like,
                "offset": offset,
                "limit_plus_one": limit + 1,
            },
        )
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        CanonicalIngredientSearchItem(
            ingredient_code=r.ingredient_code,
            name_ko=r.name_ko,
            name_en=r.name_en,
            normalized_name=r.normalized_name,
            source_url=r.source_url,
        )
        for r in page
    ]
    next_cursor = _encode_offset_cursor(offset + limit) if has_more else None
    return CanonicalIngredientSearchResponse(items=items, next_cursor=next_cursor)


def _encode_offset_cursor(offset: int) -> str:
    raw = json.dumps({"v": CURSOR_VERSION, "o": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_offset_cursor(cursor: str | None) -> int:
    if cursor is None or not cursor.strip():
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(f"{cursor}{padding}".encode("ascii")))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.") from exc
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    offset = payload.get("o")
    if not isinstance(offset, int) or offset < 0:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    return offset
