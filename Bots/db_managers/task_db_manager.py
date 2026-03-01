import sqlite3
import os
import asyncio

# Define the network path to the NAS
nas_path = r'/home/am.k/Concord/Database'
db_path = os.path.join(nas_path, 'tasks.db')

# Function to check and create the database file
def check_and_create_database():
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                assignees TEXT,
                details TEXT,
                deadline TEXT,
                temp_channel_link TEXT,
                assigner TEXT,
                status TEXT,
                title TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_tasks_channels (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                tasks TEXT,
                task_message_ids TEXT
            )
        ''')
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the 'tasks' and 'task_message_ids' columns exist
        cursor.execute("PRAGMA table_info(pending_tasks_channels)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'tasks' not in columns:
            cursor.execute('''
                ALTER TABLE pending_tasks_channels ADD COLUMN tasks TEXT
            ''')
        if 'task_message_ids' not in columns:
            cursor.execute('''
                ALTER TABLE pending_tasks_channels ADD COLUMN task_message_ids TEXT
            ''')

        # Check if the 'title' column exists in the 'tasks' table
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'title' not in columns:
            cursor.execute('''
                ALTER TABLE tasks ADD COLUMN title TEXT
            ''')
        
        conn.commit()
        conn.close()

# Database functions
async def store_task_in_database(task_data):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _store_task_in_database_sync, task_data)

async def retrieve_task_from_database(channel_id):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _retrieve_task_from_database_sync, channel_id)

async def update_task_in_database(task_data):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _update_task_in_database_sync, task_data)

async def retrieve_all_tasks_from_database():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _retrieve_all_tasks_from_database_sync)

def _store_task_in_database_sync(task_data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            assignees TEXT,
            details TEXT,
            deadline TEXT,
            temp_channel_link TEXT,
            assigner TEXT,
            status TEXT,
            title TEXT
        )
    ''')
    cursor.execute('''
        INSERT INTO tasks (channel_id, assignees, details, deadline, temp_channel_link, assigner, status, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (task_data['channel_id'], ', '.join(task_data['assignees']), task_data['details'], task_data['deadline'], task_data['temp_channel_link'], task_data['assigner'], task_data['status'], task_data['title']))
    conn.commit()
    conn.close()

def _retrieve_task_from_database_sync(channel_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT assignees, details, deadline, temp_channel_link, assigner, status, title FROM tasks WHERE channel_id = ?', (channel_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'channel_id': channel_id,
            'assignees': row[0].split(', '),
            'details': row[1],
            'deadline': row[2],
            'temp_channel_link': row[3],
            'assigner': row[4],
            'status': row[5],
            'title': row[6]  # Ensure title is included
        }
    return None

def _retrieve_all_tasks_from_database_sync():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT task_id, channel_id, assignees, details, deadline, temp_channel_link, assigner, status, title FROM tasks')
    rows = cursor.fetchall()
    conn.close()
    tasks = []
    for row in rows:
        tasks.append({
            'task_id': row[0],
            'channel_id': row[1],
            'assignees': row[2].split(', '),
            'details': row[3],
            'deadline': row[4],
            'temp_channel_link': row[5],
            'assigner': row[6],
            'status': row[7],
            'title': row[8]  # Ensure title is included
        })
    return tasks

def _update_task_in_database_sync(task_data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tasks
        SET assignees = ?, details = ?, deadline = ?, temp_channel_link = ?, assigner = ?, status = ?, title = ?
        WHERE channel_id = ?
    ''', (', '.join(task_data['assignees']), task_data['details'], task_data['deadline'], task_data['temp_channel_link'], task_data['assigner'], task_data['status'], task_data['title'], task_data['channel_id']))
    conn.commit()
    conn.close()

def _delete_task_from_database_sync(channel_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tasks WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

def store_pending_tasks_channel(user_id, channel_id, tasks=None, task_message_ids=None):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO pending_tasks_channels (user_id, channel_id, tasks, task_message_ids)
        VALUES (?, ?, ?, ?)
    ''', (user_id, channel_id, ','.join(tasks) if tasks else '', ','.join(task_message_ids) if task_message_ids else ''))
    conn.commit()
    conn.close()

def update_pending_tasks_channel(user_id, tasks, task_message_ids):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE pending_tasks_channels
        SET tasks = ?, task_message_ids = ?
        WHERE user_id = ?
    ''', (','.join(tasks), ','.join(task_message_ids), user_id))
    conn.commit()
    conn.close()

def retrieve_pending_tasks_channel(user_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, tasks, task_message_ids FROM pending_tasks_channels WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1].split(',') if row[1] else [], row[2].split(',') if row[2] else []
    return None, [], []

def _delete_pending_tasks_channel_from_database(user_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM pending_tasks_channels WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
