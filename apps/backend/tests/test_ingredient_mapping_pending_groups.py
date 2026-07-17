from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.cli import seed_data
from app.services.admin import ingredient_mapping_service as mapping_service
from app.services.admin.ingredient_mapping_pending_groups import (
    PENDING_GROUPS_VIEW_NAME,
    PendingIngredientGroupsRefreshError,
    refresh_pending_ingredient_mapping_groups,
)


def test_list_and_summary_read_pending_groups_view() -> None:
    list_sql = str(mapping_service._LIST_SQL)
    summary_sql = str(mapping_service._SUMMARY_SQL)

    assert f"from {PENDING_GROUPS_VIEW_NAME} g" in list_sql
    assert f"from {PENDING_GROUPS_VIEW_NAME} g" in summary_sql
    assert "from product_ingredients" not in list_sql
    assert "from product_ingredients" not in summary_sql


def test_refresh_rejects_non_postgresql_engine() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    with pytest.raises(PendingIngredientGroupsRefreshError, match="PostgreSQL"):
        refresh_pending_ingredient_mapping_groups(engine)  # type: ignore[arg-type]


def test_refresh_uses_autocommit_connection() -> None:
    executed: list[str] = []
    isolation_levels: list[str] = []

    class FakeConnection:
        def execution_options(self, *, isolation_level: str) -> "FakeConnection":
            isolation_levels.append(isolation_level)
            return self

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            executed.append(str(statement))

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

        def connect(self) -> FakeConnection:
            return FakeConnection()

    refresh_pending_ingredient_mapping_groups(FakeEngine())  # type: ignore[arg-type]

    assert isolation_levels == ["AUTOCOMMIT"]
    assert executed == ["refresh materialized view concurrently ingredient_mapping_pending_groups"]


def test_seed_cli_reports_committed_data_when_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *_args: object) -> None:
            return None

    def raise_refresh_failure(_engine: object) -> float:
        raise PendingIngredientGroupsRefreshError("refresh failed")

    monkeypatch.setattr(seed_data, "SessionLocal", FakeSessionContext)
    monkeypatch.setattr(seed_data, "_seed_and_commit", lambda _session, _data_dir: "seed committed")
    monkeypatch.setattr(seed_data, "refresh_pending_ingredient_mapping_groups", raise_refresh_failure)
    monkeypatch.setattr(sys, "argv", ["seed_data"])

    with pytest.raises(SystemExit, match="Seed data was committed"):
        seed_data.main()

    assert "seed committed" in capsys.readouterr().err


def test_pending_groups_migration_creates_populated_view_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration_module()
    statements: list[str] = []
    fake_op = SimpleNamespace(execute=lambda statement: statements.append(str(statement)))
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()
    migration.downgrade()

    normalized_sql = "\n".join(statements).lower()
    assert "create materialized view ingredient_mapping_pending_groups" in normalized_sql
    assert "with data" in normalized_sql
    assert "uq_ing_mapping_pending_groups_source_nsn" in normalized_sql
    assert "ix_ing_mapping_pending_groups_cursor" in normalized_sql
    assert "drop materialized view if exists ingredient_mapping_pending_groups" in normalized_sql


def _load_migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260717_0048_add_ingredient_mapping_pending_groups_view.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20260717_0048", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the ingredient mapping pending groups migration.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
