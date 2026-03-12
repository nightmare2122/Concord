"""
Bots/db_managers/discovery_db_manager.py — Guild Discovery Database Layer
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import logging
import json

from .base_db import get_conn, db_queue, db_worker, db_execute  # noqa: F401

logger = logging.getLogger("Concord")

# ─── Schema Initialization + Migration ─────────────────────────────────────────────────────

def _initialize_discovery_db_sync():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id   BIGINT PRIMARY KEY,
                    name TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id          BIGINT PRIMARY KEY,
                    name        TEXT,
                    type        TEXT,
                    category_id BIGINT,
                    CONSTRAINT fk_category FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS roles (
                    id       BIGINT PRIMARY KEY,
                    name     TEXT,
                    color    TEXT,
                    position INTEGER
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS members (
                    id           BIGINT PRIMARY KEY,
                    name         TEXT,
                    display_name TEXT,
                    joined_at    TEXT,
                    roles        JSONB DEFAULT '[]'::jsonb
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id         BIGINT PRIMARY KEY,
                    channel_id BIGINT,
                    author_id  BIGINT,
                    content    TEXT,
                    created_at TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_events (
                    id          BIGINT PRIMARY KEY,
                    name        TEXT,
                    description TEXT,
                    start_time  TEXT,
                    end_time    TEXT,
                    status      INTEGER
                )
            ''')
        conn.commit()

async def initialize_discovery_db():
    await db_execute(_initialize_discovery_db_sync)

# ─── Upsert Functions ─────────────────────────────────────────────────────────

def _upsert_category_sync(category_id, name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO categories (id, name) VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            ''', (category_id, name))
        conn.commit()

def _upsert_channel_sync(channel_id, name, channel_type, category_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO channels (id, name, type, category_id) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    name = EXCLUDED.name, 
                    type = EXCLUDED.type, 
                    category_id = EXCLUDED.category_id
            ''', (channel_id, name, channel_type, category_id))
        conn.commit()

def _upsert_role_sync(role_id, name, color, position):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO roles (id, name, color, position) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    name = EXCLUDED.name, 
                    color = EXCLUDED.color, 
                    position = EXCLUDED.position
            ''', (role_id, name, str(color), position))
        conn.commit()

def _upsert_member_sync(member_id, name, display_name, joined_at, roles=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if roles is not None:
                roles_json = json.dumps(roles, ensure_ascii=False)
                cur.execute('''
                    INSERT INTO members (id, name, display_name, joined_at, roles)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        name         = EXCLUDED.name,
                        display_name = EXCLUDED.display_name,
                        joined_at    = EXCLUDED.joined_at,
                        roles        = EXCLUDED.roles
                ''', (member_id, name, display_name, str(joined_at), roles_json))
            else:
                cur.execute('''
                    INSERT INTO members (id, name, display_name, joined_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        name         = EXCLUDED.name,
                        display_name = EXCLUDED.display_name,
                        joined_at    = EXCLUDED.joined_at
                ''', (member_id, name, display_name, str(joined_at)))
        conn.commit()

# ─── Delete Functions ─────────────────────────────────────────────────────────

def _delete_category_sync(category_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM categories WHERE id = %s', (category_id,))
        conn.commit()

def _delete_channel_sync(channel_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM channels WHERE id = %s', (channel_id,))
        conn.commit()

def _delete_role_sync(role_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM roles WHERE id = %s', (role_id,))
        conn.commit()

def _delete_member_sync(member_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM members WHERE id = %s', (member_id,))
        conn.commit()

def _upsert_message_sync(message_id, channel_id, author_id, content, created_at):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO messages (id, channel_id, author_id, content, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                    channel_id = EXCLUDED.channel_id,
                    author_id = EXCLUDED.author_id,
                    content = EXCLUDED.content,
                    created_at = EXCLUDED.created_at
            ''', (message_id, channel_id, author_id, content, str(created_at)))
        conn.commit()

def _delete_message_sync(message_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM messages WHERE id = %s', (message_id,))
        conn.commit()

def _upsert_scheduled_event_sync(event_id, name, description, start_time, end_time, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO scheduled_events (id, name, description, start_time, end_time, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    status = EXCLUDED.status
            ''', (event_id, name, description, str(start_time), str(end_time) if end_time else None, status))
        conn.commit()

def _delete_scheduled_event_sync(event_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM scheduled_events WHERE id = %s', (event_id,))
        conn.commit()

# ─── Async Wrappers ───────────────────────────────────────────────────────────

async def upsert_category(category_id, name):
    await db_execute(_upsert_category_sync, category_id, name)

async def upsert_channel(channel_id, name, channel_type, category_id):
    await db_execute(_upsert_channel_sync, channel_id, name, channel_type, category_id)

async def upsert_role(role_id, name, color, position):
    await db_execute(_upsert_role_sync, role_id, name, color, position)

async def upsert_member(member_id, name, display_name, joined_at, roles=None):
    await db_execute(_upsert_member_sync, member_id, name, display_name, joined_at, roles)

async def upsert_message(message_id, channel_id, author_id, content, created_at):
    await db_execute(_upsert_message_sync, message_id, channel_id, author_id, content, created_at)

async def upsert_scheduled_event(event_id, name, description, start_time, end_time, status):
    await db_execute(_upsert_scheduled_event_sync, event_id, name, description, start_time, end_time, status)

async def delete_category(category_id):
    await db_execute(_delete_category_sync, category_id)

async def delete_channel(channel_id):
    await db_execute(_delete_channel_sync, channel_id)

async def delete_role(role_id):
    await db_execute(_delete_role_sync, role_id)

async def delete_member(member_id):
    await db_execute(_delete_member_sync, member_id)

async def delete_message(message_id):
    await db_execute(_delete_message_sync, message_id)

async def delete_scheduled_event(event_id):
    await db_execute(_delete_scheduled_event_sync, event_id)

# ─── Query Functions ─────────────────────────────────────────────────────────

async def get_category_id_by_name(name):
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM categories WHERE name = %s', (name,))
                result = cur.fetchone()
                return result['id'] if result else None
    return await db_execute(_fetch)

async def get_channel_id_by_name(name):
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM channels WHERE name = %s', (name,))
                result = cur.fetchone()
                return result['id'] if result else None
    return await db_execute(_fetch)

async def get_role_id_by_name(name):
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM roles WHERE name = %s', (name,))
                result = cur.fetchone()
                return result['id'] if result else None
    return await db_execute(_fetch)

async def get_member_roles(member_id):
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT roles FROM members WHERE id = %s', (member_id,))
                result = cur.fetchone()
                if result and result['roles']:
                    return result['roles'] if isinstance(result['roles'], list) else json.loads(result['roles'])
                return []
    return await db_execute(_fetch)

async def member_has_role(member_id, role_name):
    roles = await get_member_roles(member_id)
    return role_name in roles

async def get_members_with_role(role_name):
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, display_name, roles FROM members WHERE roles ? %s",
                    (role_name,)
                )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
    return await db_execute(_fetch)

# ─── Convenience Status Helpers ───────────────────────────────────────────────

async def is_on_leave(member_id):
    return await member_has_role(member_id, 'On Leave')

async def has_submitted_dar(member_id):
    return await member_has_role(member_id, 'D.A.R Submitted')

async def get_members_on_leave():
    return await get_members_with_role('On Leave')

async def get_members_dar_pending():
    def _fetch():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, display_name FROM members WHERE NOT (roles ? 'D.A.R Submitted')")
                rows = cur.fetchall()
                return [dict(m) for m in rows]
    return await db_execute(_fetch)
