"""
Pattern detection: classify tables and collapse time-partitioned tables.

Two jobs:

1. **Categorise** every table (business / audit / config / infrastructure / ...)
   from its name, so the docs can highlight the interesting tables and play down
   the framework noise.
2. **Group partitions** — when a database has ``events_2021 ... events_2025``,
   we document a single ``events`` entry instead of five near-identical pages.

All of the rules come from :class:`~schemascribe.config.Config`, so the
behaviour is fully tunable without touching this file.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from schemascribe.config import Config
from schemascribe.models import PartitionGroup, SchemaInfo, TableInfo

logger = logging.getLogger(__name__)


# =============================================================================
# Categorisation
# =============================================================================

def classify_table(table_name: str, config: Config) -> str:
    """Return a category label for ``table_name``.

    Checks run in priority order; the first match wins. Returns one of:
    ``migration_metadata``, ``infrastructure``, ``audit``, ``raw``,
    ``intermediate``, ``config``, ``historical``, ``operational`` or
    ``business`` (the default).
    """
    name = table_name.lower()

    # 1. Exact infrastructure names (migration trackers, locks, ...)
    if name in {n.lower() for n in config.infrastructure_exact}:
        if "migration" in name or name in ("flyway_schema_history", "alembic_version"):
            return "migration_metadata"
        return "infrastructure"

    # 2. Infrastructure prefixes (schedulers, queues, batch frameworks)
    for prefix in config.infrastructure_prefixes:
        if name.startswith(prefix.lower()):
            return "infrastructure"

    # 3. Audit / change-tracking suffixes
    for suffix in config.audit_suffixes:
        if name.endswith(suffix.lower()):
            return "audit"
    if "_audit_" in name:
        return "audit"

    # 4. Raw ingestion tables
    if name.endswith("_raw") or "_raw_" in name:
        return "raw"

    # 5. Staging / intermediate / ETL
    if "_intermediate" in name or "_staging" in name or "_stage" in name:
        return "intermediate"
    if name.endswith("_etl") or name.endswith("_tmp") or name.endswith("_temp"):
        return "intermediate"

    # 6. Configuration
    if name.endswith("_config") or "_config_" in name or name.startswith("config_"):
        return "config"
    if name.endswith("_settings") or name.endswith("_setting"):
        return "config"

    # 7. Logs
    if name.endswith("_log") or name.endswith("_logs"):
        return "operational"

    return "business"


# =============================================================================
# Partition detection
# =============================================================================

def detect_partition(table_name: str, config: Config) -> Optional[Tuple[str, str]]:
    """If ``table_name`` looks like a partition, return ``(base_name, type)``.

    Otherwise return ``None``. The base name is the first regex capture group.
    """
    for pattern in config.partition_patterns:
        match = re.match(pattern.regex, table_name)
        if match:
            return match.group(1), pattern.type
    return None


def _extract_year(table_name: str) -> Optional[int]:
    """Pull a plausible 4-digit year (1970–2100) out of a partition name."""
    for match in re.finditer(r"(\d{4})", table_name):
        year = int(match.group(1))
        if 1970 <= year <= 2100:
            return year
    return None


_VARIANT_RE = re.compile(r"_(live|predicted|research|draft|final)$")


# =============================================================================
# Schema-level processing
# =============================================================================

def process_schema(
    schema_info: SchemaInfo, config: Config
) -> Tuple[List[TableInfo], Dict[str, PartitionGroup]]:
    """Categorise tables and build partition groups for one schema.

    Returns:
        ``(documentable_tables, partition_groups)`` where ``documentable_tables``
        is the list to render (individual tables plus one representative per
        partition group), and ``partition_groups`` maps base name -> group.
    """
    tables_by_name = {t.table_name: t for t in schema_info.tables}

    # --- Step 1: find candidate partitions --------------------------------
    groups: Dict[str, PartitionGroup] = {}
    partition_members: set[str] = set()

    for table in schema_info.tables:
        detected = detect_partition(table.table_name, config)
        if not detected:
            continue
        base_name, ptype = detected
        group = groups.setdefault(
            base_name,
            PartitionGroup(
                base_table_name=base_name,
                schema_name=schema_info.schema_name,
                partition_type=ptype,
            ),
        )
        group.partitions.append(table.table_name)
        partition_members.add(table.table_name)

        year = _extract_year(table.table_name)
        if year:
            lo, hi = group.year_range
            group.year_range = (min(year, lo or year), max(year, hi or year))

        variant = _VARIANT_RE.search(table.table_name)
        if variant and variant.group(1) not in group.variants:
            group.variants.append(variant.group(1))

    # --- Step 2: drop "groups" too small to be real partition sets --------
    for base_name in [b for b, g in groups.items() if len(g.partitions) < config.min_partition_group_size]:
        for member in groups[base_name].partitions:
            partition_members.discard(member)
        del groups[base_name]

    # --- Step 3: pick a representative table for each group ---------------
    for base_name, group in groups.items():
        if base_name in tables_by_name:
            group.representative_table = tables_by_name[base_name]
        elif group.partitions:
            # Most recent partition name sorts last; use it as the representative.
            rep_name = sorted(group.partitions)[-1]
            group.representative_table = tables_by_name.get(rep_name)

    # --- Step 4: categorise every table -----------------------------------
    for table in schema_info.tables:
        table.category = classify_table(table.table_name, config)
        if table.table_name in partition_members:
            table.is_partition = True
            detected = detect_partition(table.table_name, config)
            if detected:
                table.base_table_name, table.partition_type = detected

    # --- Step 5: build the documentable list ------------------------------
    # Non-partition tables are documented as-is; partition members are folded
    # into their group's representative.
    documentable: List[TableInfo] = [
        t for t in schema_info.tables if t.table_name not in partition_members
    ]
    for base_name, group in groups.items():
        if base_name not in tables_by_name and group.representative_table:
            rep = group.representative_table
            rep.base_table_name = base_name
            rep.partition_type = group.partition_type
            if rep not in documentable:
                documentable.append(rep)

    # --- Step 6: populate the schema's category buckets -------------------
    schema_info.business_tables = [t.table_name for t in documentable if t.category == "business"]
    schema_info.infrastructure_tables = [
        t.table_name for t in documentable
        if t.category in ("infrastructure", "migration_metadata")
    ]
    schema_info.audit_tables = [t.table_name for t in documentable if t.category == "audit"]

    logger.info(
        "  -> %s: %d tables, %d documentable, %d partition group(s)",
        schema_info.schema_name, len(schema_info.tables), len(documentable), len(groups),
    )
    return documentable, groups
