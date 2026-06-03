"""Tests for table categorisation and partition grouping."""

from schemascribe.config import Config
from schemascribe.models import SchemaInfo, TableInfo
from schemascribe.patterns import classify_table, detect_partition, process_schema


def _config() -> Config:
    return Config()  # built-in defaults, no DB credentials needed


def test_classify_business_table():
    assert classify_table("orders", _config()) == "business"


def test_classify_migration_metadata():
    assert classify_table("flyway_schema_history", _config()) == "migration_metadata"
    assert classify_table("alembic_version", _config()) == "migration_metadata"


def test_classify_infrastructure_prefix():
    assert classify_table("qrtz_triggers", _config()) == "infrastructure"
    assert classify_table("celery_taskmeta", _config()) == "infrastructure"


def test_classify_audit_and_config_and_raw():
    cfg = _config()
    assert classify_table("orders_audit", cfg) == "audit"
    assert classify_table("orders_history", cfg) == "audit"
    assert classify_table("app_config", cfg) == "config"
    assert classify_table("vendor_raw", cfg) == "raw"
    assert classify_table("orders_staging", cfg) == "intermediate"


def test_detect_partition_variants():
    cfg = _config()
    assert detect_partition("events_2024", cfg) == ("events", "yearly")
    assert detect_partition("events_2024_06", cfg) == ("events", "monthly")
    assert detect_partition("events_2024_q1", cfg) == ("events", "quarterly")
    assert detect_partition("events_202401", cfg) == ("events", "monthly")
    assert detect_partition("orders", cfg) is None


def test_process_schema_collapses_partitions():
    cfg = _config()
    tables = [
        TableInfo(schema_name="public", table_name="orders"),
        TableInfo(schema_name="public", table_name="events_2022"),
        TableInfo(schema_name="public", table_name="events_2023"),
        TableInfo(schema_name="public", table_name="events_2024"),
        TableInfo(schema_name="public", table_name="flyway_schema_history"),
    ]
    schema = SchemaInfo(schema_name="public", tables=tables)

    documentable, groups = process_schema(schema, cfg)

    # The three events_* tables collapse into one group named "events".
    assert "events" in groups
    assert len(groups["events"].partitions) == 3
    assert groups["events"].year_range == (2022, 2024)

    # Documentable list contains orders, flyway, and exactly one "events" entry.
    names = sorted(t.display_name for t in documentable)
    assert names == ["events", "flyway_schema_history", "orders"]

    # Category buckets are populated.
    assert "orders" in schema.business_tables
    assert "flyway_schema_history" in schema.infrastructure_tables


def test_small_partition_run_is_not_grouped():
    cfg = _config()  # min_partition_group_size defaults to 2
    cfg.min_partition_group_size = 3
    tables = [
        TableInfo(schema_name="public", table_name="events_2023"),
        TableInfo(schema_name="public", table_name="events_2024"),
    ]
    schema = SchemaInfo(schema_name="public", tables=tables)

    documentable, groups = process_schema(schema, cfg)

    # Two partitions but threshold is 3 -> not treated as a group.
    assert groups == {}
    assert len(documentable) == 2
