import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.search import SearchDocument
from app.services.product_candidates import ProductCandidate
from app.services.recommendation_intent import RecommendationIntent


@dataclass(frozen=True)
class SearchMatch:
    product_id: str
    keyword_score: float
    vector_score: float
    search_match_score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class _WeightedTerm:
    text: str
    weight: float


def match_product_search_documents(
    session: Session,
    intent: RecommendationIntent,
    candidates: list[ProductCandidate],
) -> list[SearchMatch]:
    if not candidates:
        return []

    product_ids = [candidate.db_product_id for candidate in candidates]
    documents_by_product_id = _load_product_documents(session, product_ids)
    weighted_terms = _build_weighted_terms(intent)

    return [
        _score_candidate(
            candidate,
            documents_by_product_id.get(candidate.db_product_id, ()),
            weighted_terms,
        )
        for candidate in candidates
    ]


def _load_product_documents(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[SearchDocument, ...]]:
    rows = (
        session.execute(
            select(SearchDocument).where(
                SearchDocument.product_id.in_(product_ids),
                SearchDocument.document_type == "product",
            )
        )
        .scalars()
        .all()
    )

    documents_by_product_id: dict[int, list[SearchDocument]] = {}
    for document in rows:
        if document.product_id is None:
            continue
        documents_by_product_id.setdefault(document.product_id, []).append(document)

    return {
        product_id: tuple(documents)
        for product_id, documents in documents_by_product_id.items()
    }


def _score_candidate(
    candidate: ProductCandidate,
    documents: tuple[SearchDocument, ...],
    weighted_terms: tuple[_WeightedTerm, ...],
) -> SearchMatch:
    document_text = _normalize_text(
        " ".join(
            " ".join(
                value
                for value in (document.title, document.content, document.keywords or "")
                if value
            )
            for document in documents
        )
    )

    matched_terms: list[str] = []
    matched_weight = 0.0
    total_weight = sum(term.weight for term in weighted_terms)

    if document_text and total_weight > 0:
        for term in weighted_terms:
            if _document_matches_term(document_text, term.text):
                matched_terms.append(term.text)
                matched_weight += term.weight

    keyword_score = _clamp_score(matched_weight / total_weight if total_weight else 0.0)
    vector_score = 0.0

    return SearchMatch(
        product_id=candidate.product_id,
        keyword_score=keyword_score,
        vector_score=vector_score,
        search_match_score=keyword_score,
        matched_terms=tuple(matched_terms),
    )


def _build_weighted_terms(intent: RecommendationIntent) -> tuple[_WeightedTerm, ...]:
    weighted_terms_by_key: dict[str, _WeightedTerm] = {}

    for concern in intent.concerns:
        _upsert_weighted_term(weighted_terms_by_key, concern.name, 1.0)
        _upsert_weighted_term(weighted_terms_by_key, concern.matched_text, 1.0)

    for effect in intent.effects:
        _upsert_weighted_term(weighted_terms_by_key, effect.name, 1.0)

    for effect in intent.priority_effects:
        _upsert_weighted_term(weighted_terms_by_key, effect.name, 1.5)

    return tuple(weighted_terms_by_key.values())


def _upsert_weighted_term(
    weighted_terms_by_key: dict[str, _WeightedTerm],
    term: str,
    weight: float,
) -> None:
    normalized = _normalize_text(term)
    if not normalized:
        return

    existing = weighted_terms_by_key.get(normalized)
    if existing is None or weight > existing.weight:
        weighted_terms_by_key[normalized] = _WeightedTerm(text=term, weight=weight)


def _document_matches_term(document_text: str, term: str) -> bool:
    variants = _term_variants(term)
    return any(_matches_text(document_text, variant) for variant in variants)


def _term_variants(term: str) -> tuple[str, ...]:
    normalized = _normalize_text(term)
    parts = [
        part
        for part in re.split(r"[·/\s]+", normalized)
        if len(part) >= 2 and part not in {"조절", "강화", "정돈", "케어"}
    ]
    return _dedupe_terms([normalized, *parts])


def _matches_text(document_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    return normalized_term in document_text or _compact(normalized_term) in _compact(document_text)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _dedupe_terms(terms: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _normalize_text(term)
        if normalized and normalized not in seen:
            deduped.append(term)
            seen.add(normalized)
    return tuple(deduped)


def _clamp_score(score: float) -> float:
    return max(0.0, min(1.0, round(score, 4)))
