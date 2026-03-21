"""
tests/test_db.py
Task database manager unit tests mocking psycopg connection.
"""

import pytest
import sys
import os
import asyncio
import inspect
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from Bots.db_managers import task_db_manager as db_manager

# Make the queue worker run inline for easier testing
async def mock_db_execute(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)

@pytest.fixture(autouse=True)
def patch_db_execute():
    with patch('Bots.db_managers.task_db_manager.db_execute', side_effect=mock_db_execute):
        yield

@pytest.fixture
def mock_conn():
    with patch('Bots.db_managers.task_db_manager.get_conn') as get_conn_mock, \
         patch('Bots.db_managers.task_db_manager.put_conn'):
        conn = MagicMock()
        get_conn_mock.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn, cur

def make_db_row(**overrides):
    base = {
        'task_id': 1,
        'channel_id': '12345',
        'assignees': 'UserA, UserB',
        'assignee_ids': '1, 2',
        'details': 'Fix the bug',
        'deadline': '01/01/2026 12:00 PM',
        'temp_channel_link': 'http://discord.com/channels/1/2',
        'assigner': 'Boss',
        'assigner_id': 999,
        'status': 'Pending',
        'title': 'Bug Fix',
        'global_state': 'Active',
        'completion_vector': '0,0',
        'activity_log': '',
        'reminders_sent': '',
        'main_message_id': '5678',
        'priority': 'Normal',
        'acknowledged_by': '',
        'blocker_reason': '',
        'completed_at': None,
        'checklist': '',
        'created_at': None
    }
    base.update(overrides)
    return base

# ─── Store & Retrieve ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_and_retrieve_task(mock_conn):
    conn, cur = mock_conn
    task = make_db_row()
    task['assignees'] = ['UserA', 'UserB'] # Store gets Python object
    
    # Mock INSERT fetchone returning the new ID
    cur.fetchone.return_value = {'task_id': 1}
    
    new_id = await db_manager.store_task_in_database(task)
    assert new_id == 1
    cur.execute.assert_called()

@pytest.mark.asyncio
async def test_retrieve_task(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = make_db_row(title='Retrieved', channel_id='999')
    
    res = await db_manager.retrieve_task_from_database(999)
    assert res['title'] == 'Retrieved'
    cur.execute.assert_called()

@pytest.mark.asyncio
async def test_retrieve_all_tasks(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [make_db_row(title='Task A'), make_db_row(title='Task B')]
    
    res = await db_manager.retrieve_all_tasks_from_database()
    assert len(res) == 2
    assert res[1]['title'] == 'Task B'

# ─── Update & Delete ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_task(mock_conn):
    conn, cur = mock_conn
    task = make_db_row(task_id=1, status='Completed')
    task['assignees'] = ['UserA', 'UserB']
    
    await db_manager.update_task_in_database(task)
    cur.execute.assert_called()
    conn.commit.assert_called()

@pytest.mark.asyncio
async def test_delete_task(mock_conn):
    conn, cur = mock_conn
    await db_manager.delete_task_from_database(555)
    cur.execute.assert_called_with('DELETE FROM tasks WHERE channel_id = %s', (555,))
    conn.commit.assert_called()

# ─── Channels ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_tasks_channel(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = {'channel_id': '888', 'tasks': '1,2', 'task_message_ids': '3,4'}
    
    res = await db_manager.retrieve_pending_tasks_channel(123)
    assert res['channel_id'] == '888'

@pytest.mark.asyncio
async def test_store_pending_tasks_channel(mock_conn):
    conn, cur = mock_conn
    await db_manager.store_pending_tasks_channel(123, 456)
    cur.execute.assert_called()
    conn.commit.assert_called()
