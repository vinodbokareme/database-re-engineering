"""
The end-to-end run: connect → extract → detect patterns → infer → render.

This is the orchestrator the CLI calls. It is deliberately resilient:

* Each schema is processed independently, so one bad schema can't abort the run.
* A checkpoint file records completed schemas, so ``--resume`` skips work that
  already succeeded.
* A failure report is written for anything that could not be documented.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from schemascribe.config import Config
from schemascribe.db import get_connection, reconnect_if_needed, test_connection
from schemascribe.extractor import MetadataExtractor
from schemascribe.generator import DocGenerator
from schemascribe.models import PartitionGroup, SchemaInfo
from schemascribe.patterns import process_schema
from schemascribe.relationships import RelationshipInferrer

logger = logging.getLogger(__name__)


def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_checkpoint(path: Path, completed: List[str], failed: List[str]) -> None:
    path.write_text(
        json.dumps(
            {"timestamp": datetime.now().isoformat(), "completed": completed, "failed": failed},
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_failure_report(
    output_dir: Path, failed_schemas: List[str], failed_tables: Dict[str, List[str]]
) -> None:
    if not failed_schemas and not failed_tables:
        return
    lines = [
        "# SchemaScribe — Failure Report",
        f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
    ]
    if failed_schemas:
        lines.append(f"## Failed schemas ({len(failed_schemas)})\n")
        lines += [f"- `{s}`" for s in failed_schemas]
        lines.append("\nRe-run with `--resume` to retry only the failures.\n")
    if failed_tables:
        total = sum(len(v) for v in failed_tables.values())
        lines.append(f"## Failed tables ({total})\n")
        for schema, tables in failed_tables.items():
            lines.append(f"\n### `{schema}`")
            lines += [f"- `{t}`" for t in tables[:30]]
    (output_dir / "FAILURE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run(
    config: Config,
    output_dir: str | Path = "docs",
    *,
    resume: bool = False,
    only_schema: Optional[str] = None,
) -> int:
    """Generate documentation. Returns a process-style exit code (0 = success)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = output_dir / ".checkpoint.json"
    start = time.time()

    logger.info("=" * 64)
    logger.info("SchemaScribe — %s", "RESUME" if resume else "full run")
    logger.info("Output: %s", output_dir.resolve())
    logger.info("=" * 64)

    if not test_connection(config.database):
        logger.error("Cannot connect to the database. Check your PG* environment variables.")
        return 1

    checkpoint = _load_checkpoint(checkpoint_file) if resume else {}
    already_done = set(checkpoint.get("completed", []))
    if already_done:
        logger.info("Resuming — %d schema(s) already done.", len(already_done))

    completed: List[str] = list(already_done)
    failed_schemas: List[str] = []
    failed_tables: Dict[str, List[str]] = {}
    tables_documented = 0

    all_schema_infos: List[SchemaInfo] = []
    all_partition_groups: Dict[str, Dict[str, PartitionGroup]] = {}

    with get_connection(config.database) as conn:
        extractor = MetadataExtractor(conn)
        inferrer = RelationshipInferrer(config)
        generator = DocGenerator(config, inferrer, output_dir)

        schemas = [s for s in extractor.get_schemas() if s not in config.excluded_schemas]
        if only_schema:
            schemas = [s for s in schemas if s == only_schema]
            if not schemas:
                logger.error("Schema '%s' not found.", only_schema)
                return 1
        todo = [s for s in schemas if s not in already_done]
        logger.info("%d schema(s) total, %d to process.", len(schemas), len(todo))

        for idx, schema_name in enumerate(todo, 1):
            schema_start = time.time()
            try:
                conn = reconnect_if_needed(conn, config.database)
                extractor.conn = conn

                schema_info = extractor.extract_schema(schema_name)
                all_schema_infos.append(schema_info)
                inferrer.register_schema(schema_info)

                documentable, partition_groups = process_schema(schema_info, config)
                all_partition_groups[schema_name] = partition_groups

                for table in documentable:
                    inferrer.infer_for_table(table)

                generator.generate_schema(schema_info, documentable, partition_groups)

                schema_failures: List[str] = []
                for table in documentable:
                    pg = partition_groups.get(table.display_name)
                    try:
                        generator.generate_table(table, partition_group=pg)
                        tables_documented += 1
                    except Exception as exc:  # one bad table shouldn't kill the schema
                        schema_failures.append(table.table_name)
                        logger.debug("table doc failed for %s.%s: %s", schema_name, table.table_name, exc)
                if schema_failures:
                    failed_tables[schema_name] = schema_failures

                completed.append(schema_name)
                _save_checkpoint(checkpoint_file, completed, failed_schemas)
                logger.info(
                    "  ✓ [%d/%d] %s — %d docs, %d partition group(s) (%.1fs)",
                    idx, len(todo), schema_name, len(documentable),
                    len(partition_groups), time.time() - schema_start,
                )
            except Exception as exc:
                failed_schemas.append(schema_name)
                _save_checkpoint(checkpoint_file, completed, failed_schemas)
                logger.error("  ✗ [%d/%d] %s — FAILED: %s", idx, len(todo), schema_name, exc)
                logger.debug("traceback:\n%s", traceback.format_exc())

        logger.info("Generating database overview...")
        try:
            generator.generate_database_overview(all_schema_infos, all_partition_groups)
        except Exception as exc:
            logger.error("Could not generate database overview: %s", exc)

    _write_failure_report(output_dir, failed_schemas, failed_tables)
    if not failed_schemas and checkpoint_file.exists():
        checkpoint_file.unlink()

    elapsed = time.time() - start
    logger.info("=" * 64)
    logger.info("DONE in %.1fs (%.1f min)", elapsed, elapsed / 60)
    logger.info("  schemas: %d ok / %d failed", len(completed), len(failed_schemas))
    logger.info("  tables documented: %d", tables_documented)
    logger.info("  cross-schema links: %d", len(inferrer.cross_schema_links()))
    logger.info("  output: %s", output_dir.resolve())
    logger.info("=" * 64)

    return 2 if failed_schemas else 0
