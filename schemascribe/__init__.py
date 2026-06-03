"""
SchemaScribe — turn any PostgreSQL database into beautiful, human- and
AI-readable documentation.

SchemaScribe connects to a database in **read-only** mode, extracts its full
structure (schemas, tables, columns, keys, indexes, sizes), figures out what
each table is *for* using naming conventions and a configurable glossary, then
renders clean Markdown + JSON docs you can commit, browse, or feed to an LLM.

Typical usage from Python::

    from schemascribe import Config, run

    config = Config.load("config.yaml")   # or Config.default()
    run(config, output_dir="docs")

Most people just use the command line::

    schemascribe --output docs

Author: Vinod Bokare
"""

from schemascribe.config import Config, DatabaseConfig, PartitionPattern
from schemascribe.models import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    SchemaInfo,
    TableInfo,
)
from schemascribe.pipeline import run

__all__ = [
    "Config",
    "DatabaseConfig",
    "PartitionPattern",
    "ColumnInfo",
    "ForeignKeyInfo",
    "IndexInfo",
    "TableInfo",
    "SchemaInfo",
    "run",
]

__version__ = "0.1.0"
__author__ = "Vinod Bokare"
