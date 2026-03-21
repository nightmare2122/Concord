import sqlite3
import psycopg
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Migration")

import sys
# Add project root to sys.path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# SQLite Paths - resolved relative to project root
sqlite_db_dir = os.path.join(PROJECT_ROOT, 'Database')
db_discovery_path = os.path.join(sqlite_db_dir, 'discovery.db')
db_leave_details_path = os.path.join(sqlite_db_dir, 'leave_details.db')
db_dynamic_updates_path = os.path.join(sqlite_db_dir, 'dynamic_updates.db')
db_tasks_path = os.path.join(sqlite_db_dir, 'tasks.db')

# PostgreSQL Credentials
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "concord_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

def get_pg_conn():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def migrate_discovery():
    if not os.path.exists(db_discovery_path):
        logger.warning(f"Discovery DB not found at {db_discovery_path}")
        return

    logger.info("Migrating Discovery DB...")
    lite_conn = sqlite3.connect(db_discovery_path)
    lite_conn.row_factory = sqlite3.Row
    pg_conn = get_pg_conn()
    
    with pg_conn.cursor() as cur:
        # Categories
        rows = lite_conn.execute("SELECT * FROM categories").fetchall()
        for r in rows:
            cur.execute("INSERT INTO categories (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (r['id'], r['name']))
        
        # Channels
        rows = lite_conn.execute("SELECT * FROM channels").fetchall()
        for r in rows:
            cur.execute("INSERT INTO channels (id, name, type, category_id) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (r['id'], r['name'], r['type'], r['category_id']))
        
        # Roles
        rows = lite_conn.execute("SELECT * FROM roles").fetchall()
        for r in rows:
            cur.execute("INSERT INTO roles (id, name, color, position) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (r['id'], r['name'], r['color'], r['position']))
            
        # Members
        rows = lite_conn.execute("SELECT * FROM members").fetchall()
        for r in rows:
            roles = r['roles'] if r['roles'] else '[]'
            cur.execute("INSERT INTO members (id, name, display_name, joined_at, roles) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", 
                        (r['id'], r['name'], r['display_name'], r['joined_at'], roles))
        
        # Messages
        rows = lite_conn.execute("SELECT * FROM messages").fetchall()
        for r in rows:
            cur.execute("INSERT INTO messages (id, channel_id, author_id, content, created_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", 
                        (r['id'], r['channel_id'], r['author_id'], r['content'], r['created_at']))
        
        # Scheduled Events
        rows = lite_conn.execute("SELECT * FROM scheduled_events").fetchall()
        for r in rows:
            cur.execute("INSERT INTO scheduled_events (id, name, description, start_time, end_time, status) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", 
                        (r['id'], r['name'], r['description'], r['start_time'], r['end_time'], r['status']))

    pg_conn.commit()
    pg_conn.close()
    lite_conn.close()
    logger.info("Discovery DB migration complete.")

def migrate_leaves():
    if not os.path.exists(db_dynamic_updates_path):
        logger.warning(f"Dynamic Updates DB not found at {db_dynamic_updates_path}")
    else:
        logger.info("Migrating Users/Balances...")
        lite_conn = sqlite3.connect(db_dynamic_updates_path)
        lite_conn.row_factory = sqlite3.Row
        pg_conn = get_pg_conn()
        with pg_conn.cursor() as cur:
            rows = lite_conn.execute("SELECT * FROM dynamic_updates").fetchall()
            for r in rows:
                cur.execute('''
                    INSERT INTO users (user_id, nickname, total_sick_leave, total_casual_leave, total_c_off, last_leave_taken, off_duty_hours)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET nickname = EXCLUDED.nickname
                ''', (r['user_id'], r['nickname'], r['total_sick_leave'], r['total_casual_leave'], r['total_c_off'], r['last_leave_taken'], r['off_duty_hours']))
        pg_conn.commit()
        pg_conn.close()
        lite_conn.close()

    if not os.path.exists(db_leave_details_path):
        logger.warning(f"Leave Details DB not found at {db_leave_details_path}")
        return

    logger.info("Migrating Leaves (per-user tables)...")
    lite_conn = sqlite3.connect(db_leave_details_path)
    lite_conn.row_factory = sqlite3.Row
    pg_conn = get_pg_conn()
    
    # Get all tables
    tables = lite_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'").fetchall()
    
    with pg_conn.cursor() as cur:
        for table_row in tables:
            table_name = table_row['name']
            # Resolve user_id for this nickname
            cur.execute("SELECT user_id FROM users WHERE nickname = %s", (table_name,))
            user_row = cur.fetchone()
            if not user_row:
                logger.warning(f"Could not find user_id for table {table_name}, skipping.")
                continue
            
            user_id = user_row[0]
            
            # Fetch data from SQLite
            cursor = lite_conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [c[1] for c in cursor.fetchall()]
            
            rows = lite_conn.execute(f"SELECT * FROM {table_name}").fetchall()
            for r in rows:
                # Column mapping logic
                data = {
                    'user_id': user_id,
                    'leave_type': r['leave_type'],
                    'leave_reason': r['leave_reason'],
                    'date_from': r['date_from'],
                    'date_to': r['date_to'],
                    'number_of_days_off': r['number_of_days_off'],
                    'resume_office_on': r['resume_office_on'],
                    'time_off': r['time_off'] if 'time_off' in columns else None,
                    'leave_status': r['leave_status'],
                    'reason_for_decline': r['reason_for_decline'],
                    'approved_by': r['approved_by'] if 'approved_by' in columns else None,
                    'time_period': r['time_period'] if 'time_period' in columns else None,
                    'footer_text': r['footer_text'] if 'footer_text' in columns else None,
                    'cancelled_by': r['cancelled_by'] if 'cancelled_by' in columns else None,
                    'cancellation_reason': r['cancellation_reason'] if 'cancellation_reason' in columns else None
                }
                
                cur.execute('''
                    INSERT INTO leaves (
                        user_id, leave_type, leave_reason, date_from, date_to, 
                        number_of_days_off, resume_office_on, time_off, leave_status, 
                        reason_for_decline, approved_by, time_period, footer_text, 
                        cancelled_by, cancellation_reason
                    ) VALUES (
                        %(user_id)s, %(leave_type)s, %(leave_reason)s, %(date_from)s, %(date_to)s, 
                        %(number_of_days_off)s, %(resume_office_on)s, %(time_off)s, %(leave_status)s, 
                        %(reason_for_decline)s, %(approved_by)s, %(time_period)s, %(footer_text)s, 
                        %(cancelled_by)s, %(cancellation_reason)s
                    )
                ''', data)

    pg_conn.commit()
    pg_conn.close()
    lite_conn.close()
    logger.info("Leave migration complete.")

def migrate_tasks():
    if not os.path.exists(db_tasks_path):
        logger.warning(f"Tasks DB not found at {db_tasks_path}")
        return

    logger.info("Migrating Tasks...")
    lite_conn = sqlite3.connect(db_tasks_path)
    lite_conn.row_factory = sqlite3.Row
    pg_conn = get_pg_conn()
    
    with pg_conn.cursor() as cur:
        # Tasks table
        rows = lite_conn.execute("SELECT * FROM tasks").fetchall()
        for r in rows:
            cur.execute('''
                INSERT INTO tasks (
                    channel_id, assignees, assignee_ids, details, deadline, 
                    temp_channel_link, assigner, assigner_id, status, title, 
                    global_state, completion_vector, activity_log, reminders_sent, 
                    main_message_id, priority, acknowledged_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                r['channel_id'], r['assignees'], r['assignee_ids'], r['details'], r['deadline'],
                r['temp_channel_link'], r['assigner'], r['assigner_id'], r['status'], r['title'],
                r['global_state'], r['completion_vector'], r['activity_log'], r['reminders_sent'],
                r['main_message_id'], r['priority'], r['acknowledged_by']
            ))
        
        # Pending Tasks Channels
        rows = lite_conn.execute("SELECT * FROM pending_tasks_channels").fetchall()
        for r in rows:
            cur.execute('''
                INSERT INTO pending_tasks_channels (user_id, channel_id, tasks, task_message_ids)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (r['user_id'], r['channel_id'], r['tasks'], r['task_message_ids']))

    pg_conn.commit()
    pg_conn.close()
    lite_conn.close()
    logger.info("Tasks migration complete.")

if __name__ == "__main__":
    import asyncio
    from Bots.db_managers import discovery_db_manager, leave_db_manager, task_db_manager
    
    async def run_init():
        logger.info("Initializing PostgreSQL Schema...")
        
        # Start background workers for each manager
        workers = [
            asyncio.create_task(discovery_db_manager.db_worker()),
            asyncio.create_task(leave_db_manager.db_worker()),
            asyncio.create_task(task_db_manager.db_worker())
        ]
        
        try:
            await discovery_db_manager.initialize_discovery_db()
            await leave_db_manager.initialize_leave_db()
            await task_db_manager.initialize_task_db()
        finally:
            # Shutdown the workers
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
    
    asyncio.run(run_init())
    
    migrate_discovery()
    migrate_leaves()
    migrate_tasks()
    logger.info("All migrations completed successfully.")
