"""Tests for plain-English column and table inference."""

from schemascribe.config import Config
from schemascribe.inference import (
    infer_business_purpose,
    infer_column_meaning,
    infer_risk_notes,
    infer_tags,
    llm_summary,
)
from schemascribe.models import PartitionGroup, TableInfo


def _config() -> Config:
    return Config()


def test_glossary_exact_match_wins():
    cfg = _config()
    assert infer_column_meaning("created_at", "timestamptz", cfg).startswith("Timestamp when")
    assert "currency" in infer_column_meaning("currency", "char(3)", cfg).lower()


def test_user_glossary_merges_over_defaults():
    cfg = _config()
    cfg.column_glossary["mrr"] = "Monthly recurring revenue"
    assert infer_column_meaning("mrr", "numeric", cfg) == "Monthly recurring revenue"


def test_id_suffix_becomes_reference():
    cfg = _config()
    assert infer_column_meaning("customer_id", "bigint", cfg) == "Reference to the Customer record"


def test_boolean_prefix():
    cfg = _config()
    assert infer_column_meaning("is_active", "boolean", cfg).lower().startswith("whether")
    assert infer_column_meaning("has_discount", "boolean", cfg).lower().startswith("whether")


def test_money_and_date_suffixes():
    cfg = _config()
    assert "monetary amount" in infer_column_meaning("refund_amount", "numeric", cfg)
    assert infer_column_meaning("ship_date", "date", cfg) == "Ship date"


def test_fallback_humanises_unknown_name():
    cfg = _config()
    assert infer_column_meaning("some_obscure_thing", "text", cfg) == "Some Obscure Thing"


def test_database_comment_overrides_inference():
    cfg = _config()
    table = TableInfo(schema_name="public", table_name="orders", table_comment="The canonical orders ledger.")
    assert infer_business_purpose(table, cfg) == "The canonical orders ledger."


def test_business_purpose_mentions_partitioning():
    cfg = _config()
    table = TableInfo(schema_name="public", table_name="events", base_table_name="events")
    pg = PartitionGroup(
        base_table_name="events", schema_name="public",
        partition_type="yearly", partitions=["events_2022", "events_2023"],
        year_range=(2022, 2023),
    )
    text = infer_business_purpose(table, cfg, pg)
    assert "time-partitioned" in text
    assert "2022 to 2023" in text


def test_tags_from_vocabulary():
    cfg = _config()
    table = TableInfo(schema_name="public", table_name="payment_transaction")
    assert "transactional" in infer_tags(table, cfg)


def test_risk_notes_flag_missing_pk_and_audit():
    cfg = _config()
    audit = TableInfo(schema_name="public", table_name="orders_audit", category="audit")
    notes = infer_risk_notes(audit)
    assert any("Audit" in n for n in notes)
    assert any("primary key" in n.lower() for n in notes)


def test_llm_summary_is_one_sentence():
    table = TableInfo(schema_name="public", table_name="orders", primary_key=["id"])
    summary = llm_summary(table)
    assert summary.startswith("`public.orders`")
    assert summary.endswith(".")
