"""
Plain-English inference.

This module turns dry metadata into sentences a human (or an LLM) can actually
read: what a table is probably *for*, what each column likely means, which tags
apply, and what to watch out for. None of it touches the database — it works
purely from names, types and the configured glossary/vocabulary.

Everything here is best-effort and clearly labelled as inferred. When the
database has a real comment, that always wins over a guess.
"""

from __future__ import annotations

from typing import List, Optional

from schemascribe.config import Config
from schemascribe.models import PartitionGroup, TableInfo

# Human-friendly phrasing for each domain tag used in table descriptions.
_DOMAIN_DESCRIPTIONS = {
    "reference_data": "master reference data (entities, lookups, mappings)",
    "transactional": "business transactions",
    "user_account": "user accounts and profiles",
    "audit": "audit trails and change tracking",
    "config": "configuration and business rules",
    "workflow": "operational workflow and process management",
    "analytics": "metrics, aggregates and analytics",
    "geo": "geographic and location data",
}


# =============================================================================
# Table-level inference
# =============================================================================

def infer_tags(table: TableInfo, config: Config) -> List[str]:
    """Infer a sorted list of domain tags for a table from its name + category."""
    tags: set[str] = set()
    name = table.display_name.lower()

    for tag, keywords in config.domain_vocabulary.items():
        if any(keyword in name for keyword in keywords):
            tags.add(tag)

    if table.category == "audit":
        tags.add("audit")
    if table.category == "config":
        tags.add("config")

    return sorted(tags) if tags else ["general"]


def infer_business_purpose(
    table: TableInfo, config: Config, partition_group: Optional[PartitionGroup] = None
) -> str:
    """Compose a one-paragraph, plain-English guess at what the table is for.

    If the database has a real comment on the table, that is returned verbatim.
    """
    if table.table_comment:
        return table.table_comment.strip()

    name = table.display_name.lower()
    tokens = name.split("_")

    # Which domains does the name touch?
    domains = [
        tag for tag, keywords in config.domain_vocabulary.items()
        if any(keyword in name for keyword in keywords)
    ]
    friendly = [_DOMAIN_DESCRIPTIONS.get(d, d.replace("_", " ")) for d in domains]
    subject = " and ".join(friendly[:2]) if friendly else "business"

    # Pick a sentence shape from the table's structural role.
    if "master" in tokens:
        body = f"The authoritative source for {subject}; other tables reference it as the single source of truth"
    elif table.category == "config":
        body = f"Stores configuration settings and business rules for {subject}"
    elif table.category == "audit":
        body = f"Records every change to the related table, providing a full audit trail for {subject}"
    elif "mapping" in tokens or "map" in tokens:
        body = f"Links identifiers across systems for {subject}"
    elif "lookup" in tokens or "ref" in tokens:
        body = f"A reference lookup table providing standardised values for {subject}"
    elif table.category == "intermediate":
        body = f"An intermediate / staging table used while loading or transforming {subject}"
    elif table.category == "raw":
        body = f"Stores raw, unprocessed data as received from its source for {subject}"
    elif table.category == "operational":
        body = f"Captures operational log entries for {subject}"
    else:
        body = f"Stores {subject} data used in day-to-day operations"

    if partition_group:
        body += f". The data is time-partitioned ({partition_group.partition_type})"
        lo, hi = partition_group.year_range
        if lo and hi:
            body += f", spanning {lo} to {hi}"
        body += ", so each period has its own storage segment for performance"

    return f"{body}. _(inferred from naming)_"


def infer_technical_purpose(
    table: TableInfo, partition_group: Optional[PartitionGroup] = None
) -> str:
    """A terse, structural one-liner (keys, FKs, size)."""
    parts: List[str] = []
    if partition_group:
        parts.append(
            f"Parent of {len(partition_group.partitions)} {partition_group.partition_type} partitions"
        )
    if table.primary_key:
        parts.append(f"Primary key: {', '.join(table.primary_key)}")
    if table.foreign_keys:
        parts.append(f"{len(table.foreign_keys)} foreign-key constraint(s)")
    if table.estimated_row_count > 0:
        parts.append(f"~{table.estimated_row_count:,} rows estimated")
    if not parts:
        parts.append("Standard relational table")
    return ". ".join(parts) + "."


