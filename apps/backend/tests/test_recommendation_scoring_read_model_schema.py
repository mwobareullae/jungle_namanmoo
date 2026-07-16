import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.db.session import make_engine


def test_read_model_migration_upgrades_and_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration_module()
    engine = make_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(text("create table products (id bigint primary key)"))
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        migration.upgrade()
        inspector = inspect(connection)
        columns = {
            column["name"]
            for column in inspector.get_columns(
                "product_recommendation_scoring_read_models"
            )
        }
        primary_key = inspector.get_pk_constraint(
            "product_recommendation_scoring_read_models"
        )

        assert "scoring_payload" not in columns
        assert {
            "product_id",
            "top_ingredient_codes",
            "top_effect_codes",
            "read_model_version",
            "source_updated_at",
            "computed_at",
        }.issubset(columns)
        assert primary_key["constrained_columns"] == ["product_id"]

        migration.downgrade()
        assert "product_recommendation_scoring_read_models" not in inspect(
            connection
        ).get_table_names()


def _load_migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260716_0045_add_recommendation_scoring_read_models.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20260716_0045", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the recommendation read model migration.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
