"""
Bots/db_managers/base_db.py — Shared Database Infrastructure
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.

Single source of truth for:
  - PostgreSQL connection factory (get_conn)
  - Async serial DB worker (db_worker / db_execute)

All domain db_manager modules import from here.
"""

import os
import asyncio
import logging

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# ── PostgreSQL credentials ────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "concord_db")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

logger = logging.getLogger("Concord")


def get_conn() -> psycopg.Connection:
    """Return a new synchronous psycopg connection with dict_row factory."""
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        row_factory=dict_row,
    )


# ── Async serial DB worker ────────────────────────────────────────────────────
# Each db_manager module that imports this module gets its own queue + worker
# instance so that they remain independently serialized.  Call db_worker() once
# as a background task (from cog_load) before calling db_execute().

db_queue: asyncio.Queue = asyncio.Queue()


async def db_worker() -> None:  # pragma: no cover — runs forever
    """Consume the db_queue and execute DB operations serially."""
    while True:
        func, args, kwargs, future = await db_queue.get()
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
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    await db_queue.put((func, args, kwargs, future))
    return await future
