import pytest
from sqlalchemy.orm import Session

from app.cli.embed_search_documents import (
    _validate_cli_provider,
    embed_search_documents,
)
from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.embeddings import LocalHashEmbeddingProvider
from tests.test_data_loader import EXAMPLES_DIR


def test_embed_search_documents_dry_run_reports_estimated_input_chars() -> None:
    session = _seed_example_session()
    provider = LocalHashEmbeddingProvider(dimensions=64)

    result = embed_search_documents(session, provider=provider, dry_run=True)

    assert result.scanned == 4
    assert result.embedded == 0
    assert result.provider_model == "local-hash-v1"
    assert result.dimensions == 64
    assert result.estimated_input_chars > 0
    assert result.dry_run is True


def test_validate_cli_provider_blocks_local_hash_for_server_batches() -> None:
    provider = LocalHashEmbeddingProvider(dimensions=64)

    with pytest.raises(SystemExit, match="OPENAI_API_KEY is required"):
        _validate_cli_provider(provider, require_openai=True)


def test_validate_cli_provider_allows_local_hash_for_local_fallback_runs() -> None:
    provider = LocalHashEmbeddingProvider(dimensions=64)

    _validate_cli_provider(provider, require_openai=False)


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
