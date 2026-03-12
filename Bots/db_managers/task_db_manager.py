"""
Bots/db_managers/task_db_manager.py — Task Management Database Layer
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import logging

from .base_db import get_conn, db_queue, db_worker, db_execute  # noqa: F401

logger = logging.getLogger("Concord")

# ─── Schema Initialization ────────────────────────────────────────────────────

async def initialize_task_db():
    """Initializes the tasks database and required tables."""
    def _init():
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Create main tasks table
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id SERIAL PRIMARY KEY,
                        channel_id BIGINT UNIQUE,
                        assignees TEXT,
                        assignee_ids TEXT,
                        details TEXT,
                        deadline TEXT,
                        temp_channel_link TEXT,
                        assigner TEXT,
                        assigner_id BIGINT,
                        status TEXT,
                        title TEXT,
                        global_state TEXT DEFAULT 'Active',
                        completion_vector TEXT DEFAULT '',
                        activity_log TEXT DEFAULT '',
                        reminders_sent TEXT DEFAULT '',
                        main_message_id TEXT DEFAULT '',
                        priority TEXT DEFAULT 'Normal',
                        acknowledged_by TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                ''')
                # Create index on main_message_id for recovery
                cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_message_id ON tasks(main_message_id)')
                
                # Pending Tasks Channels (per-assignee view channel)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS pending_tasks_channels (
                        user_id         BIGINT PRIMARY KEY,
                        channel_id      BIGINT UNIQUE,
                        tasks           TEXT DEFAULT '',
                        task_message_ids TEXT DEFAULT ''
                    )
                ''')

                # Assigner Dashboard table
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS assigner_dashboard_channels (
                        user_id          BIGINT PRIMARY KEY,
                        channel_id       BIGINT UNIQUE,
                        tasks            TEXT DEFAULT '',
                        task_message_ids TEXT DEFAULT ''
                    )
                ''')

                # Notification Queue
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS notification_queue (
                        id SERIAL PRIMARY KEY,
                        task_id INTEGER,
                        recipient_id BIGINT,
                        content TEXT,
                        scheduled_at TIMESTAMP,
                        sent BOOLEAN DEFAULT FALSE
                    )
                ''')

                # Task Drafts table for reboot recovery
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS task_drafts (
                        draft_id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        modal_data JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            conn.commit()
    await db_execute(_init)

async def store_task_draft(user_id, modal_data):
    """Stores task details in a draft for reboot recovery."""
    import json
    def _store():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO task_drafts (user_id, modal_data)
                    VALUES (%s, %s)
                    RETURNING draft_id
                ''', (user_id, json.dumps(modal_data)))
                d_id = cur.fetchone()['draft_id']
                conn.commit()
                return d_id
    return await db_execute(_store)

async def retrieve_task_draft(draft_id):
    """Retrieves a task draft by its ID."""
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:  # connection already uses dict_row
                cur.execute('SELECT * FROM task_drafts WHERE draft_id = %s', (draft_id,))
                return cur.fetchone()
    return await db_execute(_retrieve)

async def delete_task_draft(draft_id):
    """Deletes a task draft."""
    def _delete():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM task_drafts WHERE draft_id = %s', (draft_id,))
            conn.commit()
    await db_execute(_delete)

# Legacy check function kept for compatibility
def check_and_create_database():
    # Note: This is now a wrapper around initialize_task_db
    pass

# ─── Core Database Methods ────────────────────────────────────────────────────

async def store_task_in_database(task_data):
    def _store():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO tasks (
                        channel_id, assignees, assignee_ids, details, deadline, 
                        temp_channel_link, assigner, assigner_id, status, title, 
                        global_state, completion_vector, activity_log, reminders_sent, 
                        main_message_id, priority, acknowledged_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING task_id
                ''', (
                    task_data['channel_id'], 
                    ', '.join(task_data['assignees']), 
                    ', '.join(map(str, task_data.get('assignee_ids', []))), 
                    task_data['details'], 
                    task_data['deadline'], 
                    task_data['temp_channel_link'], 
                    task_data['assigner'], 
                    task_data.get('assigner_id'), 
                    task_data['status'], 
                    task_data['title'], 
                    task_data.get('global_state', 'Active'), 
                    task_data.get('completion_vector', ''), 
                    task_data.get('activity_log', ''), 
                    task_data.get('reminders_sent', ''), 
                    task_data.get('main_message_id', ''), 
                    task_data.get('priority', 'Normal'), 
                    task_data.get('acknowledged_by', '')
                ))
                new_id = cur.fetchone()['task_id']
                conn.commit()
                return new_id
    return await db_execute(_store)

async def retrieve_task_from_database(channel_id):
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    SELECT 
                        assignees, assignee_ids, details, deadline, temp_channel_link, 
                        assigner, assigner_id, status, title, global_state, 
                        completion_vector, activity_log, reminders_sent, 
                        main_message_id, priority, acknowledged_by 
                    FROM tasks WHERE channel_id = %s
                ''', (channel_id,))
                row = cur.fetchone()
                if row:
                    return {
                        'channel_id': channel_id,
                        'assignees': row['assignees'].split(', ') if row['assignees'] else [],
                        'assignee_ids': [int(x) for x in row['assignee_ids'].split(', ') if x] if row['assignee_ids'] else [],
                        'details': row['details'],
                        'deadline': row['deadline'],
                        'temp_channel_link': row['temp_channel_link'],
                        'assigner': row['assigner'],
                        'assigner_id': row['assigner_id'],
                        'status': row['status'],
                        'title': row['title'],
                        'global_state': row['global_state'],
                        'completion_vector': row['completion_vector'],
                        'activity_log': row['activity_log'],
                        'reminders_sent': row['reminders_sent'],
                        'main_message_id': row['main_message_id'],
                        'priority': row['priority'],
                        'acknowledged_by': row['acknowledged_by']
                    }
                return None
    return await db_execute(_retrieve)

async def retrieve_task_by_id(task_id):
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM tasks WHERE task_id = %s', (task_id,))
                row = cur.fetchone()
                if row:
                    return {
                        'task_id': row['task_id'],
                        'channel_id': row['channel_id'],
                        'assignees': row['assignees'].split(', ') if row['assignees'] else [],
                        'assignee_ids': [int(x) for x in row['assignee_ids'].split(', ') if x] if row['assignee_ids'] else [],
                        'details': row['details'],
                        'deadline': row['deadline'],
                        'temp_channel_link': row['temp_channel_link'],
                        'assigner': row['assigner'],
                        'assigner_id': row['assigner_id'],
                        'status': row['status'],
                        'title': row['title'],
                        'global_state': row['global_state'],
                        'completion_vector': row['completion_vector'],
                        'activity_log': row['activity_log'],
                        'reminders_sent': row['reminders_sent'],
                        'main_message_id': row['main_message_id'],
                        'priority': row['priority'],
                        'acknowledged_by': row['acknowledged_by']
                    }
                return None
    return await db_execute(_retrieve)

async def retrieve_all_tasks_from_database():
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM tasks')
                rows = cur.fetchall()
                tasks = []
                for row in rows:
                    tasks.append({
                        'task_id': row['task_id'],
                        'channel_id': row['channel_id'],
                        'assignees': row['assignees'].split(', ') if row['assignees'] else [],
                        'assignee_ids': [int(x) for x in row['assignee_ids'].split(', ') if x] if row['assignee_ids'] else [],
                        'details': row['details'],
                        'deadline': row['deadline'],
                        'temp_channel_link': row['temp_channel_link'],
                        'assigner': row['assigner'],
                        'assigner_id': row['assigner_id'],
                        'status': row['status'],
                        'title': row['title'],
                        'global_state': row['global_state'],
                        'completion_vector': row['completion_vector'],
                        'activity_log': row['activity_log'],
                        'reminders_sent': row['reminders_sent'],
                        'main_message_id': row['main_message_id'],
                        'priority': row['priority'],
                        'acknowledged_by': row['acknowledged_by']
                    })
                return tasks
    return await db_execute(_retrieve)

async def update_task_in_database(task_data):
    def _update():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE tasks
                    SET assignees = %s, assignee_ids = %s, details = %s, deadline = %s, 
                        temp_channel_link = %s, assigner = %s, assigner_id = %s, 
                        status = %s, title = %s, global_state = %s, completion_vector = %s, 
                        activity_log = %s, reminders_sent = %s, main_message_id = %s, 
                        priority = %s, acknowledged_by = %s
                    WHERE task_id = %s
                ''', (
                    ', '.join(task_data['assignees']), 
                    ', '.join(map(str, task_data.get('assignee_ids', []))), 
                    task_data['details'], 
                    task_data['deadline'], 
                    task_data['temp_channel_link'], 
                    task_data['assigner'], 
                    task_data.get('assigner_id'), 
                    task_data['status'], 
                    task_data['title'], 
                    task_data.get('global_state', 'Active'), 
                    task_data.get('completion_vector', ''), 
                    task_data.get('activity_log', ''), 
                    task_data.get('reminders_sent', ''), 
                    task_data.get('main_message_id', ''), 
                    task_data.get('priority', 'Normal'), 
                    task_data.get('acknowledged_by', ''), 
                    task_data['task_id']
                ))
            conn.commit()
    await db_execute(_update)

async def delete_task_from_database(channel_id):
    def _delete():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM tasks WHERE channel_id = %s', (channel_id,))
            conn.commit()
    await db_execute(_delete)

async def store_pending_tasks_channel(user_id, channel_id, tasks=None, task_message_ids=None):
    def _store():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO pending_tasks_channels (user_id, channel_id, tasks, task_message_ids)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET 
                        channel_id = EXCLUDED.channel_id,
                        tasks = EXCLUDED.tasks,
                        task_message_ids = EXCLUDED.task_message_ids
                ''', (user_id, channel_id, ','.join(tasks) if tasks else '', ','.join(task_message_ids) if task_message_ids else ''))
            conn.commit()
    await db_execute(_store)

async def update_pending_tasks_channel(user_id, tasks, task_message_ids):
    def _update():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE pending_tasks_channels
                    SET tasks = %s, task_message_ids = %s
                    WHERE user_id = %s
                ''', (','.join(tasks), ','.join(task_message_ids), user_id))
            conn.commit()
    await db_execute(_update)

async def retrieve_pending_tasks_channel(user_id):
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT channel_id, tasks, task_message_ids FROM pending_tasks_channels WHERE user_id = %s', (user_id,))
                row = cur.fetchone()
                return row if row else None
    return await db_execute(_retrieve)

async def delete_pending_tasks_channel_from_database(user_id):
    def _delete():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM pending_tasks_channels WHERE user_id = %s', (user_id,))
            conn.commit()
    await db_execute(_delete)

# ─── Assigner Dashboard Methods ───────────────────────────────────────────────

async def store_assigner_dashboard_channel(user_id, channel_id, tasks=None, task_message_ids=None):
    def _store():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO assigner_dashboard_channels (user_id, channel_id, tasks, task_message_ids)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET 
                        channel_id = EXCLUDED.channel_id,
                        tasks = EXCLUDED.tasks,
                        task_message_ids = EXCLUDED.task_message_ids
                ''', (user_id, channel_id, ','.join(tasks) if tasks else '', ','.join(task_message_ids) if task_message_ids else ''))
            conn.commit()
    await db_execute(_store)

async def update_assigner_dashboard_channel(user_id, tasks, task_message_ids):
    def _update():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE assigner_dashboard_channels
                    SET tasks = %s, task_message_ids = %s
                    WHERE user_id = %s
                ''', (','.join(tasks), ','.join(task_message_ids), user_id))
            conn.commit()
    await db_execute(_update)

async def retrieve_assigner_dashboard_channel(user_id):
    def _retrieve():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT channel_id, tasks, task_message_ids FROM assigner_dashboard_channels WHERE user_id = %s', (user_id,))
                row = cur.fetchone()
                return row if row else None
    return await db_execute(_retrieve)

async def delete_assigner_dashboard_channel_from_database(user_id):
    def _delete():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM assigner_dashboard_channels WHERE user_id = %s', (user_id,))
            conn.commit()
    await db_execute(_delete)

async def mark_task_completed(task_id):
    """Sets the completed_at timestamp for the task."""
    def _mark():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    UPDATE tasks 
                    SET global_state = 'Finalized', 
                        status = 'Finalized',
                        completed_at = CURRENT_TIMESTAMP 
                    WHERE task_id = %s
                ''', (task_id,))
            conn.commit()
    await db_execute(_mark)
