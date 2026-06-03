"""
Plain data models shared across SchemaScribe.

These are deliberately simple ``@dataclass`` containers with no behaviour beyond
holding the metadata we extract from the database. Keeping them separate from
the extraction and rendering logic makes them trivial to construct in tests and
to serialize to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ColumnInfo:
    """A single column on a table."""

    name: str
    data_type: str
    is_nullable: bool
    column_default: Optional[str]
    ordinal_position: int


@dataclass
class ForeignKeyInfo:
    """An explicit foreign-key constraint declared in the database.

    A composite key (more than one column) is represented by parallel lists:
    ``columns[i]`` references ``referenced_columns[i]``.
    """

    constraint_name: str
    columns: List[str]
    referenced_schema: str
    referenced_table: str
    referenced_columns: List[str]


@dataclass
class IndexInfo:
    """An index defined on a table."""

    index_name: str
    is_unique: bool
    index_definition: str


@dataclass
class TableInfo:
    """Everything we know about one table.

    The fields after ``table_comment`` are *derived* — they are filled in later
    by the pattern detector rather than read directly from the database.
    """

    schema_name: str
    table_name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)
    indexes: List[IndexInfo] = field(default_factory=list)
    estimated_row_count: int = 0
    table_size_bytes: int = 0
    table_comment: Optional[str] = None

    # --- Derived by patterns.py -------------------------------------------
    category: str = "business"
    is_partition: bool = False
    base_table_name: Optional[str] = None
    partition_type: Optional[str] = None

    @property
    def full_name(self) -> str:
        """Schema-qualified name, e.g. ``public.orders``."""
        return f"{self.schema_name}.{self.table_name}"

    @property
    def display_name(self) -> str:
        """Name to show in docs — the partition *base* name when applicable."""
        return self.base_table_name or self.table_name


@dataclass
class SchemaInfo:
    """A schema and all of its tables."""

    schema_name: str
    tables: List[TableInfo] = field(default_factory=list)

    # --- Derived category buckets (filled by patterns.py) -----------------
    business_tables: List[str] = field(default_factory=list)
    infrastructure_tables: List[str] = field(default_factory=list)
    audit_tables: List[str] = field(default_factory=list)

    @property
    def table_count(self) -> int:
        return len(self.tables)


@dataclass
class PartitionGroup:
    """A set of time-partitioned tables that share a common base name.

    For example ``events_2021``, ``events_2022``, ``events_2023`` collapse into
    one group with ``base_table_name="events"`` so the documentation shows a
    single entry instead of one page per year.
    """

    base_table_name: str
    schema_name: str
    partition_type: str = ""  # yearly, monthly, quarterly, ...
    partitions: List[str] = field(default_factory=list)
    year_range: Tuple[Optional[int], Optional[int]] = (None, None)
    variants: List[str] = field(default_factory=list)
    representative_table: Optional[TableInfo] = None
