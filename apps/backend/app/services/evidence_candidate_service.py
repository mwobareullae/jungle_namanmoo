from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.taxonomy import (
    Effect,
    EvidenceDiscoveryCandidate,
    EvidenceDiscoveryReview,
    Ingredient,
    IngredientEffect,
    IngredientEvidence,
)
from app.schemas.common import ApiError
from app.schemas.evidence_admin import (
    EvidenceCandidateApproveRequest,
    EvidenceCandidateDecisionResponse,
    EvidenceCandidateDetailResponse,
    EvidenceCandidateImportItem,
    EvidenceCandidateImportResponse,
    EvidenceCandidateItem,
    EvidenceCandidateListResponse,
    EvidenceCandidateReviewItem,
    EvidenceCandidateStats,
    EvidenceCandidateRejectRequest,
    CurrentIngredientEvidenceItem,
)


def import_evidence_candidates(
    session: Session,
    candidates: list[EvidenceCandidateImportItem],
) -> EvidenceCandidateImportResponse:
    ingredient_codes = {item.ingredient_id for item in candidates}
    effect_codes = {item.effect_id for item in candidates}
    ingredients = {
        row.ingredient_code: row
        for row in session.execute(
            select(Ingredient).where(Ingredient.ingredient_code.in_(ingredient_codes))
        ).scalars()
    }
    effects = {
        row.effect_code: row
        for row in session.execute(
            select(Effect).where(Effect.effect_code.in_(effect_codes))
        ).scalars()
    }
    missing_ingredients = sorted(ingredient_codes - ingredients.keys())
    missing_effects = sorted(effect_codes - effects.keys())
    if missing_ingredients or missing_effects:
        details = []
        if missing_ingredients:
            details.append(f"성분: {', '.join(missing_ingredients)}")
        if missing_effects:
            details.append(f"효능: {', '.join(missing_effects)}")
        raise ApiError(400, "UNKNOWN_EVIDENCE_PAIR", "정본에 없는 " + " / ".join(details))

    valid_pairs = set(
        session.execute(
            select(Ingredient.ingredient_code, Effect.effect_code)
            .select_from(IngredientEffect)
            .join(Ingredient, IngredientEffect.ingredient_id == Ingredient.id)
            .join(Effect, IngredientEffect.effect_id == Effect.id)
            .where(
                Ingredient.ingredient_code.in_(ingredient_codes),
                Effect.effect_code.in_(effect_codes),
            )
        ).all()
    )
    invalid_pairs = sorted(
        {
            (item.ingredient_id, item.effect_id)
            for item in candidates
            if (item.ingredient_id, item.effect_id) not in valid_pairs
        }
    )
    if invalid_pairs:
        formatted = ", ".join(f"{ingredient}/{effect}" for ingredient, effect in invalid_pairs)
        raise ApiError(400, "UNKNOWN_INGREDIENT_EFFECT_PAIR", f"검색 대상이 아닌 조합입니다: {formatted}")

    now = datetime.now(timezone.utc)
    inserted = 0
    refreshed = 0
    for item in candidates:
        ingredient = ingredients[item.ingredient_id]
        effect = effects[item.effect_id]
        paper_key = _paper_key(item)
        existing = session.execute(
            select(EvidenceDiscoveryCandidate).where(
                EvidenceDiscoveryCandidate.ingredient_id == ingredient.id,
                EvidenceDiscoveryCandidate.effect_id == effect.id,
                EvidenceDiscoveryCandidate.paper_key == paper_key,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                EvidenceDiscoveryCandidate(
                    discovery_key=item.discovery_key,
                    ingredient_id=ingredient.id,
                    effect_id=effect.id,
                    paper_key=paper_key,
                    first_seen_at=now,
                    last_seen_at=now,
                    **_candidate_metadata(item),
                )
            )
            inserted += 1
            continue

        existing.last_seen_at = now
        existing.updated_at = now
        for field, value in _candidate_metadata(item).items():
            if value not in {None, ""}:
                setattr(existing, field, value)
        refreshed += 1

    session.flush()
    return EvidenceCandidateImportResponse(
        received=len(candidates),
        inserted=inserted,
        refreshed=refreshed,
    )


def list_evidence_candidates(
    session: Session,
    *,
    status: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> EvidenceCandidateListResponse:
    filters = []
    if status:
        filters.append(EvidenceDiscoveryCandidate.review_status == status)
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(
            Ingredient.name_ko.ilike(pattern)
            | Ingredient.name_en.ilike(pattern)
            | Ingredient.ingredient_code.ilike(pattern)
            | Effect.name.ilike(pattern)
            | EvidenceDiscoveryCandidate.title.ilike(pattern)
            | EvidenceDiscoveryCandidate.pmid.ilike(pattern)
            | EvidenceDiscoveryCandidate.doi.ilike(pattern)
        )

    evidence_count = (
        select(func.count(IngredientEvidence.id))
        .where(
            IngredientEvidence.ingredient_id == EvidenceDiscoveryCandidate.ingredient_id,
            IngredientEvidence.effect_id == EvidenceDiscoveryCandidate.effect_id,
            IngredientEvidence.is_current.is_(True),
        )
        .correlate(EvidenceDiscoveryCandidate)
        .scalar_subquery()
    )
    base = (
        select(EvidenceDiscoveryCandidate, Ingredient, Effect, evidence_count)
        .join(Ingredient, EvidenceDiscoveryCandidate.ingredient_id == Ingredient.id)
        .join(Effect, EvidenceDiscoveryCandidate.effect_id == Effect.id)
        .where(*filters)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.execute(
        base.order_by(
            EvidenceDiscoveryCandidate.review_status.asc(),
            EvidenceDiscoveryCandidate.last_seen_at.desc(),
            EvidenceDiscoveryCandidate.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    stats_by_status = dict(
        session.execute(
            select(EvidenceDiscoveryCandidate.review_status, func.count())
            .group_by(EvidenceDiscoveryCandidate.review_status)
        ).all()
    )
    stats = EvidenceCandidateStats(
        total=sum(stats_by_status.values()),
        candidate_unverified=stats_by_status.get("candidate_unverified", 0),
        accepted=stats_by_status.get("accepted", 0),
        rejected=stats_by_status.get("rejected", 0),
    )
    items = [
        _candidate_item(candidate, ingredient, effect, current_evidence_count)
        for candidate, ingredient, effect, current_evidence_count in rows
    ]
    return EvidenceCandidateListResponse(
        items=items,
        stats=stats,
        total=total,
        limit=limit,
        offset=offset,
    )


def get_evidence_candidate(
    session: Session,
    candidate_id: int,
) -> EvidenceCandidateDetailResponse:
    row = session.execute(
        select(EvidenceDiscoveryCandidate, Ingredient, Effect)
        .join(Ingredient, EvidenceDiscoveryCandidate.ingredient_id == Ingredient.id)
        .join(Effect, EvidenceDiscoveryCandidate.effect_id == Effect.id)
        .where(EvidenceDiscoveryCandidate.id == candidate_id)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "EVIDENCE_CANDIDATE_NOT_FOUND", "논문 후보를 찾을 수 없습니다.")
    candidate, ingredient, effect = row
    history_rows = session.execute(
        select(EvidenceDiscoveryReview, User)
        .join(User, EvidenceDiscoveryReview.reviewer_user_id == User.id)
        .where(EvidenceDiscoveryReview.candidate_id == candidate.id)
        .order_by(EvidenceDiscoveryReview.created_at.desc(), EvidenceDiscoveryReview.id.desc())
    ).all()
    current_evidence_count = session.scalar(
        select(func.count(IngredientEvidence.id)).where(
            IngredientEvidence.ingredient_id == candidate.ingredient_id,
            IngredientEvidence.effect_id == candidate.effect_id,
            IngredientEvidence.is_current.is_(True),
        )
    ) or 0
    item = _candidate_item(candidate, ingredient, effect, current_evidence_count)
    current_evidence_rows = session.execute(
        select(IngredientEvidence)
        .where(
            IngredientEvidence.ingredient_id == candidate.ingredient_id,
            IngredientEvidence.effect_id == candidate.effect_id,
            IngredientEvidence.is_current.is_(True),
        )
        .order_by(
            IngredientEvidence.is_representative.desc(),
            IngredientEvidence.representative_rank.asc(),
            IngredientEvidence.evidence_score.desc(),
            IngredientEvidence.id.asc(),
        )
    ).scalars()
    return EvidenceCandidateDetailResponse(
        **item.model_dump(),
        search_query=candidate.search_query,
        search_window_start=candidate.search_window_start,
        search_window_end=candidate.search_window_end,
        current_evidence=[
            CurrentIngredientEvidenceItem(
                id=evidence.id,
                source_title=evidence.source_title,
                source_url=evidence.source_url,
                summary=evidence.summary,
                evidence_level=evidence.evidence_level,
                evidence_score=evidence.evidence_score,
                review_status=evidence.review_status,
                result_direction=evidence.result_direction,
                score_use_level=evidence.score_use_level,
                is_representative=evidence.is_representative,
                representative_rank=evidence.representative_rank,
            )
            for evidence in current_evidence_rows
        ],
        history=[
            EvidenceCandidateReviewItem(
                id=review.id,
                previous_status=review.previous_status,
                new_status=review.new_status,
                reviewer=user.display_name or user.email,
                note=review.note,
                promoted_evidence_id=review.promoted_evidence_id,
                created_at=review.created_at,
            )
            for review, user in history_rows
        ],
    )


def approve_evidence_candidate(
    session: Session,
    candidate_id: int,
    reviewer: User,
    request: EvidenceCandidateApproveRequest,
) -> EvidenceCandidateDecisionResponse:
    candidate = _candidate_for_review(session, candidate_id)
    _validate_approval(request)
    now = datetime.now(timezone.utc)

    if request.is_representative:
        occupied = session.execute(
            select(IngredientEvidence.id).where(
                IngredientEvidence.ingredient_id == candidate.ingredient_id,
                IngredientEvidence.effect_id == candidate.effect_id,
                IngredientEvidence.is_current.is_(True),
                IngredientEvidence.is_representative.is_(True),
                IngredientEvidence.representative_rank == request.representative_rank,
            )
        ).scalar_one_or_none()
        if occupied is not None:
            raise ApiError(409, "REPRESENTATIVE_RANK_OCCUPIED", "해당 대표 근거 순위가 이미 사용 중입니다.")

    evidence = session.execute(
        select(IngredientEvidence).where(
            IngredientEvidence.ingredient_id == candidate.ingredient_id,
            IngredientEvidence.effect_id == candidate.effect_id,
            IngredientEvidence.canonical_evidence_key == candidate.paper_key,
        )
    ).scalar_one_or_none()
    evidence_values = {
        "evidence_level": request.evidence_level,
        "evidence_score": request.evidence_score,
        "source_title": candidate.title[:240],
        "source_url": candidate.source_url,
        "summary": request.summary,
        "published_at": candidate.publication_date,
        "source_type": "paper",
        "pmid": candidate.pmid,
        "doi": candidate.doi,
        "source_authority_score": request.source_authority_score
        if request.source_authority_score is not None
        else {"high": Decimal("0.9"), "medium": Decimal("0.7"), "low": Decimal("0.5")}[request.evidence_level],
        "canonical_evidence_key": candidate.paper_key,
        "review_status": "accepted",
        "result_direction": request.result_direction,
        "score_use_level": request.score_use_level,
        "is_representative": request.is_representative,
        "representative_rank": request.representative_rank,
        "is_current": True,
        "review_note": request.review_note,
        "reviewed_by": reviewer.email[:120],
        "reviewed_at": now,
    }
    if evidence is None:
        evidence = IngredientEvidence(
            ingredient_id=candidate.ingredient_id,
            effect_id=candidate.effect_id,
            **evidence_values,
        )
        session.add(evidence)
    else:
        for field, value in evidence_values.items():
            setattr(evidence, field, value)
    session.flush()

    previous_status = candidate.review_status
    candidate.review_status = "accepted"
    candidate.review_note = request.review_note
    candidate.reviewed_by_user_id = reviewer.id
    candidate.reviewed_at = now
    candidate.promoted_evidence_id = evidence.id
    candidate.updated_at = now
    session.add(
        EvidenceDiscoveryReview(
            candidate_id=candidate.id,
            previous_status=previous_status,
            new_status="accepted",
            reviewer_user_id=reviewer.id,
            note=request.review_note,
            promoted_evidence_id=evidence.id,
        )
    )
    session.flush()
    detail = get_evidence_candidate(session, candidate.id)
    return EvidenceCandidateDecisionResponse(candidate=detail, promoted_evidence_id=evidence.id)


def reject_evidence_candidate(
    session: Session,
    candidate_id: int,
    reviewer: User,
    request: EvidenceCandidateRejectRequest,
) -> EvidenceCandidateDecisionResponse:
    candidate = _candidate_for_review(session, candidate_id)
    now = datetime.now(timezone.utc)
    previous_status = candidate.review_status
    candidate.review_status = "rejected"
    candidate.review_note = request.review_note
    candidate.reviewed_by_user_id = reviewer.id
    candidate.reviewed_at = now
    candidate.updated_at = now
    session.add(
        EvidenceDiscoveryReview(
            candidate_id=candidate.id,
            previous_status=previous_status,
            new_status="rejected",
            reviewer_user_id=reviewer.id,
            note=request.review_note,
        )
    )
    session.flush()
    return EvidenceCandidateDecisionResponse(
        candidate=get_evidence_candidate(session, candidate.id),
        promoted_evidence_id=None,
    )


def _candidate_for_review(session: Session, candidate_id: int) -> EvidenceDiscoveryCandidate:
    candidate = session.execute(
        select(EvidenceDiscoveryCandidate)
        .where(EvidenceDiscoveryCandidate.id == candidate_id)
        .with_for_update()
    ).scalar_one_or_none()
    if candidate is None:
        raise ApiError(404, "EVIDENCE_CANDIDATE_NOT_FOUND", "논문 후보를 찾을 수 없습니다.")
    if candidate.review_status != "candidate_unverified":
        raise ApiError(409, "EVIDENCE_CANDIDATE_ALREADY_REVIEWED", "이미 판정된 논문 후보입니다.")
    return candidate


def _validate_approval(request: EvidenceCandidateApproveRequest) -> None:
    if request.is_representative != (request.representative_rank is not None):
        raise ApiError(400, "INVALID_REPRESENTATIVE_RANK", "대표 근거 여부와 대표 순위를 함께 입력해야 합니다.")
    if request.result_direction != "positive" and (
        request.evidence_score != Decimal("0") or request.score_use_level != "reference_only"
    ):
        raise ApiError(
            400,
            "NON_POSITIVE_EVIDENCE_CANNOT_SCORE",
            "음성·무효·불명확 근거는 현재 점수를 올릴 수 없으며 reference_only와 0점이어야 합니다.",
        )
    if request.score_use_level == "reference_only" and request.evidence_score != Decimal("0"):
        raise ApiError(
            400,
            "REFERENCE_ONLY_EVIDENCE_CANNOT_SCORE",
            "참고 전용 근거는 현재 점수를 올릴 수 없으며 0점이어야 합니다.",
        )


def _paper_key(item: EvidenceCandidateImportItem) -> str:
    pmid = item.pmid.strip()
    if pmid:
        return f"PMID:{pmid}"
    doi = item.doi.strip().lower()
    if doi:
        return f"DOI:{doi}"
    raise ApiError(400, "MISSING_PAPER_IDENTIFIER", "PMID 또는 DOI가 필요합니다.")


def _candidate_metadata(item: EvidenceCandidateImportItem) -> dict[str, object | None]:
    return {
        "pmid": item.pmid.strip() or None,
        "doi": item.doi.strip().lower() or None,
        "title": (item.title.strip() or "제목 미확인")[:500],
        "journal": item.journal.strip()[:240] or None,
        "publication_date": _parse_publication_date(item.publication_date),
        "publication_date_text": item.publication_date.strip() or None,
        "publication_types": item.publication_types.strip() or None,
        "authors": item.authors.strip() or None,
        "abstract_excerpt": item.abstract_excerpt.strip() or None,
        "source_url": item.source_url.strip(),
        "discovery_scope": item.discovery_scope,
        "search_query": item.search_query.strip() or None,
        "search_window_start": item.search_window_start,
        "search_window_end": item.search_window_end,
    }


def _candidate_item(
    candidate: EvidenceDiscoveryCandidate,
    ingredient: Ingredient,
    effect: Effect,
    current_evidence_count: int,
) -> EvidenceCandidateItem:
    return EvidenceCandidateItem(
        id=candidate.id,
        discovery_key=candidate.discovery_key,
        ingredient_id=ingredient.ingredient_code,
        ingredient_name=ingredient.name_ko,
        effect_id=effect.effect_code,
        effect_name=effect.name,
        pmid=candidate.pmid,
        doi=candidate.doi,
        title=candidate.title,
        journal=candidate.journal,
        publication_date=candidate.publication_date,
        publication_date_text=candidate.publication_date_text,
        publication_types=candidate.publication_types,
        authors=candidate.authors,
        abstract_excerpt=candidate.abstract_excerpt,
        source_url=candidate.source_url,
        discovery_scope=candidate.discovery_scope,
        first_seen_at=candidate.first_seen_at,
        last_seen_at=candidate.last_seen_at,
        review_status=candidate.review_status,
        review_note=candidate.review_note,
        reviewed_at=candidate.reviewed_at,
        promoted_evidence_id=candidate.promoted_evidence_id,
        current_evidence_count=current_evidence_count,
    )


def _parse_publication_date(value: str) -> date | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None
