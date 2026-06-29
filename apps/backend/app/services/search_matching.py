import re
from dataclasses import dataclass

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.search import SearchDocument
from app.services.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    cosine_similarity,
    get_default_embedding_provider,
    format_vector,
    parse_vector,
)
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
    *,
    embedding_provider: EmbeddingProvider | None = None,
    keyword_weight: float = settings.hybrid_keyword_weight,
    vector_weight: float = settings.hybrid_vector_weight,
) -> list[SearchMatch]:
    if not candidates:
        return []

    product_ids = [candidate.db_product_id for candidate in candidates]
    documents_by_product_id = _load_product_documents(session, product_ids)
    weighted_terms = _build_weighted_terms(intent)
    keyword_matches = [
        _score_candidate(
            candidate,
            documents_by_product_id.get(candidate.db_product_id, ()),
            weighted_terms,
        )
        for candidate in candidates
    ]
    vector_scores = _load_vector_scores(
        session,
        intent,
        candidates,
        embedding_provider=embedding_provider,
    )

    return [
        _merge_match_scores(
            match,
            vector_scores.get(match.product_id),
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
        )
        for match in keyword_matches
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


def _load_vector_scores(
    session: Session,
    intent: RecommendationIntent,
    candidates: list[ProductCandidate],
    *,
    embedding_provider: EmbeddingProvider | None,
) -> dict[str, float]:
    if not candidates or not _should_use_vector_search(intent):
        return {}

    provider = embedding_provider or get_default_embedding_provider()
    if not _has_matching_embeddings(session, provider):
        return {}

    try:
        query_vector = provider.embed_text(intent.semantic_query_text)
    except EmbeddingError:
        return {}

    if session.get_bind().dialect.name == "postgresql":
        return _load_postgres_vector_scores(session, candidates, provider, query_vector)
    return _load_python_vector_scores(session, candidates, provider, query_vector)


def _should_use_vector_search(intent: RecommendationIntent) -> bool:
    if intent.search_terms:
        return True
    if intent.purchase_conditions.has_constraints:
        return False
    return bool(intent.concern_text.strip())


def _has_matching_embeddings(
    session: Session,
    provider: EmbeddingProvider,
) -> bool:
    row = session.execute(
        select(SearchDocument.id)
        .where(
            SearchDocument.document_type == "product",
            SearchDocument.embedding.is_not(None),
            SearchDocument.embedding_model == provider.model,
            SearchDocument.embedding_dimensions == provider.dimensions,
        )
        .limit(1)
    ).first()
    return row is not None


def _load_postgres_vector_scores(
    session: Session,
    candidates: list[ProductCandidate],
    provider: EmbeddingProvider,
    query_vector: list[float],
) -> dict[str, float]:
    product_codes_by_db_id = {
        candidate.db_product_id: candidate.product_id
        for candidate in candidates
    }
    statement = text(
        """
        SELECT
            product_id,
            MAX(GREATEST(0.0, 1.0 - (embedding <=> CAST(:query_embedding AS vector)))) AS vector_score
        FROM search_documents
        WHERE product_id IN :product_ids
          AND document_type = 'product'
          AND embedding IS NOT NULL
          AND embedding_model = :embedding_model
          AND embedding_dimensions = :embedding_dimensions
        GROUP BY product_id
        """
    ).bindparams(bindparam("product_ids", expanding=True))

    rows = session.execute(
        statement,
        {
            "product_ids": list(product_codes_by_db_id),
            "query_embedding": format_vector(query_vector),
            "embedding_model": provider.model,
            "embedding_dimensions": provider.dimensions,
        },
    ).all()
    return {
        product_codes_by_db_id[int(product_id)]: _clamp_score(float(vector_score or 0.0))
        for product_id, vector_score in rows
        if int(product_id) in product_codes_by_db_id
    }


def _load_python_vector_scores(
    session: Session,
    candidates: list[ProductCandidate],
    provider: EmbeddingProvider,
    query_vector: list[float],
) -> dict[str, float]:
    product_codes_by_db_id = {
        candidate.db_product_id: candidate.product_id
        for candidate in candidates
    }
    rows = session.execute(
        select(
            SearchDocument.product_id,
            SearchDocument.embedding,
        ).where(
            SearchDocument.product_id.in_(product_codes_by_db_id),
            SearchDocument.document_type == "product",
            SearchDocument.embedding.is_not(None),
            SearchDocument.embedding_model == provider.model,
            SearchDocument.embedding_dimensions == provider.dimensions,
        )
    ).all()

    scores_by_product: dict[str, float] = {}
    for product_id, embedding in rows:
        if product_id is None:
            continue
        document_vector = parse_vector(embedding)
        if document_vector is None:
            continue
        product_code = product_codes_by_db_id.get(int(product_id))
        if not product_code:
            continue
        score = _clamp_score(cosine_similarity(query_vector, document_vector))
        scores_by_product[product_code] = max(scores_by_product.get(product_code, 0.0), score)

    return scores_by_product


def _merge_match_scores(
    match: SearchMatch,
    vector_score: float | None,
    *,
    keyword_weight: float,
    vector_weight: float,
) -> SearchMatch:
    if vector_score is None:
        return match

    active_weights = [
        (match.keyword_score, max(0.0, keyword_weight)),
        (_clamp_score(vector_score), max(0.0, vector_weight)),
    ]
    weight_sum = sum(weight for _, weight in active_weights if weight > 0)
    search_match_score = (
        sum(score * weight for score, weight in active_weights if weight > 0) / weight_sum
        if weight_sum > 0
        else 0.0
    )

    return SearchMatch(
        product_id=match.product_id,
        keyword_score=match.keyword_score,
        vector_score=_clamp_score(vector_score),
        search_match_score=_clamp_score(search_match_score),
        matched_terms=match.matched_terms,
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
