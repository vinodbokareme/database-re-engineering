"""
Documentation rendering.

Takes the extracted + inferred metadata and writes it out as Markdown (for
humans and LLMs) plus JSON (for tooling). All presentation lives in the Jinja2
templates under ``templates/`` — this module just assembles the context and
decides where files go.

Output layout::

    <output>/
      summary/
        database_overview.md
        schema_index.json
      schemas/
        <schema>/
          schema_overview.md
          schema_metadata.json
          tables/
            <table>.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

from schemascribe import inference
from schemascribe.config import Config
from schemascribe.models import PartitionGroup, SchemaInfo, TableInfo
from schemascribe.relationships import RelationshipInferrer

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class DocGenerator:
    """Renders Markdown + JSON docs into ``output_dir``."""

    def __init__(self, config: Config, inferrer: RelationshipInferrer, output_dir: Path):
        self.config = config
        self.inferrer = inferrer
        self.output_dir = Path(output_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        (self.output_dir / "summary").mkdir(parents=True, exist_ok=True)

    # --- helpers -----------------------------------------------------------

    def _schema_dir(self, schema: str) -> Path:
        d = self.output_dir / "schemas" / schema
        (d / "tables").mkdir(parents=True, exist_ok=True)
        return d

    # --- table -------------------------------------------------------------

    def generate_table(self, table: TableInfo, partition_group: Optional[PartitionGroup] = None) -> None:
        """Write the Markdown page for a single table (or partition group)."""
        schema_dir = self._schema_dir(table.schema_name)
        out_path = schema_dir / "tables" / f"{table.display_name}.md"

        rels = self.inferrer.get(table.schema_name, table.table_name)
        join_paths = self.inferrer.join_paths_for(table)
        column_meanings = {
            col.name: inference.infer_column_meaning(col.name, col.data_type, self.config)
            for col in table.columns
        }

        context = {
            "table": table,
            "display_name": table.display_name,
            "partition_group": partition_group,
            "business_purpose": inference.infer_business_purpose(table, self.config, partition_group),
            "technical_purpose": inference.infer_technical_purpose(table, partition_group),
            "tags": inference.infer_tags(table, self.config),
            "risk_notes": inference.infer_risk_notes(table, partition_group),
            "llm_summary": inference.llm_summary(table, partition_group),
            "sample_queries": inference.sample_queries(table, join_paths),
            "join_paths": join_paths,
            "relationships": rels,
            "column_meanings": column_meanings,
        }
        out_path.write_text(self.env.get_template("table.md.j2").render(**context), encoding="utf-8")

    # --- schema ------------------------------------------------------------

    def generate_schema(
        self,
        schema_info: SchemaInfo,
        documentable: List[TableInfo],
        partition_groups: Dict[str, PartitionGroup],
    ) -> None:
        """Write the schema overview Markdown + JSON metadata."""
        schema_dir = self._schema_dir(schema_info.schema_name)

        categories: Dict[str, int] = {}
        for t in documentable:
            categories[t.category] = categories.get(t.category, 0) + 1

        # Suggested starting points: business tables richest in keys + columns.
        entry_points = sorted(
            (t for t in documentable if t.category == "business"),
            key=lambda t: (len(t.foreign_keys), len(t.columns)),
            reverse=True,
        )

        context = {
            "schema": schema_info,
            "documentable": documentable,
            "partition_groups": partition_groups,
            "categories": categories,
            "tags": inference.infer_tags(
                TableInfo(schema_name=schema_info.schema_name, table_name=schema_info.schema_name),
                self.config,
            ),
            "entry_points": [t.table_name for t in entry_points[:5]],
        }
        (schema_dir / "schema_overview.md").write_text(
            self.env.get_template("schema.md.j2").render(**context), encoding="utf-8"
        )

        metadata = {
            "schema_name": schema_info.schema_name,
            "total_table_count": schema_info.table_count,
            "documentable_count": len(documentable),
            "partition_groups": len(partition_groups),
            "categories": categories,
            "business_tables": schema_info.business_tables,
            "infrastructure_tables": schema_info.infrastructure_tables,
            "audit_tables": schema_info.audit_tables,
        }
        (schema_dir / "schema_metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

    # --- database ----------------------------------------------------------

    def generate_database_overview(
        self,
        all_schemas: List[SchemaInfo],
        all_partition_groups: Dict[str, Dict[str, PartitionGroup]],
    ) -> None:
        """Write the top-level overview Markdown + the schema index JSON."""
        schemas_sorted = sorted(all_schemas, key=lambda s: s.table_count, reverse=True)
        total_tables = sum(s.table_count for s in all_schemas)
        total_partitions = sum(
            sum(len(g.partitions) for g in groups.values())
            for groups in all_partition_groups.values()
        )
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cross_links = self.inferrer.cross_schema_links()

        context = {
            "schemas": schemas_sorted,
            "total_schemas": len(all_schemas),
            "total_tables": total_tables,
            "total_partition_groups": sum(len(g) for g in all_partition_groups.values()),
            "total_partitions": total_partitions,
            "partition_patterns": self.config.partition_patterns,
            "cross_schema_links": cross_links[:50],
            "generated_at": generated_at,
        }
        (self.output_dir / "summary" / "database_overview.md").write_text(
            self.env.get_template("database.md.j2").render(**context), encoding="utf-8"
        )

        index = {
            "generated_at": generated_at,
            "total_schemas": len(all_schemas),
            "total_tables": total_tables,
            "schemas": [
                {"name": s.schema_name, "table_count": s.table_count} for s in schemas_sorted
            ],
            "cross_schema_links": cross_links,
        }
        (self.output_dir / "summary" / "schema_index.json").write_text(
            json.dumps(index, indent=2), encoding="utf-8"
        )
