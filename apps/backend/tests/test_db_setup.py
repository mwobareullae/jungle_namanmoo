from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from app.core.config import settings
from app.db.base import Base
from app.db.session import make_engine, normalize_database_url


def test_database_url_uses_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://user:pass@db:5432/app") == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )
    assert normalize_database_url("postgresql+psycopg://user:pass@db:5432/app") == (
        "postgresql+psycopg://user:pass@db:5432/app"
    )


def test_sqlalchemy_engine_can_execute_sqlite_smoke_query() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")

    with engine.connect() as connection:
        result = connection.execute(text("select 1")).scalar_one()

    assert result == 1


def test_declarative_base_metadata_is_available() -> None:
    assert Base.metadata.tables == {}


def test_alembic_config_points_to_migrations() -> None:
    config = Config("alembic.ini")
    script_location = config.get_main_option("script_location")

    assert script_location is not None
    assert Path(script_location).name == "migrations"


def test_settings_exposes_database_url() -> None:
    assert settings.database_url
