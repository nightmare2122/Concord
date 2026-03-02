import sqlite3
import os
import asyncio
import logging
import json

# Path to the Database folder
db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'Database'))
os.makedirs(db_path, exist_ok=True)
db_discovery_path = os.path.join(db_path, 'discovery.db')

logger = logging.getLogger("Concord")

def get_discovery_conn():
    conn = sqlite3.connect(db_discovery_path, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

# ─── Database Worker ───────────────────────────────────────────────────────────

db_queue = asyncio.Queue()

async def db_worker():
    while True:
        func, args, kwargs, future = await db_queue.get()
        try:
            result = func(*args, **kwargs)
            if not future.done():
                future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
        db_queue.task_done()

async def db_execute(func, *args, **kwargs):
    future = asyncio.Future()
    await db_queue.put((func, args, kwargs, future))
    return await future

# ─── Schema Initialization + Migration ────────────────────────────────────────

def _initialize_discovery_db_sync():
    with get_discovery_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                type        TEXT,
                category_id INTEGER,
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                id       INTEGER PRIMARY KEY,
                name     TEXT,
                color    TEXT,
                position INTEGER
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id           INTEGER PRIMARY KEY,
                name         TEXT,
                display_name TEXT,
                joined_at    TEXT,
                roles        TEXT DEFAULT '[]'
            )
        ''')

        # Migration: add roles column if the members table already exists without it
        try:
            conn.execute("ALTER TABLE members ADD COLUMN roles TEXT DEFAULT '[]'")
            logger.info("[Discovery] Migrated members table: added 'roles' column.")
        except sqlite3.OperationalError:
            pass  # Column already exists — no action needed

        # Remove the old member_roles junction table if it lingered from a previous version
        conn.execute('DROP TABLE IF EXISTS member_roles')

# ─── Upsert Sync Functions ────────────────────────────────────────────────────

def _upsert_category_sync(category_id, name):
    with get_discovery_conn() as conn:
        conn.execute('INSERT OR REPLACE INTO categories (id, name) VALUES (?, ?)', (category_id, name))

def _upsert_channel_sync(channel_id, name, channel_type, category_id):
    with get_discovery_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO channels (id, name, type, category_id) VALUES (?, ?, ?, ?)',
            (channel_id, name, channel_type, category_id)
        )

def _upsert_role_sync(role_id, name, color, position):
    with get_discovery_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO roles (id, name, color, position) VALUES (?, ?, ?, ?)',
            (role_id, name, str(color), position)
        )

def _upsert_member_sync(member_id, name, display_name, joined_at, roles=None):
    """
    Upserts a member record.
    roles: list of role name strings. If None, the existing roles column is preserved.
    """
    with get_discovery_conn() as conn:
        if roles is not None:
            roles_json = json.dumps(roles, ensure_ascii=False)
            conn.execute(
                '''INSERT INTO members (id, name, display_name, joined_at, roles)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name         = excluded.name,
                       display_name = excluded.display_name,
                       joined_at    = excluded.joined_at,
                       roles        = excluded.roles''',
                (member_id, name, display_name, str(joined_at), roles_json)
            )
        else:
            conn.execute(
                '''INSERT INTO members (id, name, display_name, joined_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name         = excluded.name,
                       display_name = excluded.display_name,
                       joined_at    = excluded.joined_at''',
                (member_id, name, display_name, str(joined_at))
            )

# ─── Delete Sync Functions ────────────────────────────────────────────────────

def _delete_category_sync(category_id):
    with get_discovery_conn() as conn:
        conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))

def _delete_channel_sync(channel_id):
    with get_discovery_conn() as conn:
        conn.execute('DELETE FROM channels WHERE id = ?', (channel_id,))

def _delete_role_sync(role_id):
    with get_discovery_conn() as conn:
        conn.execute('DELETE FROM roles WHERE id = ?', (role_id,))

def _delete_member_sync(member_id):
    with get_discovery_conn() as conn:
        conn.execute('DELETE FROM members WHERE id = ?', (member_id,))

# ─── Async Wrappers ───────────────────────────────────────────────────────────

async def initialize_discovery_db():
    await db_execute(_initialize_discovery_db_sync)

async def upsert_category(category_id, name):
    await db_execute(_upsert_category_sync, category_id, name)

async def upsert_channel(channel_id, name, channel_type, category_id):
    await db_execute(_upsert_channel_sync, channel_id, name, channel_type, category_id)

async def upsert_role(role_id, name, color, position):
    await db_execute(_upsert_role_sync, role_id, name, color, position)

async def upsert_member(member_id, name, display_name, joined_at, roles=None):
    """roles: optional list of role name strings to store on the member row."""
    await db_execute(_upsert_member_sync, member_id, name, display_name, joined_at, roles)

async def delete_category(category_id):
    await db_execute(_delete_category_sync, category_id)

async def delete_channel(channel_id):
    await db_execute(_delete_channel_sync, channel_id)

async def delete_role(role_id):
    await db_execute(_delete_role_sync, role_id)

async def delete_member(member_id):
    await db_execute(_delete_member_sync, member_id)

# ─── Query Functions (synchronous) ───────────────────────────────────────────

def get_channel_id_by_name(name):
    """Return the Discord ID of a channel by its name, or None."""
    with get_discovery_conn() as conn:
        result = conn.execute('SELECT id FROM channels WHERE name = ?', (name,)).fetchone()
        return result['id'] if result else None

def get_role_id_by_name(name):
    """Return the Discord ID of a role by its name, or None."""
    with get_discovery_conn() as conn:
        result = conn.execute('SELECT id FROM roles WHERE name = ?', (name,)).fetchone()
        return result['id'] if result else None

def get_member_roles(member_id):
    """Return list of role name strings for a member."""
    with get_discovery_conn() as conn:
        result = conn.execute('SELECT roles FROM members WHERE id = ?', (member_id,)).fetchone()
        if result and result['roles']:
            return json.loads(result['roles'])
        return []

def member_has_role(member_id, role_name):
    """Return True if the member currently holds the given role (by name)."""
    return role_name in get_member_roles(member_id)

def get_members_with_role(role_name):
    """Return list of member dicts [{id, name, display_name, roles}] who hold a given role."""
    with get_discovery_conn() as conn:
        # JSON search via LIKE — works for exact role names
        rows = conn.execute(
            "SELECT id, name, display_name, roles FROM members WHERE roles LIKE ?",
            (f'%"{role_name}"%',)
        ).fetchall()
        return [dict(r) for r in rows]

# ─── Convenience Status Helpers ───────────────────────────────────────────────

def is_on_leave(member_id):
    """True if the member currently has the 'On Leave' role."""
    return member_has_role(member_id, 'On Leave')

def has_submitted_dar(member_id):
    """True if the member currently has the 'D.A.R Submitted' role."""
    return member_has_role(member_id, 'D.A.R Submitted')

def get_members_on_leave():
    """Return all members currently marked On Leave."""
    return get_members_with_role('On Leave')

def get_members_dar_pending():
    """Return all members who have NOT yet submitted their DAR today."""
    submitted = {m['id'] for m in get_members_with_role('D.A.R Submitted')}
    with get_discovery_conn() as conn:
        all_members = conn.execute('SELECT id, name, display_name FROM members').fetchall()
        return [dict(m) for m in all_members if m['id'] not in submitted]
