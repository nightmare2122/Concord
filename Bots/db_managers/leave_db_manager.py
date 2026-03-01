import sqlite3
import os
import re
import asyncio

# Network path to the NAS server (or local database folder)
nas_server_path = "/home/am.k/Concord/Database"
db_leave_details_path = os.path.join(nas_server_path, 'leave_details.db')
db_dynamic_updates_path = os.path.join(nas_server_path, 'dynamic_updates.db')

def get_leave_conn():
    conn = sqlite3.connect(db_leave_details_path, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def get_dynamic_conn():
    conn = sqlite3.connect(db_dynamic_updates_path, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

# Database worker loop functions from original Leave.py
db_queue = asyncio.Queue()

async def db_worker():
    while True:
        func, args, kwargs, future = await db_queue.get()
        try:
            result = func(*args, **kwargs)
            future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
        db_queue.task_done()

async def db_execute(func, *args, **kwargs):
    future = asyncio.Future()
    await db_queue.put((func, args, kwargs, future))
    return await future

# Function to sanitize table names
def sanitize_table_name(name):
    return re.sub(r'\W+', '_', name)

# --- Core Database Methods ---

def _create_user_table_sync(nickname):
    table_name = sanitize_table_name(nickname)
    with get_leave_conn() as conn:
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
                leave_type TEXT,
                leave_reason TEXT,
                date_from TEXT,
                date_to TEXT,
                number_of_days_off REAL,
                resume_office_on TEXT,
                time_off TEXT,
                leave_status TEXT,
                reason_for_decline TEXT,
                approved_by TEXT,
                time_period TEXT,
                footer_text TEXT
            )
        ''')

def _delete_user_table_sync(nickname):
    table_name = sanitize_table_name(nickname)
    with get_leave_conn() as conn:
        conn.execute(f'DROP TABLE IF EXISTS {table_name}')

def _create_dynamic_table_sync():
    with get_dynamic_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS dynamic_updates (
                nickname TEXT,
                user_id INTEGER UNIQUE,
                total_sick_leave REAL DEFAULT 0,
                total_casual_leave REAL DEFAULT 0,
                total_c_off REAL DEFAULT 0,
                last_leave_taken TEXT,
                off_duty_hours REAL DEFAULT 0
            )
        ''')

# Async Database Function Wrappers
async def create_user_table(nickname):
    await db_execute(_create_user_table_sync, nickname)

async def delete_user_table(nickname):
    await db_execute(_delete_user_table_sync, nickname)

async def create_dynamic_table():
    await db_execute(_create_dynamic_table_sync)

async def insert_dynamic_user(nickname, user_id):
    def _insert():
        with get_dynamic_conn() as conn:
            conn.execute('''
                INSERT OR IGNORE INTO dynamic_updates (nickname, user_id)
                VALUES (?, ?)
            ''', (nickname, user_id))
    await db_execute(_insert)

async def remove_dynamic_user(user_id):
    def _delete():
        with get_dynamic_conn() as conn:
            conn.execute('DELETE FROM dynamic_updates WHERE user_id = ?', (user_id,))
    await db_execute(_delete)

async def fetch_dynamic_user(user_id):
    def _fetch():
        with get_dynamic_conn() as conn:
            return conn.execute('''
                SELECT last_leave_taken, total_casual_leave, total_sick_leave
                FROM dynamic_updates
                WHERE user_id = ?
            ''', (user_id,)).fetchone()
    return await db_execute(_fetch)

async def get_leave_status(nickname, leave_id):
    def _get():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            return conn.execute(f'''
                SELECT leave_reason, number_of_days_off FROM {table_name}
                WHERE leave_id = ? AND leave_status = 'Accepted'
            ''', (leave_id,)).fetchone()
    return await db_execute(_get)

async def check_leave_owner(nickname):
    def _check():
        with get_dynamic_conn() as conn:
            return conn.execute('''
                SELECT user_id FROM dynamic_updates WHERE nickname = ?
            ''', (nickname,)).fetchone()
    return await db_execute(_check)

async def withdraw_leave(nickname, leave_id):
    def _withdraw():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            conn.execute(f"UPDATE {table_name} SET leave_status = 'Withdrawn' WHERE leave_id = ?", (leave_id,))
    await db_execute(_withdraw)

async def reduce_leave_balance(user_id, leave_reason, amount):
    def _reduce():
        with get_dynamic_conn() as conn:
            if leave_reason == "sick":
                conn.execute("UPDATE dynamic_updates SET total_sick_leave = total_sick_leave - ? WHERE user_id = ?", (amount, user_id))
            elif leave_reason == "casual":
                conn.execute("UPDATE dynamic_updates SET total_casual_leave = total_casual_leave - ? WHERE user_id = ?", (amount, user_id))
            elif leave_reason == "c. off":
                conn.execute("UPDATE dynamic_updates SET total_c_off = total_c_off - ? WHERE user_id = ?", (amount, user_id))
    await db_execute(_reduce)

async def update_last_leave_date_after_withdrawal(nickname, user_id):
    def _update():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn1:
            latest_date = conn1.execute(f"SELECT MAX(date_to) FROM {table_name} WHERE leave_status = 'Accepted'").fetchone()[0]
            if latest_date:
                with get_dynamic_conn() as conn2:
                    conn2.execute("UPDATE dynamic_updates SET last_leave_taken = ? WHERE user_id = ?", (latest_date, user_id))
    await db_execute(_update)

