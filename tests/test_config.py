"""Tests for configuration loading and merging."""

import textwrap

import pytest

from schemascribe.config import Config, DatabaseConfig


def test_default_config_has_builtin_values():
    cfg = Config()
    assert "pg_catalog" in cfg.excluded_schemas
    assert cfg.partition_patterns  # non-empty
    assert "id" in cfg.column_glossary
    assert cfg.min_partition_group_size == 2


def test_database_config_reports_missing_fields():
    db = DatabaseConfig()  # nothing set
    missing = db.missing_fields()
    assert "PGDATABASE" in missing
    assert "PGUSER" in missing
    assert "PGPASSWORD" in missing


def test_database_config_from_env(monkeypatch):
    monkeypatch.setenv("PGDATABASE", "mydb")
    monkeypatch.setenv("PGUSER", "alice")
    monkeypatch.setenv("PGPASSWORD", "secret")
    db = DatabaseConfig.from_env()
    assert db.database == "mydb"
    assert db.user == "alice"
    assert db.missing_fields() == []


def test_load_merges_yaml_over_defaults(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    monkeypatch.setenv("PGDATABASE", "x")
    monkeypatch.setenv("PGUSER", "x")
    monkeypatch.setenv("PGPASSWORD", "x")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            excluded_schemas: [pg_catalog, archive]
            column_glossary:
              mrr: "Monthly recurring revenue"
            reference_tables:
              customer_id:
                - { schema: public, table: customers, column: id }
            min_partition_group_size: 5
            """
        ),
        encoding="utf-8",
    )

    cfg = Config.load(config_file)
    assert cfg.excluded_schemas == ["pg_catalog", "archive"]
    # User glossary entry is added...
    assert cfg.column_glossary["mrr"] == "Monthly recurring revenue"
    # ...without wiping the built-in defaults.
    assert "id" in cfg.column_glossary
    assert cfg.reference_tables["customer_id"][0]["table"] == "customers"
    assert cfg.min_partition_group_size == 5


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        Config.load("definitely_not_a_real_file.yaml")
