import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.db.session import make_engine


def test_coarse_feature_migration_upgrades_and_downgrades(
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
                "product_recommendation_coarse_features"
            )
        }
        primary_key = inspector.get_pk_constraint(
            "product_recommendation_coarse_features"
        )

        assert {
            "functional_status",
            "functional_claims",
            "review_quality_score",
            "popularity_score",
            "top_ingredient_codes",
        }.isdisjoint(columns)
        assert {
            "product_id",
            "acne_sebum_effect_score",
            "wrinkle_evidence_score",
            "dry_fit",
            "sensitive_fit",
            "skin_profile_confidence_code",
            "source_current",
            "feature_version",
            "source_updated_at",
            "computed_at",
        }.issubset(columns)
        assert primary_key["constrained_columns"] == ["product_id"]

        migration.downgrade()
        assert "product_recommendation_coarse_features" not in inspect(
            connection
        ).get_table_names()


def _load_migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260717_0046_add_recommendation_coarse_features.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20260717_0046", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the recommendation coarse feature migration.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