def infer_risk_notes(
    table: TableInfo, partition_group: Optional[PartitionGroup] = None
) -> List[str]:
    """Surface cautions a query author should know before using the table."""
    notes: List[str] = []

    if partition_group:
        notes.append(f"Large partition set ({len(partition_group.partitions)} partitions)")
        lo, hi = partition_group.year_range
        if lo and hi and (hi - lo) > 20:
            notes.append(f"Spans {hi - lo}+ years — a query without a date filter may be expensive")

    if table.category == "audit":
        notes.append("Audit table — use for change history, not current-state queries")
    if table.category == "intermediate":
        notes.append("Staging table — may contain transient or incomplete data")
    if table.category == "raw":
        notes.append("Raw table — data may not be cleansed or validated")
    if table.estimated_row_count > 100_000_000:
        notes.append(f"Very large table (~{table.estimated_row_count:,} rows)")
    if "_old" in table.table_name or "_backup" in table.table_name or "_deprecated" in table.table_name:
        notes.append("Looks deprecated/backup — prefer the current version")
    if not table.primary_key:
        notes.append("No primary key — rows may not be uniquely identifiable")

    return notes or ["No specific risks identified"]


def llm_summary(table: TableInfo, partition_group: Optional[PartitionGroup] = None) -> str:
    """A single dense sentence designed to brief an AI assistant on the table."""
    category_phrase = {
        "business": "a core business table",
        "raw": "a raw ingestion table (unprocessed source data)",
        "intermediate": "an intermediate/staging table",
        "audit": "an audit/change-tracking table",
        "config": "a configuration table",
        "infrastructure": "an infrastructure table (framework noise)",
        "migration_metadata": "a schema-migration tracking table",
        "operational": "an operational log table",
    }
    parts = [f"`{table.full_name}` is {category_phrase.get(table.category, 'a data table')}"]
    if partition_group:
        parts.append(
            f"split into {len(partition_group.partitions)} {partition_group.partition_type} partitions"
        )
        lo, hi = partition_group.year_range
        if lo and hi:
            parts.append(f"covering {lo}-{hi}")
    parts.append(f"with {len(table.columns)} columns")
    if table.primary_key:
        parts.append(f"keyed by `{', '.join(table.primary_key)}`")
    if table.estimated_row_count > 1_000_000:
        parts.append(f"~{table.estimated_row_count:,} rows")

    if table.category in ("infrastructure", "migration_metadata"):
        parts.append("— skip unless investigating system internals")
    elif table.category == "audit":
        parts.append("— only query for change history")
    elif table.category == "raw":
        parts.append("— prefer the processed version when available")
    return ", ".join(parts) + "."


# =============================================================================
# Column-level inference
# =============================================================================

