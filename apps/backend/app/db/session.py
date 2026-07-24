from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.slow_query_logging import configure_db_slow_query_logging


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def make_engine(database_url: str | None = None) -> Engine:
    created_engine = create_engine(
        normalize_database_url(database_url or settings.database_url),
        pool_pre_ping=True,
    )
    configure_db_slow_query_logging(created_engine)
    return created_engine


engine = make_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
