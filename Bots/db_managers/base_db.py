"""
Bots/db_managers/base_db.py — Shared Database Infrastructure
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.

Single source of truth for:
  - PostgreSQL connection pool (get_conn)
  - Async serial DB worker (db_worker / db_execute)

All domain db_manager modules import from here.
"""

import os
import asyncio
import logging
import atexit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from dotenv import load_dotenv

load_dotenv()

# ── PostgreSQL credentials ────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "concord_db")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

# Connection pool settings for 50+ users
POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN", "2"))
POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX", "20"))
POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "30.0"))

logger = logging.getLogger("Concord")

# ── Global Connection Pool ────────────────────────────────────────────────────
_pool: ConnectionPool | None = None


def init_pool():
    """Initialize the global connection pool."""
    global _pool
    if _pool is None:
        conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
        _pool = ConnectionPool(
            conninfo=conninfo,
            min_size=POOL_MIN_CONN,
            max_size=POOL_MAX_CONN,
            timeout=POOL_TIMEOUT,
            kwargs={"row_factory": dict_row},
        )
        logger.info(f"[DB] Connection pool initialized (min={POOL_MIN_CONN}, max={POOL_MAX_CONN})")


def close_pool():
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("[DB] Connection pool closed")


# Register cleanup on exit
atexit.register(close_pool)


def get_conn() -> psycopg.Connection:
    """Return a connection from the pool. Raises PoolTimeout with a clear message on exhaustion."""
    if _pool is None:
        init_pool()
    try:
        return _pool.getconn()  # type: ignore
    except PoolTimeout:
        logger.error(
            f"[ERR-DB-002] Connection pool exhausted after {POOL_TIMEOUT}s "
            f"(pool size: {POOL_MIN_CONN}–{POOL_MAX_CONN}). "
            "Consider increasing DB_POOL_MAX or reducing query frequency."
        )
        raise


def put_conn(conn: psycopg.Connection):
    """Return a connection to the pool."""
    if _pool is not None:
        _pool.putconn(conn)


# ── Async serial DB worker ────────────────────────────────────────────────────
# Each db_manager module that imports this module gets its own queue + worker
# instance so that they remain independently serialized.  Call db_worker() once
# as a background task (from cog_load) before calling db_execute().

db_queue: asyncio.Queue = asyncio.Queue()


async def db_worker() -> None:  # pragma: no cover — runs forever
    """Consume the db_queue and execute DB operations serially."""
    # Initialize pool on worker start
    init_pool()

    while True:
        try:
            func, args, kwargs, future = await db_queue.get()
        except asyncio.CancelledError:
            logger.info("[DB] db_worker cancelled — shutting down.")
            return

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            logger.exception(f"[ERR-DB-001] Database execution error in db_worker: {exc}")
            if not future.done():
                future.set_exception(exc)
        finally:
            db_queue.task_done()


async def db_execute(func, *args, **kwargs):
    """Schedule *func* on the serial DB worker and await its result."""
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    await db_queue.put((func, args, kwargs, future))
    return await future


# ── Synchronous helper for connection context ─────────────────────────────────

class ConnectionContext:
    """Context manager for database connections from the pool."""
    
    def __enter__(self):
        self.conn = get_conn()
        return self.conn
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            put_conn(self.conn)


def get_connection() -> ConnectionContext:
    """Get a connection context manager that returns conn to pool on exit."""
    return ConnectionContext()