def infer_column_meaning(col_name: str, data_type: str, config: Config) -> str:
    """Best-effort plain-English meaning for a single column.

    Strategy: exact match against the glossary first, then a long ladder of
    suffix/prefix heuristics, then a humanised fallback derived from the name.
    """
    name = col_name.lower()

    # 1. Exact glossary hit (user glossary merged over the built-in defaults).
    if name in config.column_glossary:
        return config.column_glossary[name]

    # 2. References / identifiers
    if name.endswith("_id") and name != "id":
        return f"Reference to the {_humanise(name[:-3])} record"
    if name.endswith("_uuid"):
        return f"UUID reference to {_humanise(name[:-5])}"
    if name.endswith("_code"):
        return f"{_humanise(name[:-5])} classification code"
    if name.endswith("_key"):
        return f"{_humanise(name[:-4])} lookup key"

    # 3. Dates and timestamps
    if name.endswith("_date") or name.endswith("_dt"):
        return f"{_humanise(name.rsplit('_', 1)[0])} date"
    if name.endswith("_timestamp") or name.endswith("_ts"):
        return f"{_humanise(name.rsplit('_', 1)[0])} timestamp"
    if name.endswith("_at") and "timestamp" in data_type:
        return f"Timestamp when {_humanise(name[:-3]).lower()} occurred"

    # 4. Money / numeric values
    for suffix, phrase in (
        ("_price", "price value"), ("_amount", "monetary amount"), ("_amt", "monetary amount"),
        ("_value", "value"), ("_val", "value"), ("_rate", "rate"), ("_ratio", "ratio"),
        ("_factor", "adjustment factor"), ("_pct", "percentage"), ("_percent", "percentage"),
        ("_percentage", "percentage"), ("_weight", "weight / proportion"), ("_score", "score"),
        ("_rank", "ranking position"),
    ):
        if name.endswith(suffix):
            return f"{_humanise(name[: -len(suffix)])} {phrase}"

    # 5. Counts and sizes
    if name.endswith("_count") or name.endswith("_cnt"):
        return f"Number of {_humanise(name.rsplit('_', 1)[0]).lower()} items"
    if name.endswith("_size"):
        return f"{_humanise(name[:-5])} size"
    if name.endswith("_num") or name.endswith("_number"):
        return f"{_humanise(name.rsplit('_', 1)[0])} number"

    # 6. Booleans / flags
    if name.startswith(("is_", "has_", "can_", "should_")):
        return f"Whether the record {_humanise(name.split('_', 1)[1]).lower()}"
    if name.endswith("_flag") or name.endswith("_ind"):
        return f"{_humanise(name.rsplit('_', 1)[0])} indicator (yes/no)"
    if name.endswith("_enabled") or name.endswith("_active"):
        return f"Whether {_humanise(name.rsplit('_', 1)[0]).lower()} is enabled/active"

    # 7. Names, descriptions, labels
    if name.endswith("_name") or name.endswith("_nm"):
        return f"{_humanise(name.rsplit('_', 1)[0])} name"
    if name.endswith("_desc") or name.endswith("_description"):
        return f"{_humanise(name.rsplit('_', 1)[0])} description"
    if name.endswith("_label"):
        return f"{_humanise(name[:-6])} display label"

    # 8. Status / type / category / level
    for suffix in ("_status", "_type", "_category", "_level", "_state"):
        if name.endswith(suffix):
            return f"{_humanise(name[: -len(suffix)])} {suffix[1:]}"

    # 9. URLs, paths, contacts
    if name.endswith("_url") or name.endswith("_uri"):
        return f"{_humanise(name.rsplit('_', 1)[0])} web address"
    if name.endswith("_path"):
        return f"{_humanise(name[:-5])} file path"
    if name.endswith("_email"):
        return f"{_humanise(name[:-6])} email address"

    # 10. Fallback — just make the raw name readable.
    readable = _humanise(name)
    return readable if readable else "—"


def _humanise(token: str) -> str:
    """Turn ``some_snake_case`` into ``Some Snake Case``."""
    return token.replace("_", " ").strip().title()


# =============================================================================
# Sample queries
# =============================================================================

def sample_queries(table: TableInfo, join_paths: List[str]) -> List[str]:
    """Generate two or three illustrative SQL snippets for the docs."""
    full = table.full_name if not table.base_table_name else f"{table.schema_name}.{table.display_name}"
    queries: List[str] = []

    if table.columns:
        cols = ", ".join(c.name for c in table.columns[:5])
        queries.append(f"-- Browse recent rows\nSELECT {cols}\nFROM {full}\nLIMIT 100;")

    if table.primary_key:
        queries.append(
            f"-- Look up by primary key\n"
            f"SELECT *\nFROM {full}\nWHERE {table.primary_key[0]} = '<value>';"
        )

    if join_paths:
        queries.append(f"-- Join to a related table\nSELECT t.*\nFROM {full} t\n{join_paths[0]}\nLIMIT 50;")

    return queries[:3]
