"""
Bots/db_managers/leave_db_manager.py — Leave Management Database Layer
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import re
import logging

from .base_db import get_conn, put_conn, get_connection, db_queue, db_worker, db_execute  # noqa: F401

logger = logging.getLogger("Concord")

# ─── Schema Initialization ────────────────────────────────────────────────────

async def initialize_leave_db():
    def _init():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        nickname TEXT,
                        total_sick_leave REAL DEFAULT 0,
                        total_casual_leave REAL DEFAULT 0,
                        total_c_off REAL DEFAULT 0,
                        last_leave_taken TEXT,
                        off_duty_hours REAL DEFAULT 0
                    )
                ''')
                
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS leaves (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
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
                        footer_text TEXT,
                        cancelled_by TEXT,
                        cancellation_reason TEXT
                    )
                ''')

                cur.execute('''
                    CREATE TABLE IF NOT EXISTS holidays (
                        date TEXT PRIMARY KEY,
                        description TEXT NOT NULL
                    )
                ''')
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_init)

# ─── Holiday Helpers ──────────────────────────────────────────────────────────

async def is_holiday(date_str):
    """Check if a date (DD-MM-YYYY) falls on a national holiday."""
    def _check():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM holidays WHERE date = %s", (date_str,))
                return cur.fetchone() is not None
        finally:
            put_conn(conn)
    return await db_execute(_check)

# ─── Core Database Methods ────────────────────────────────────────────────────

async def create_dynamic_table():
    await initialize_leave_db()

async def insert_dynamic_user(nickname, user_id):
    def _insert():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO users (user_id, nickname)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET nickname = EXCLUDED.nickname
                ''', (user_id, nickname))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_insert)

async def remove_dynamic_user(user_id):
    def _delete():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM users WHERE user_id = %s', (user_id,))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_delete)

async def fetch_dynamic_user(user_id):
    def _fetch():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT last_leave_taken, total_casual_leave, total_sick_leave, total_c_off, off_duty_hours
                    FROM users
                    WHERE user_id = %s
                ''', (user_id,))
                return cur.fetchone()
        finally:
            put_conn(conn)
    return await db_execute(_fetch)

async def get_leave_status(nickname, leave_id):
    def _get():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT leave_reason, number_of_days_off 
                    FROM leaves
                    WHERE id = %s AND leave_status = 'Accepted'
                ''', (leave_id,))
                result = cur.fetchone()
                return result if result else None
        finally:
            put_conn(conn)
    return await db_execute(_get)

async def get_leave_full_details(nickname, leave_id):
    def _get():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM leaves WHERE id = %s", (leave_id,))
                return cur.fetchone()
        finally:
            put_conn(conn)
    return await db_execute(_get)

async def get_pending_leave_status(nickname, leave_id):
    def _get():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT leave_reason, number_of_days_off 
                    FROM leaves
                    WHERE id = %s AND leave_status = 'PENDING'
                ''', (leave_id,))
                result = cur.fetchone()
                return result if result else None
        finally:
            put_conn(conn)
    return await db_execute(_get)

async def check_leave_owner(nickname):
    def _check():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT user_id FROM users WHERE nickname = %s', (nickname,))
                result = cur.fetchone()
                return result if result else None
        finally:
            put_conn(conn)
    return await db_execute(_check)

async def withdraw_leave(nickname, leave_id, cancelled_by=None, cancellation_reason=None):
    def _withdraw():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE leaves 
                    SET leave_status = 'Withdrawn', 
                        cancelled_by = COALESCE(%s, cancelled_by), 
                        cancellation_reason = COALESCE(%s, cancellation_reason) 
                    WHERE id = %s
                ''', (cancelled_by, cancellation_reason, leave_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_withdraw)

async def request_withdraw_leave(nickname, leave_id, requested_by=None, reason=None):
    def _request_withdraw():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE leaves 
                    SET leave_status = 'Withdrawal Requested', 
                        cancelled_by = COALESCE(%s, cancelled_by), 
                        cancellation_reason = COALESCE(%s, cancellation_reason) 
                    WHERE id = %s
                ''', (requested_by, reason, leave_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_request_withdraw)

async def confirm_withdraw_leave(nickname, leave_id):
    def _confirm_withdraw():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE leaves SET leave_status = 'Withdrawn by HR' WHERE id = %s", (leave_id,))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_confirm_withdraw)

async def revert_cancellation_request(nickname, leave_id):
    def _revert():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE leaves SET leave_status = 'Accepted' WHERE id = %s", (leave_id,))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_revert)

async def reduce_leave_balance(user_id, leave_reason, amount):
    def _reduce():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                if leave_reason == "sick":
                    cur.execute("UPDATE users SET total_sick_leave = total_sick_leave - %s WHERE user_id = %s", (amount, user_id))
                elif leave_reason == "casual":
                    cur.execute("UPDATE users SET total_casual_leave = total_casual_leave - %s WHERE user_id = %s", (amount, user_id))
                elif leave_reason == "c. off":
                    cur.execute("UPDATE users SET total_c_off = total_c_off - %s WHERE user_id = %s", (amount, user_id))
            conn.commit()
        finally:
            put_conn(conn)
    return await db_execute(_reduce)

async def refund_leave_balance(user_id, leave_reason, amount):
    def _refund():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                if leave_reason == "sick":
                    cur.execute("UPDATE users SET total_sick_leave = total_sick_leave + %s WHERE user_id = %s", (amount, user_id))
                elif leave_reason == "casual":
                    cur.execute("UPDATE users SET total_casual_leave = total_casual_leave + %s WHERE user_id = %s", (amount, user_id))
                elif leave_reason == "c. off":
                    cur.execute("UPDATE users SET total_c_off = total_c_off + %s WHERE user_id = %s", (amount, user_id))
            conn.commit()
        finally:
            put_conn(conn)
    return await db_execute(_refund)

async def update_last_leave_date_after_withdrawal(nickname, user_id):
    def _update():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date_to) FROM leaves WHERE user_id = %s AND leave_status = 'Accepted'", (user_id,))
                latest_date_row = cur.fetchone()
                latest_date = latest_date_row['max'] if latest_date_row else None
                if latest_date:
                    cur.execute("UPDATE users SET last_leave_taken = %s WHERE user_id = %s", (latest_date, user_id))
            conn.commit()
        finally:
            put_conn(conn)
    return await db_execute(_update)

async def update_footer_text(nickname, leave_id, footer_text):
    def _update():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE leaves SET footer_text = %s WHERE id = %s", (footer_text, leave_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_update)

async def submit_leave_application(nickname, leave_details, data, user_id=None):
    if user_id is None:
        owner = await check_leave_owner(nickname)
        if owner:
            user_id = owner['user_id']
        else:
            raise ValueError(f"User ID not provided and could not be resolved for {nickname}")

    def _insert():
        leave_type = leave_details.get('leave_type', '')
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                if leave_type == 'FULL DAY':
                    cur.execute('''
                        INSERT INTO leaves (user_id, leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (user_id, *data))
                elif leave_type == 'HALF DAY':
                    cur.execute('''
                        INSERT INTO leaves (user_id, leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, leave_status, reason_for_decline)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (user_id, *data))
                elif leave_type == 'OFF DUTY':
                    cur.execute('''
                        INSERT INTO leaves (user_id, leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_period, time_off, leave_status, reason_for_decline)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (user_id, *data))
                new_id = cur.fetchone()['id']
            conn.commit()
            return new_id
        finally:
            put_conn(conn)
    return await db_execute(_insert)

async def add_off_duty_hours(user_id, cumulated_hours):
    def _update():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET off_duty_hours = off_duty_hours + %s WHERE user_id = %s", (cumulated_hours, user_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_update)

async def confirm_leave_acceptance(nickname, leave_id, leave_reason, number_of_days_off, date_to, user_id):
    def _accept():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE leaves SET leave_status = 'Accepted' WHERE id = %s", (leave_id,))
                if leave_reason == "sick":
                    cur.execute("UPDATE users SET total_sick_leave = total_sick_leave + %s, last_leave_taken = %s WHERE user_id = %s", (number_of_days_off, date_to, user_id))
                elif leave_reason == "casual":
                    cur.execute("UPDATE users SET total_casual_leave = total_casual_leave + %s, last_leave_taken = %s WHERE user_id = %s", (number_of_days_off, date_to, user_id))
                elif leave_reason == "c. off":
                    cur.execute("UPDATE users SET total_c_off = total_c_off + %s, last_leave_taken = %s WHERE user_id = %s", (number_of_days_off, date_to, user_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_accept)

async def update_approval(nickname, leave_id, approved_by):
    def _approve():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE leaves SET approved_by = %s WHERE id = %s", (approved_by, leave_id))
            conn.commit()
        finally:
            put_conn(conn)
    await db_execute(_approve)

async def get_footer_text(nickname, leave_id):
    def _fetch():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT footer_text FROM leaves WHERE id = %s", (leave_id,))
                result = cur.fetchone()
                return result if result else None
        finally:
            put_conn(conn)
    return await db_execute(_fetch)

# ─── Data Export Helpers ──────────────────────────────────────────────────────

async def get_all_users():
    def _fetch():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT nickname FROM users")
                return [r['nickname'] for r in cur.fetchall()]
        finally:
            put_conn(conn)
    return await db_execute(_fetch)

async def fetch_user_leave_data(nickname, start_of_month, end_of_month):
    """
    Returns a list of dicts for accepted/withdrawn leave records in the given date range.
    start_of_month / end_of_month: Python date objects or ISO strings (YYYY-MM-DD).
    Dates stored in the DB as DD-MM-YYYY text — TO_DATE() handles the conversion.
    """
    def _fetch():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT l.* FROM leaves l
                    JOIN users u ON l.user_id = u.user_id
                    WHERE u.nickname = %s
                      AND l.leave_status IN ('Accepted', 'Withdrawn')
                      AND TO_DATE(l.date_from, 'DD-MM-YYYY') >= %s
                      AND (
                          l.date_to IS NULL
                          OR TO_DATE(l.date_to, 'DD-MM-YYYY') <= %s
                      )
                    ORDER BY TO_DATE(l.date_from, 'DD-MM-YYYY')
                """, (nickname, start_of_month, end_of_month))
                return [dict(row) for row in cur.fetchall()]
        finally:
            put_conn(conn)
    return await db_execute(_fetch)
