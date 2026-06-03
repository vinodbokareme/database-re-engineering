"""
Metadata extraction from PostgreSQL's ``information_schema`` and ``pg_catalog``.

Design goals:

* **No N+1 queries.** Each kind of metadata (columns, keys, indexes, ...) is
  fetched for a whole schema in a single batch query, then grouped in memory.
* **Resilient.** Every query is retried on transient connection errors so one
  slow query can't sink a multi-hour run.
* **Observable.** Slow queries are logged with their timing.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Dict, List

import psycopg2

from schemascribe.models import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    SchemaInfo,
    TableInfo,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Retry decorator
# =============================================================================

def retry_on_db_error(max_retries: int = 2, backoff: float = 3.0):
    """Retry a method on *transient* database errors only.

    Programming errors (bad SQL, missing table) are re-raised immediately —
    retrying those would just waste time.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                    last_error = exc
                    if attempt < max_retries:
                        wait = backoff * attempt
                        logger.warning(
                            "  [retry %d/%d] %s failed: %s — waiting %.1fs",
                            attempt, max_retries, func.__name__, exc, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error("  [failed] %s after %d attempts", func.__name__, max_retries)
                        raise
                except psycopg2.Error as exc:
                    logger.error("  [db error] %s: %s", func.__name__, exc)
                    raise
            raise RuntimeError(f"{func.__name__} exhausted retries: {last_error}")

        return wrapper

    return decorator


# =============================================================================
# SQL — one batch query per metadata type, parameterised by schema
# =============================================================================

SQL_SCHEMAS = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name NOT LIKE 'pg_%'
      AND schema_name <> 'information_schema'
    ORDER BY schema_name;
"""

SQL_TABLES = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = %s
      AND table_type = 'BASE TABLE'
    ORDER BY table_name;
"""

SQL_COLUMNS = """
    SELECT table_name, column_name, data_type, is_nullable, column_default,
           ordinal_position, udt_name, character_maximum_length,
           numeric_precision, numeric_scale
    FROM information_schema.columns
    WHERE table_schema = %s
    ORDER BY table_name, ordinal_position;
"""

SQL_PRIMARY_KEYS = """
    SELECT cl.relname AS table_name,
           att.attname AS column_name,
           cols.ord    AS ordinal_position
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class cl ON cl.oid = con.conrelid
    JOIN pg_catalog.pg_namespace nsp ON nsp.oid = cl.relnamespace
    CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS cols(colnum, ord)
    JOIN pg_catalog.pg_attribute att
         ON att.attrelid = con.conrelid AND att.attnum = cols.colnum
    WHERE con.contype = 'p' AND nsp.nspname = %s
    ORDER BY cl.relname, cols.ord;
"""

SQL_FOREIGN_KEYS = """
    SELECT cl.relname      AS table_name,
           con.conname     AS constraint_name,
           att.attname     AS column_name,
           nsp_ref.nspname AS referenced_schema,
           cl_ref.relname  AS referenced_table,
           att_ref.attname AS referenced_column
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class cl ON cl.oid = con.conrelid
    JOIN pg_catalog.pg_namespace nsp ON nsp.oid = cl.relnamespace
    JOIN pg_catalog.pg_class cl_ref ON cl_ref.oid = con.confrelid
    JOIN pg_catalog.pg_namespace nsp_ref ON nsp_ref.oid = cl_ref.relnamespace
    CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
         WITH ORDINALITY AS cols(conkey, confkey, ord)
    JOIN pg_catalog.pg_attribute att
         ON att.attrelid = con.conrelid AND att.attnum = cols.conkey
    JOIN pg_catalog.pg_attribute att_ref
         ON att_ref.attrelid = con.confrelid AND att_ref.attnum = cols.confkey
    WHERE con.contype = 'f' AND nsp.nspname = %s
    ORDER BY cl.relname, con.conname, cols.ord;
"""

# pg_class is dramatically faster than information_schema for sizes/counts.
SQL_TABLE_STATS = """
    SELECT c.relname AS table_name,
           c.reltuples::bigint AS estimated_row_count,
           pg_total_relation_size(c.oid) AS table_size_bytes
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
    ORDER BY c.relname;
"""

SQL_TABLE_COMMENTS = """
    SELECT c.relname AS table_name,
           pg_catalog.obj_description(c.oid, 'pg_class') AS table_comment
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
      AND pg_catalog.obj_description(c.oid, 'pg_class') IS NOT NULL;
"""

SQL_INDEXES = """
    SELECT tablename AS table_name,
           indexname AS index_name,
           indexdef  AS index_definition
    FROM pg_catalog.pg_indexes
    WHERE schemaname = %s
    ORDER BY tablename, indexname;
"""


class MetadataExtractor:
    """Pulls structural metadata out of a live PostgreSQL connection."""

    def __init__(self, connection):
        self.conn = connection
        self.query_times: Dict[str, float] = {}

    # --- low-level ---------------------------------------------------------

    def _execute(self, query: str, params=None, name: str = "") -> List[dict]:
        start = time.time()
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        elapsed = time.time() - start
        if name:
            self.query_times[name] = elapsed
            if elapsed > 5.0:
                logger.warning("    slow query '%s': %.2fs (%d rows)", name, elapsed, len(rows))
        return rows

    @staticmethod
    def _format_data_type(row: dict) -> str:
        """Render a friendly type string with precision, e.g. ``varchar(255)``."""
        dt = row["data_type"]
        if dt == "character varying" and row.get("character_maximum_length"):
            return f"varchar({row['character_maximum_length']})"
        if dt == "character" and row.get("character_maximum_length"):
            return f"char({row['character_maximum_length']})"
        if dt == "numeric" and row.get("numeric_precision"):
            return f"numeric({row['numeric_precision']},{row.get('numeric_scale', 0)})"
        if dt == "ARRAY":
            return f"{row.get('udt_name', 'array')}[]"
        if dt == "USER-DEFINED":
            return row.get("udt_name", "user_defined")
        return dt

    # --- per-type fetchers -------------------------------------------------

    @retry_on_db_error()
    def get_schemas(self) -> List[str]:
        rows = self._execute(SQL_SCHEMAS, name="schemas")
        schemas = [r["schema_name"] for r in rows]
        logger.info("Discovered %d schema(s).", len(schemas))
        return schemas

    @retry_on_db_error()
    def get_tables(self, schema: str) -> List[str]:
        rows = self._execute(SQL_TABLES, (schema,), name=f"{schema}/tables")
        return [r["table_name"] for r in rows]

    @retry_on_db_error()
    def get_columns(self, schema: str) -> Dict[str, List[ColumnInfo]]:
        rows = self._execute(SQL_COLUMNS, (schema,), name=f"{schema}/columns")
        out: Dict[str, List[ColumnInfo]] = {}
        for r in rows:
            out.setdefault(r["table_name"], []).append(
                ColumnInfo(
                    name=r["column_name"],
                    data_type=self._format_data_type(r),
                    is_nullable=(r["is_nullable"] == "YES"),
                    column_default=r["column_default"],
                    ordinal_position=r["ordinal_position"],
                )
            )
        return out

    @retry_on_db_error()
    def get_primary_keys(self, schema: str) -> Dict[str, List[str]]:
        rows = self._execute(SQL_PRIMARY_KEYS, (schema,), name=f"{schema}/pks")
        out: Dict[str, List[str]] = {}
        for r in rows:
            out.setdefault(r["table_name"], []).append(r["column_name"])
        return out

    @retry_on_db_error()
    def get_foreign_keys(self, schema: str) -> Dict[str, List[ForeignKeyInfo]]:
        rows = self._execute(SQL_FOREIGN_KEYS, (schema,), name=f"{schema}/fks")
        # Group rows by (table, constraint) to reassemble composite keys.
        grouped: Dict[str, Dict[str, dict]] = {}
        for r in rows:
            table, constraint = r["table_name"], r["constraint_name"]
            by_constraint = grouped.setdefault(table, {})
            entry = by_constraint.setdefault(
                constraint,
                {
                    "constraint_name": constraint,
                    "columns": [],
                    "referenced_schema": r["referenced_schema"],
                    "referenced_table": r["referenced_table"],
                    "referenced_columns": [],
                },
            )
            entry["columns"].append(r["column_name"])
            entry["referenced_columns"].append(r["referenced_column"])

        return {
            table: [ForeignKeyInfo(**data) for data in constraints.values()]
            for table, constraints in grouped.items()
        }

    @retry_on_db_error()
    def get_table_stats(self, schema: str) -> Dict[str, dict]:
        rows = self._execute(SQL_TABLE_STATS, (schema,), name=f"{schema}/stats")
        return {
            r["table_name"]: {
                "estimated_row_count": max(0, r["estimated_row_count"] or 0),
                "table_size_bytes": r["table_size_bytes"] or 0,
            }
            for r in rows
        }

    @retry_on_db_error()
    def get_table_comments(self, schema: str) -> Dict[str, str]:
        rows = self._execute(SQL_TABLE_COMMENTS, (schema,), name=f"{schema}/comments")
        return {r["table_name"]: r["table_comment"] for r in rows}

    @retry_on_db_error()
    def get_indexes(self, schema: str) -> Dict[str, List[IndexInfo]]:
        rows = self._execute(SQL_INDEXES, (schema,), name=f"{schema}/indexes")
        out: Dict[str, List[IndexInfo]] = {}
        for r in rows:
            definition = r["index_definition"] or ""
            out.setdefault(r["table_name"], []).append(
                IndexInfo(
                    index_name=r["index_name"],
                    is_unique="UNIQUE" in definition,
                    index_definition=definition,
                )
            )
        return out

    # --- orchestration -----------------------------------------------------

    def extract_schema(self, schema: str) -> SchemaInfo:
        """Fetch and assemble every table in one schema into a ``SchemaInfo``."""
        start = time.time()
        logger.info("Extracting schema: %s", schema)

        tables = self.get_tables(schema)
        columns = self.get_columns(schema)
        pks = self.get_primary_keys(schema)
        fks = self.get_foreign_keys(schema)
        stats = self.get_table_stats(schema)
        comments = self.get_table_comments(schema)
        indexes = self.get_indexes(schema)

        table_infos: List[TableInfo] = []
        for name in tables:
            s = stats.get(name, {})
            table_infos.append(
                TableInfo(
                    schema_name=schema,
                    table_name=name,
                    columns=columns.get(name, []),
                    primary_key=pks.get(name, []),
                    foreign_keys=fks.get(name, []),
                    indexes=indexes.get(name, []),
                    estimated_row_count=s.get("estimated_row_count", 0),
                    table_size_bytes=s.get("table_size_bytes", 0),
                    table_comment=comments.get(name),
                )
            )

        logger.info("  -> %d table(s) in %.1fs", len(table_infos), time.time() - start)
        return SchemaInfo(schema_name=schema, tables=table_infos)
