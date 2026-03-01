"""
tests/test_db.py
Task database manager unit tests using a temporary SQLite file.
"""

import pytest
import sqlite3
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Bots'))
from db_managers import task_db_manager as db_manager
from db_managers.task_db_manager import (
    _store_task_in_database_sync,
    _retrieve_task_from_database_sync,
    _update_task_in_database_sync,
    _delete_task_from_database_sync,
    _retrieve_all_tasks_from_database_sync,
    check_and_create_database,
    store_pending_tasks_channel,
    retrieve_pending_tasks_channel,
    update_pending_tasks_channel,
    _delete_pending_tasks_channel_from_database,
)


@pytest.fixture
def mock_db_path(monkeypatch, tmp_path):
    """Route both DB paths to temporary files for each test."""
    temp_db = tmp_path / "test_tasks.db"
    monkeypatch.setattr(db_manager, "db_path", str(temp_db))
    check_and_create_database()
    return str(temp_db)


def make_task(**overrides):
    base = {
        'channel_id': '12345',
        'assignees': ['UserA', 'UserB'],
        'details': 'Fix the bug',
        'deadline': '01/01/2026 12:00 PM',
        'temp_channel_link': 'http://discord.com/channels/1/2',
        'assigner': 'Boss',
        'status': 'Pending',
        'title': 'Bug Fix',
    }
    base.update(overrides)
    return base


# ─── Store & Retrieve ─────────────────────────────────────────────────────────

def test_store_and_retrieve_task(mock_db_path):
    """A stored task should be retrievable by channel_id."""
    task = make_task()
    _store_task_in_database_sync(task)
    retrieved = _retrieve_task_from_database_sync('12345')
    assert retrieved is not None
    assert retrieved['title'] == 'Bug Fix'
    assert len(retrieved['assignees']) == 2

def test_retrieve_nonexistent_task(mock_db_path):
    """Retrieving a task that was never stored should return None."""
    result = _retrieve_task_from_database_sync('00000')
    assert result is None

def test_store_multiple_and_retrieve_all(mock_db_path):
    """Multiple stored tasks should all be returned."""
    _store_task_in_database_sync(make_task(channel_id='111', title='Task A'))
    _store_task_in_database_sync(make_task(channel_id='222', title='Task B'))
    tasks = _retrieve_all_tasks_from_database_sync()
    assert len(tasks) == 2
    titles = {t['title'] for t in tasks}
    assert titles == {'Task A', 'Task B'}

def test_retrieve_all_tasks_empty(mock_db_path):
    """An empty database should return an empty list."""
    tasks = _retrieve_all_tasks_from_database_sync()
    assert tasks == []


# ─── Update ───────────────────────────────────────────────────────────────────

def test_update_task_status(mock_db_path):
    """Updating a task's status should persist the new value."""
    task = make_task(channel_id='333', status='Pending')
    _store_task_in_database_sync(task)

    task['status'] = 'Completed by Assignee'
    _update_task_in_database_sync(task)

    updated = _retrieve_task_from_database_sync('333')
    assert updated['status'] == 'Completed by Assignee'

def test_update_task_deadline(mock_db_path):
    """Updating a task's deadline should persist the new value."""
    task = make_task(channel_id='444', deadline='10/01/2026 09:00 AM')
    _store_task_in_database_sync(task)

    task['deadline'] = '20/01/2026 05:00 PM'
    _update_task_in_database_sync(task)

    updated = _retrieve_task_from_database_sync('444')
    assert updated['deadline'] == '20/01/2026 05:00 PM'


# ─── Delete ───────────────────────────────────────────────────────────────────

def test_delete_task(mock_db_path):
    """Deleting a task by channel_id should remove it from the database."""
    task = make_task(channel_id='555')
    _store_task_in_database_sync(task)
    _delete_task_from_database_sync('555')
    result = _retrieve_task_from_database_sync('555')
    assert result is None

def test_delete_nonexistent_task_does_not_error(mock_db_path):
    """Deleting a task that doesn't exist should not raise an exception."""
    _delete_task_from_database_sync('99999')  # Should be a no-op


# ─── Pending tasks channel management ────────────────────────────────────────

def test_store_and_retrieve_pending_tasks_channel(mock_db_path):
    """Storing a pending tasks channel should be retrievable for that user."""
    user_id = 1001
    channel_id = 2001
    store_pending_tasks_channel(user_id, channel_id)
    cid, task_ids, msg_ids = retrieve_pending_tasks_channel(user_id)
    assert cid == channel_id
    assert task_ids == []
    assert msg_ids == []

def test_update_pending_tasks_channel(mock_db_path):
    """Updating task/message ID lists should persist correctly."""
    user_id = 1002
    channel_id = 2002
    store_pending_tasks_channel(user_id, channel_id)
    update_pending_tasks_channel(user_id, ['t1', 't2'], ['m1', 'm2'])
    cid, task_ids, msg_ids = retrieve_pending_tasks_channel(user_id)
    assert task_ids == ['t1', 't2']
    assert msg_ids == ['m1', 'm2']

def test_delete_pending_tasks_channel(mock_db_path):
    """Deleting a pending tasks channel record should remove it."""
    user_id = 1003
    channel_id = 2003
    store_pending_tasks_channel(user_id, channel_id)
    _delete_pending_tasks_channel_from_database(user_id)
    cid, task_ids, msg_ids = retrieve_pending_tasks_channel(user_id)
    assert cid is None

def test_retrieve_pending_tasks_channel_not_found(mock_db_path):
    """Retrieving for a user with no stored channel returns None."""
    cid, task_ids, msg_ids = retrieve_pending_tasks_channel(9999)
    assert cid is None
