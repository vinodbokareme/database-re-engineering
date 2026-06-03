"""
Relationship inference.

Real databases are full of *implied* relationships that were never declared as
foreign keys — a ``customer_id`` column that obviously points at
``customers.id``, for instance. SchemaScribe combines two signals:

1. **Explicit foreign keys** read straight from the catalog (always trusted).
2. **Naming conventions** — when a column name matches an entry in the
   configured ``reference_tables`` map, we suggest a likely join path and flag
   it with a confidence level.

The result is a set of per-table relationships plus a global list of
cross-schema links that the database overview can render.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from schemascribe.config import Config
from schemascribe.models import ForeignKeyInfo, SchemaInfo, TableInfo

logger = logging.getLogger(__name__)


@dataclass
class InferredRelationship:
    """A single suggested join between two columns."""

    source_schema: str
    source_table: str
    source_column: str
    target_schema: str
    target_table: str
    target_column: str
    confidence: str          # "explicit_fk" | "high" | "medium"
    inference_method: str    # "foreign_key" | "naming_convention"


@dataclass
class TableRelationships:
    """All relationships for one table: declared FKs plus inferred ones."""

    explicit_fks: List[ForeignKeyInfo] = field(default_factory=list)
    inferred: List[InferredRelationship] = field(default_factory=list)


@dataclass
class CrossSchemaLink:
    """A relationship that crosses a schema boundary (for the global index)."""

    from_schema: str
    from_table: str
    to_schema: str
    to_table: str
    join_key: str
    confidence: str


class RelationshipInferrer:
    """Builds and stores relationships as schemas are processed."""

    def __init__(self, config: Config):
        self.config = config
        self._by_table: Dict[str, Dict[str, TableRelationships]] = {}
        self._cross_schema: List[CrossSchemaLink] = []
        self._known_tables: Dict[str, set] = {}  # schema -> {table names}

    def register_schema(self, schema_info: SchemaInfo) -> None:
        """Remember which tables exist so we can rate inference confidence."""
        self._known_tables[schema_info.schema_name] = {t.table_name for t in schema_info.tables}

    def infer_for_table(self, table: TableInfo) -> TableRelationships:
        """Compute and store relationships for one table."""
        rels = TableRelationships(explicit_fks=list(table.foreign_keys))

        explicit_targets = {
            (fk.referenced_schema, fk.referenced_table) for fk in table.foreign_keys
        }

        for col in table.columns:
            targets = self.config.reference_tables.get(col.name.lower())
            if not targets:
                continue
            for target in targets:
                t_schema, t_table = target["schema"], target["table"]

                # Skip self-references and anything already covered by a real FK.
                if t_schema == table.schema_name and t_table == table.table_name:
                    continue
                if (t_schema, t_table) in explicit_targets:
                    continue

                exists = t_table in self._known_tables.get(t_schema, set())
                confidence = "high" if exists else "medium"

                rels.inferred.append(
                    InferredRelationship(
                        source_schema=table.schema_name,
                        source_table=table.table_name,
                        source_column=col.name,
                        target_schema=t_schema,
                        target_table=t_table,
                        target_column=target.get("column", "id"),
                        confidence=confidence,
                        inference_method="naming_convention",
                    )
                )

                if t_schema != table.schema_name:
                    self._cross_schema.append(
                        CrossSchemaLink(
                            from_schema=table.schema_name,
                            from_table=table.table_name,
                            to_schema=t_schema,
                            to_table=t_table,
                            join_key=col.name,
                            confidence=confidence,
                        )
                    )

        self._by_table.setdefault(table.schema_name, {})[table.table_name] = rels
        return rels

    def get(self, schema: str, table: str) -> Optional[TableRelationships]:
        return self._by_table.get(schema, {}).get(table)

    def cross_schema_links(self) -> List[dict]:
        """De-duplicated cross-schema links as plain dicts (for templates/JSON)."""
        seen = set()
        out: List[dict] = []
        for link in self._cross_schema:
            key = (link.from_schema, link.from_table, link.to_schema, link.to_table, link.join_key)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "from_schema": link.from_schema,
                    "from_table": link.from_table,
                    "to_schema": link.to_schema,
                    "to_table": link.to_table,
                    "join_key": link.join_key,
                    "confidence": link.confidence,
                }
            )
        return out

    def join_paths_for(self, table: TableInfo) -> List[str]:
        """Render human-readable ``JOIN ...`` suggestions for a table."""
        rels = self.get(table.schema_name, table.table_name)
        if not rels:
            return []

        paths: List[str] = []
        for fk in rels.explicit_fks:
            cols = ", ".join(fk.columns)
            ref_cols = ", ".join(fk.referenced_columns)
            paths.append(
                f"JOIN {fk.referenced_schema}.{fk.referenced_table} "
                f"ON {table.table_name}.{cols} = {fk.referenced_table}.{ref_cols}  "
                f"-- explicit FK"
            )
        for rel in rels.inferred:
            paths.append(
                f"JOIN {rel.target_schema}.{rel.target_table} "
                f"ON {table.table_name}.{rel.source_column} = "
                f"{rel.target_table}.{rel.target_column}  "
                f"-- inferred ({rel.confidence})"
            )
        return paths
