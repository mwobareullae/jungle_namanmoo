import argparse
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.db.models.search import SearchDocument
from app.db.session import SessionLocal
from app.services.embeddings import (
    EmbeddingProvider,
    embedding_text,
    format_vector,
    get_default_embedding_provider,
)


DEFAULT_BATCH_SIZE = 32


@dataclass(frozen=True)
class EmbedSearchDocumentsResult:
    scanned: int
    embedded: int
    provider_model: str
    dimensions: int
    dry_run: bool

    def __str__(self) -> str:
        return (
            "EmbedSearchDocumentsResult("
            f"scanned={self.scanned}, "
            f"embedded={self.embedded}, "
            f"provider_model='{self.provider_model}', "
            f"dimensions={self.dimensions}, "
            f"dry_run={self.dry_run}"
            ")"
        )


def main() -> None:
    args = _parse_args()
    provider = get_default_embedding_provider()

    with SessionLocal() as session:
        result = embed_search_documents(
            session,
            provider=provider,
            limit=args.limit,
            batch_size=args.batch_size,
            force=args.force,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(result)


def embed_search_documents(
    session: Session,
    *,
    provider: EmbeddingProvider,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force: bool = False,
    dry_run: bool = False,
) -> EmbedSearchDocumentsResult:
    documents = _load_documents_to_embed(
        session,
        provider=provider,
        limit=limit,
        force=force,
    )
    if dry_run:
        return EmbedSearchDocumentsResult(
            scanned=len(documents),
            embedded=0,
            provider_model=provider.model,
            dimensions=provider.dimensions,
            dry_run=True,
        )

    embedded_count = 0
    now = datetime.now(UTC)
    for batch in _chunks(documents, max(1, batch_size)):
        vectors = provider.embed_texts(
            [
                embedding_text(document.title, document.content, document.keywords)
                for document in batch
            ]
        )
        for document, vector in zip(batch, vectors, strict=True):
            _store_document_embedding(
                session,
                document,
                vector_text=format_vector(vector),
                provider=provider,
                updated_at=now,
            )
            embedded_count += 1
        session.flush()

    return EmbedSearchDocumentsResult(
        scanned=len(documents),
        embedded=embedded_count,
        provider_model=provider.model,
        dimensions=provider.dimensions,
        dry_run=False,
    )


def _load_documents_to_embed(
    session: Session,
    *,
    provider: EmbeddingProvider,
    limit: int | None,
    force: bool,
) -> list[SearchDocument]:
    statement = select(SearchDocument).order_by(SearchDocument.id.asc())
    if not force:
        statement = statement.where(
            or_(
                SearchDocument.embedding.is_(None),
                SearchDocument.embedding_model != provider.model,
                SearchDocument.embedding_dimensions != provider.dimensions,
            )
        )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.execute(statement).scalars().all())


def _store_document_embedding(
    session: Session,
    document: SearchDocument,
    *,
    vector_text: str,
    provider: EmbeddingProvider,
    updated_at: datetime,
) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text(
                """
                UPDATE search_documents
                SET embedding = CAST(:embedding AS vector),
                    embedding_model = :embedding_model,
                    embedding_dimensions = :embedding_dimensions,
                    embedding_updated_at = :embedding_updated_at
                WHERE id = :id
                """
            ),
            {
                "id": document.id,
                "embedding": vector_text,
                "embedding_model": provider.model,
                "embedding_dimensions": provider.dimensions,
                "embedding_updated_at": updated_at,
            },
        )
        return

    document.embedding = vector_text
    document.embedding_model = provider.model
    document.embedding_dimensions = provider.dimensions
    document.embedding_updated_at = updated_at


def _chunks(items: list[SearchDocument], size: int) -> list[list[SearchDocument]]:
    return [
        items[index : index + size]
        for index in range(0, len(items), size)
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and store embeddings for search_documents.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum documents to embed.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--force", action="store_true", help="Re-embed documents even if embeddings exist.")
    parser.add_argument("--dry-run", action="store_true", help="Only count target documents.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
