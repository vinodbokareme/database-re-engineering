"""
Command-line interface for SchemaScribe.

    schemascribe --output docs
    schemascribe --config config.yaml --output docs
    schemascribe --schema public            # just one schema (great for testing)
    schemascribe --resume                    # retry after a partial failure
    schemascribe --test-connection           # verify credentials only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from schemascribe import __version__
from schemascribe.config import Config
from schemascribe.db import test_connection
from schemascribe.pipeline import run


def _setup_logging(output_dir: Path, verbose: bool) -> None:
    """Log clean progress to the console and full detail to a file."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    output_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(output_dir / "schemascribe.log", mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(ch)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schemascribe",
        description="Generate beautiful, AI-ready documentation for any PostgreSQL database.",
    )
    parser.add_argument("-o", "--output", default="docs", help="Output directory (default: docs)")
    parser.add_argument("-c", "--config", default=None, help="Path to a config.yaml (optional)")
    parser.add_argument("--schema", default=None, help="Only document this one schema")
    parser.add_argument("--resume", action="store_true", help="Skip schemas already completed")
    parser.add_argument(
        "--test-connection", action="store_true",
        help="Check database connectivity and exit",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose console output")
    parser.add_argument("--version", action="version", version=f"SchemaScribe {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Load a .env file if python-dotenv is installed (purely a convenience).
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except ImportError:
        pass

    output_dir = Path(args.output)
    _setup_logging(output_dir, args.verbose)

    try:
        config = Config.load(args.config) if args.config else Config.default()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.test_connection:
        ok = test_connection(config.database)
        print("✓ Connection OK" if ok else "✗ Connection failed (see log)")
        return 0 if ok else 1

    try:
        return run(config, output_dir, resume=args.resume, only_schema=args.schema)
    except (EnvironmentError, ConnectionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run with --resume to continue.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
