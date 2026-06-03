"""Tests for foreign-key + naming-based relationship inference."""

from schemascribe.config import Config
from schemascribe.models import ColumnInfo, ForeignKeyInfo, SchemaInfo, TableInfo
from schemascribe.relationships import RelationshipInferrer


def _col(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, data_type="bigint", is_nullable=False, column_default=None, ordinal_position=1)


def _config_with_refs() -> Config:
    cfg = Config()
    cfg.reference_tables = {
        "customer_id": [{"schema": "public", "table": "customers", "column": "id"}],
    }
    return cfg


def test_infers_relationship_from_naming():
    cfg = _config_with_refs()
    inferrer = RelationshipInferrer(cfg)

    customers = TableInfo(schema_name="public", table_name="customers")
    orders = TableInfo(
        schema_name="public",
        table_name="orders",
        columns=[_col("id"), _col("customer_id")],
    )
    schema = SchemaInfo(schema_name="public", tables=[customers, orders])
    inferrer.register_schema(schema)

    rels = inferrer.infer_for_table(orders)

    assert len(rels.inferred) == 1
    rel = rels.inferred[0]
    assert rel.target_table == "customers"
    # Target table exists -> high confidence.
    assert rel.confidence == "high"


def test_unknown_target_is_medium_confidence():
    cfg = _config_with_refs()
    inferrer = RelationshipInferrer(cfg)

    orders = TableInfo(
        schema_name="public",
        table_name="orders",
        columns=[_col("customer_id")],
    )
    # We never register a schema containing "customers".
    inferrer.register_schema(SchemaInfo(schema_name="public", tables=[orders]))

    rels = inferrer.infer_for_table(orders)
    assert rels.inferred[0].confidence == "medium"


def test_explicit_fk_suppresses_inference():
    cfg = _config_with_refs()
    inferrer = RelationshipInferrer(cfg)

    orders = TableInfo(
        schema_name="public",
        table_name="orders",
        columns=[_col("customer_id")],
        foreign_keys=[
            ForeignKeyInfo(
                constraint_name="fk_cust",
                columns=["customer_id"],
                referenced_schema="public",
                referenced_table="customers",
                referenced_columns=["id"],
            )
        ],
    )
    inferrer.register_schema(SchemaInfo(schema_name="public", tables=[orders]))

    rels = inferrer.infer_for_table(orders)
    # The naming inference is skipped because a real FK already covers it.
    assert rels.inferred == []
    assert len(rels.explicit_fks) == 1


def test_cross_schema_links_are_deduplicated():
    cfg = Config()
    cfg.reference_tables = {
        "customer_id": [{"schema": "core", "table": "customers", "column": "id"}],
    }
    inferrer = RelationshipInferrer(cfg)

    for tname in ("orders", "invoices"):
        t = TableInfo(schema_name="sales", table_name=tname, columns=[_col("customer_id")])
        inferrer.register_schema(SchemaInfo(schema_name="sales", tables=[t]))
        inferrer.infer_for_table(t)

    links = inferrer.cross_schema_links()
    assert len(links) == 2
    assert all(link["from_schema"] == "sales" and link["to_schema"] == "core" for link in links)


def test_join_paths_render_both_explicit_and_inferred():
    cfg = _config_with_refs()
    inferrer = RelationshipInferrer(cfg)
    orders = TableInfo(schema_name="public", table_name="orders", columns=[_col("customer_id")])
    inferrer.register_schema(SchemaInfo(schema_name="public", tables=[orders]))
    inferrer.infer_for_table(orders)

    paths = inferrer.join_paths_for(orders)
    assert any("inferred" in p for p in paths)
    assert any("customers" in p for p in paths)