async def update_footer_text(nickname, leave_id, footer_text):
    def _update():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            conn.execute(f"UPDATE {table_name} SET footer_text = ? WHERE leave_id = ?", (footer_text, leave_id))
    await db_execute(_update)

async def insert_full_leave(nickname, data):
    def _insert():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', data)
            return cursor.lastrowid
    return await db_execute(_insert)

async def insert_half_leave(nickname, data):
    def _insert():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, leave_status, reason_for_decline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', data)
            return cursor.lastrowid
    return await db_execute(_insert)

async def insert_off_duty(nickname, data, cumulated_hours, user_id):
    def _insert():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, time_off, leave_status, reason_for_decline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', data)
            leave_id = cursor.lastrowid
            
        with get_dynamic_conn() as dyn_conn:
            dyn_conn.execute("UPDATE dynamic_updates SET off_duty_hours = off_duty_hours + ? WHERE user_id = ?", (cumulated_hours, user_id))
            
        return leave_id
    return await db_execute(_insert)

async def update_approval(nickname, leave_id, approved_by):
    def _approve():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            conn.execute(f"UPDATE {table_name} SET approved_by = ? WHERE leave_id = ?", (approved_by, leave_id))
    await db_execute(_approve)

async def confirm_leave_acceptance(nickname, leave_id, leave_reason, number_of_days_off, date_to, user_id):
    def _accept():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            conn.execute(f"UPDATE {table_name} SET leave_status = 'Accepted' WHERE leave_id = ?", (leave_id,))
            
        with get_dynamic_conn() as dyn_conn:
            if leave_reason == "sick":
                dyn_conn.execute("UPDATE dynamic_updates SET total_sick_leave = total_sick_leave + ?, last_leave_taken = ? WHERE user_id = ?", (number_of_days_off, date_to, user_id))
            elif leave_reason == "casual":
                dyn_conn.execute("UPDATE dynamic_updates SET total_casual_leave = total_casual_leave + ?, last_leave_taken = ? WHERE user_id = ?", (number_of_days_off, date_to, user_id))
            elif leave_reason == "c. off":
                dyn_conn.execute("UPDATE dynamic_updates SET total_c_off = total_c_off + ?, last_leave_taken = ? WHERE user_id = ?", (number_of_days_off, date_to, user_id))
    await db_execute(_accept)

def get_all_tables_sync():
    with get_leave_conn() as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence';").fetchall()
        return [t[0] for t in tables]

def fetch_table_data_sync(table_name, start_of_month, end_of_month):
    query = f"""
        SELECT * FROM {table_name}
        WHERE (leave_status = 'Accepted' OR leave_status = 'Withdrawn')
        AND (date_from >= '{start_of_month}' AND (date_to <= '{end_of_month}' OR date_to IS NULL))
    """
    import pandas as pd
    with get_leave_conn() as conn:
        return pd.read_sql_query(query, conn)

async def get_footer_text(nickname, leave_id):
    def _fetch():
        table_name = sanitize_table_name(nickname)
        with get_leave_conn() as conn:
            return conn.execute(f"SELECT footer_text FROM {table_name} WHERE leave_id = ?", (leave_id,)).fetchone()
    return await db_execute(_fetch)

async def submit_leave_application(nickname, leave_details, data):
    """Unified entry point for all leave type submissions. Returns new leave_id."""
    def _insert():
        table_name = sanitize_table_name(nickname)
        leave_type = leave_details.get('leave_type', '')
        with get_leave_conn() as conn:
            cursor = conn.cursor()
            if leave_type == 'FULL DAY':
                cursor.execute(f'''
                    INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', data)
            elif leave_type == 'HALF DAY':
                cursor.execute(f'''
                    INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, leave_status, reason_for_decline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', data)
            elif leave_type == 'OFF DUTY':
                cursor.execute(f'''
                    INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, time_off, leave_status, reason_for_decline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', data)
            return cursor.lastrowid
    return await db_execute(_insert)

async def add_off_duty_hours(user_id, cumulated_hours):
    """Increments off_duty_hours for a user in the dynamic_updates table."""
    def _update():
        with get_dynamic_conn() as conn:
            conn.execute(
                "UPDATE dynamic_updates SET off_duty_hours = off_duty_hours + ? WHERE user_id = ?",
                (cumulated_hours, user_id)
            )
    await db_execute(_update)

async def get_all_tables():
    """Returns a list of (table_name,) tuples from the leave_details database."""
    def _fetch():
        with get_leave_conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence';"
            ).fetchall()
            return [(r[0],) for r in rows]
    return await db_execute(_fetch)

async def fetch_table_data(table_name, start_of_month, end_of_month):
    """Returns a pandas DataFrame of accepted/withdrawn leaves within the given date range."""
    def _fetch():
        import pandas as pd
        query = f"""
            SELECT * FROM {table_name}
            WHERE (leave_status = 'Accepted' OR leave_status = 'Withdrawn')
            AND (date_from >= '{start_of_month}' AND (date_to <= '{end_of_month}' OR date_to IS NULL))
        """
        with get_leave_conn() as conn:
            return pd.read_sql_query(query, conn)
    return await db_execute(_fetch)
