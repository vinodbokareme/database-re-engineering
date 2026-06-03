"""
Configuration for SchemaScribe.

Everything that used to be hard-coded — which schemas to skip, how partitioned
tables are named, which columns mean what — lives here as **overridable
defaults**. You can run SchemaScribe with zero configuration and get good
results on any database, then tune it for your own conventions with a small
YAML file.

Resolution order (later wins):

1. Built-in defaults (the constants in this module).
2. Values from a ``config.yaml`` you pass with ``--config``.
3. Database credentials from environment variables (``PGHOST`` etc.), which
   always take precedence so secrets never live in the YAML file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# =============================================================================
# Built-in defaults
# =============================================================================

# System schemas that are never interesting to document.
DEFAULT_EXCLUDED_SCHEMAS: List[str] = [
    "pg_catalog",
    "information_schema",
    "pg_toast",
    "pg_temp_1",
    "pg_toast_temp_1",
]

# Regex patterns used to recognise time-partitioned tables. Order matters: the
# first pattern that matches wins. Each entry maps a regex to a human label.
# The first capture group is treated as the partition *base* name.
DEFAULT_PARTITION_PATTERNS: List[Dict[str, str]] = [
    {"regex": r"^(.+)_(\d{4})_(\d{2})_(live|predicted|research)$", "type": "monthly-variant"},
    {"regex": r"^(.+)_(\d{4})_q(\d)$", "type": "quarterly"},
    {"regex": r"^(.+)_(\d{4})_(\d{2})$", "type": "monthly"},
    {"regex": r"^(.+)_(\d{6})$", "type": "monthly"},
    {"regex": r"^(.+)_(\d{4})$", "type": "yearly"},
    {"regex": r"^(.+)_(default|old|backup)$", "type": "special"},
]

# Tables whose exact name marks them as framework/infrastructure noise.
DEFAULT_INFRASTRUCTURE_EXACT: List[str] = [
    "flyway_schema_history",
    "schema_migrations",
    "alembic_version",
    "django_migrations",
    "revinfo",
    "shedlock",
]

# Name prefixes that mark a table as infrastructure (job schedulers, queues,
# batch frameworks, etc.).
DEFAULT_INFRASTRUCTURE_PREFIXES: List[str] = [
    "qrtz_",        # Quartz scheduler
    "batch_job_",   # Spring Batch
    "batch_step_",
    "celery_",      # Celery
    "knex_",        # Knex migrations
]

# Suffixes that mark audit / change-tracking tables.
DEFAULT_AUDIT_SUFFIXES: List[str] = ["_audit", "_aud", "_audit_log", "_history", "_hist"]

# Maps a domain *tag* to the keywords (substrings) that suggest it. Used purely
# for labelling — tweak freely for your own domain language.
DEFAULT_DOMAIN_VOCABULARY: Dict[str, List[str]] = {
    "reference_data": ["entity", "mapping", "lookup", "ref", "master", "catalog"],
    "transactional": ["order", "transaction", "payment", "invoice", "trade", "booking"],
    "user_account": ["user", "account", "member", "profile", "login", "session"],
    "audit": ["audit", "history", "revinfo", "log", "tracking", "changelog"],
    "config": ["config", "setting", "parameter", "preference", "feature_flag"],
    "workflow": ["workflow", "task", "job", "process", "queue", "schedule", "notification"],
    "analytics": ["metric", "aggregate", "report", "summary", "stat", "score", "rollup"],
    "geo": ["country", "region", "city", "address", "location", "geo"],
}

# A glossary of *universally common* column names and what they mean. These are
# generic across virtually every business database. Extend it in your YAML with
# names specific to your own data.
DEFAULT_COLUMN_GLOSSARY: Dict[str, str] = {
    "id": "Unique identifier for this record",
    "uuid": "Universally unique identifier (UUID)",
    "guid": "Globally unique identifier",
    "name": "Display name",
    "title": "Title text",
    "label": "Display label",
    "description": "Human-readable description",
    "code": "Short code identifier",
    "type": "Classification type",
    "category": "Category classification",
    "status": "Current status of the record",
    "state": "Current state in a workflow",
    "priority": "Processing or business priority level",
    "rank": "Ranking position",
    "sequence": "Order / sequence number",
    "sort_order": "Display sort order",
    "version": "Version number for optimistic locking / change tracking",
    "revision": "Revision number for audit tracking",
    "comment": "Free-text comment or note",
    "comments": "Free-text comments or notes",
    "reason": "Reason for a change or action",
    "source": "System or source that provided this data",
    # Lifecycle timestamps
    "created_at": "Timestamp when this record was first created",
    "updated_at": "Timestamp when this record was last modified",
    "created_on": "Timestamp when this record was first created",
    "modified_on": "Timestamp when this record was last modified",
    "deleted_at": "Timestamp when this record was soft-deleted",
    "created_by": "User or system that created this record",
    "updated_by": "User or system that last modified this record",
    "modified_by": "User or system that last modified this record",
    # Common booleans
    "is_active": "Whether this record is currently active",
    "is_deleted": "Whether this record has been soft-deleted",
    "is_latest": "Whether this is the most current version",
    "is_primary": "Whether this is the primary / default record",
    "is_default": "Whether this is the default record",
    "enabled": "Whether this record is enabled",
    # Money / quantity
    "amount": "Monetary amount",
    "price": "Price value",
    "quantity": "Quantity / count",
    "currency": "ISO 4217 currency code (e.g. USD, EUR, GBP)",
    "total": "Total value",
    "balance": "Account or running balance",
    # Contact / geo
    "email": "Email address",
    "phone": "Phone number",
    "country": "Country name or code",
    "country_code": "ISO country code",
    "region": "Geographic region",
    "city": "City name",
    "postal_code": "Postal / ZIP code",
    "timezone": "Time zone identifier",
    "locale": "Locale / language tag (e.g. en-US)",
    # Public financial identifiers (open standards, safe to keep)
    "isin": "International Securities Identification Number (12 chars, ISO 6166)",
    "cusip": "CUSIP identifier (9-char North American security ID)",
    "sedol": "SEDOL identifier (7-char UK/Ireland security ID)",
    "lei": "Legal Entity Identifier (20 chars, ISO 17442)",
    "figi": "Financial Instrument Global Identifier",
    "ticker": "Exchange ticker symbol",
    "mic": "Market Identifier Code (ISO 10383 exchange code)",
}

DEFAULT_STATEMENT_TIMEOUT_MS = 120_000  # 2 minutes per query
DEFAULT_CONNECT_TIMEOUT_S = 30
DEFAULT_SSLMODE = "prefer"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class DatabaseConfig:
    """How to reach the database. Credentials come from the environment."""

    host: str = "localhost"
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""
    sslmode: str = DEFAULT_SSLMODE
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT_S

    @classmethod
    def from_env(cls, overrides: Optional[dict] = None) -> "DatabaseConfig":
        """Build from ``PG*`` environment variables, with optional YAML overrides
        for the non-secret fields (sslmode, timeouts)."""
        overrides = overrides or {}
        return cls(
            host=os.environ.get("PGHOST", overrides.get("host", "localhost")),
            port=int(os.environ.get("PGPORT", overrides.get("port", 5432))),
            database=os.environ.get("PGDATABASE", overrides.get("database", "")),
            user=os.environ.get("PGUSER", overrides.get("user", "")),
            password=os.environ.get("PGPASSWORD", overrides.get("password", "")),
            sslmode=os.environ.get("PGSSLMODE", overrides.get("sslmode", DEFAULT_SSLMODE)),
            statement_timeout_ms=int(
                overrides.get("statement_timeout_ms", DEFAULT_STATEMENT_TIMEOUT_MS)
            ),
            connect_timeout=int(overrides.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT_S)),
        )

    def missing_fields(self) -> List[str]:
        """Return the names of required fields that are empty."""
        missing = []
        if not self.database:
            missing.append("PGDATABASE")
        if not self.user:
            missing.append("PGUSER")
        if not self.password:
            missing.append("PGPASSWORD")
        return missing


@dataclass
class PartitionPattern:
    """One partition-naming rule: a regex plus the label to report when it hits."""

    regex: str
    type: str


@dataclass
class Config:
    """The complete, resolved configuration for a run."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    excluded_schemas: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_SCHEMAS))
    partition_patterns: List[PartitionPattern] = field(
        default_factory=lambda: [PartitionPattern(**p) for p in DEFAULT_PARTITION_PATTERNS]
    )
    infrastructure_exact: List[str] = field(
        default_factory=lambda: list(DEFAULT_INFRASTRUCTURE_EXACT)
    )
    infrastructure_prefixes: List[str] = field(
        default_factory=lambda: list(DEFAULT_INFRASTRUCTURE_PREFIXES)
    )
    audit_suffixes: List[str] = field(default_factory=lambda: list(DEFAULT_AUDIT_SUFFIXES))
    domain_vocabulary: Dict[str, List[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_DOMAIN_VOCABULARY.items()}
    )
    column_glossary: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_COLUMN_GLOSSARY)
    )
    # Optional: tables that other tables tend to reference. Maps a column name
    # to the table that "owns" it, so we can infer join paths even when no
    # foreign key is declared. Example:
    #   {"customer_id": [{"schema": "public", "table": "customers", "column": "id"}]}
    reference_tables: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    # A group with fewer than this many members is not treated as a partition set.
    min_partition_group_size: int = 2

    @classmethod
    def default(cls) -> "Config":
        """Return a config with built-in defaults and credentials from the env."""
        cfg = cls()
        cfg.database = DatabaseConfig.from_env()
        return cfg

    @classmethod
    def load(cls, path: Optional[str | Path]) -> "Config":
        """Load configuration, merging an optional YAML file over the defaults.

        ``path`` may be ``None`` (use defaults only). Database credentials are
        always read from the environment regardless of the YAML contents.
        """
        cfg = cls()

        data: dict = {}
        if path:
            data = _read_yaml(path)

        if "excluded_schemas" in data:
            cfg.excluded_schemas = list(data["excluded_schemas"])
        if "partition_patterns" in data:
            cfg.partition_patterns = [PartitionPattern(**p) for p in data["partition_patterns"]]
        if "infrastructure_exact" in data:
            cfg.infrastructure_exact = list(data["infrastructure_exact"])
        if "infrastructure_prefixes" in data:
            cfg.infrastructure_prefixes = list(data["infrastructure_prefixes"])
        if "audit_suffixes" in data:
            cfg.audit_suffixes = list(data["audit_suffixes"])
        if "domain_vocabulary" in data:
            cfg.domain_vocabulary = {k: list(v) for k, v in data["domain_vocabulary"].items()}
        if "reference_tables" in data:
            cfg.reference_tables = data["reference_tables"]
        if "min_partition_group_size" in data:
            cfg.min_partition_group_size = int(data["min_partition_group_size"])

        # Merge the YAML glossary *on top of* the defaults so users only add deltas.
        if "column_glossary" in data:
            cfg.column_glossary.update(data["column_glossary"])

        cfg.database = DatabaseConfig.from_env(data.get("database"))
        return cfg


def _read_yaml(path: str | Path) -> dict:
    """Read a YAML file into a dict, with a friendly error if PyYAML is missing."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Reading a config file requires PyYAML. Install it with "
            "`pip install pyyaml`, or run without --config to use defaults."
        ) from exc

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file {p} must contain a YAML mapping at the top level.")
    return loaded
