"""
Database connection management.

SchemaScribe only ever *reads* your database, so the connection is opened in
read-only mode with a statement timeout. Connections are retried with
exponential backoff because metadata runs often target large, busy production
replicas where the occasional blip is normal.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

from schemascribe.config import DatabaseConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [2, 5, 15]  # one entry per retry attempt


def _create_connection(cfg: DatabaseConfig):
    """Open a single read-only connection. Caller owns closing it."""
    conn = psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.database,
        user=cfg.user,
        password=cfg.password,
        cursor_factory=RealDictCursor,
        options=f"-c statement_timeout={cfg.statement_timeout_ms}",
        connect_timeout=cfg.connect_timeout,
        sslmode=cfg.sslmode,
    )
    # readonly + autocommit: we never write, and we don't want long-lived
    # transactions holding back vacuum on the server we're inspecting.
    conn.set_session(readonly=True, autocommit=True)
    return conn


@contextmanager
def get_connection(cfg: DatabaseConfig) -> Iterator["psycopg2.extensions.connection"]:
    """Yield a read-only connection, retrying on transient failures.

    Raises ``EnvironmentError`` if required credentials are missing and
    ``ConnectionError`` if every retry is exhausted. The connection is always
    closed on exit.
    """
    missing = cfg.missing_fields()
    if missing:
        raise EnvironmentError(
            "Missing required database settings: "
            + ", ".join(missing)
            + ". Set them as environment variables (e.g. export PGDATABASE=...)."
        )

    conn = None
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Connecting to %s:%s/%s (attempt %d/%d)",
                cfg.host, cfg.port, cfg.database, attempt, MAX_RETRIES,
            )
            conn = _create_connection(cfg)
            logger.info("Connected (read-only).")
            break
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS[attempt - 1]
                logger.warning("Connect failed: %s. Retrying in %ds...", exc, wait)
                time.sleep(wait)
            else:
                logger.error("All %d connection attempts failed.", MAX_RETRIES)

    if conn is None:
        raise ConnectionError(f"Could not connect after {MAX_RETRIES} attempts: {last_error}")

    try:
        yield conn
    finally:
        if conn and not conn.closed:
            conn.close()
            logger.info("Connection closed.")


def is_healthy(conn) -> bool:
    """Return True if a simple round-trip query succeeds on ``conn``."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception:
        return False


def reconnect_if_needed(conn, cfg: DatabaseConfig):
    """Return a live connection — the same one if healthy, or a fresh one.

    Long extraction runs can outlive a server-side idle timeout; this keeps the
    pipeline moving without restarting from scratch.
    """
    if is_healthy(conn):
        return conn

    logger.warning("Connection lost — reconnecting...")
    try:
        if not conn.closed:
            conn.close()
    except Exception:
        pass

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            new_conn = _create_connection(cfg)
            logger.info("Reconnected (attempt %d).", attempt)
            return new_conn
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    raise ConnectionError(f"Reconnect failed after {MAX_RETRIES} attempts: {last_error}")


def test_connection(cfg: DatabaseConfig) -> bool:
    """Quick connectivity probe used before a full run. Never raises."""
    try:
        with get_connection(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                return cur.fetchone()["ok"] == 1
    except Exception as exc:
        logger.error("Connection test failed: %s", exc)
        return False
