import pytest
import sqlite3
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Bots'))
from db_managers import task_db_manager as db_manager
from db_managers.task_db_manager import _store_task_in_database_sync, _retrieve_task_from_database_sync, check_and_create_database, retrieve_all_tasks_from_database, _retrieve_all_tasks_from_database_sync

@pytest.fixture
def mock_db_path(monkeypatch, tmp_path):
    # Route the database to a temporary file
    temp_db = tmp_path / "test_tasks.db"
    monkeypatch.setattr(db_manager, "db_path", str(temp_db))
    # We also need to run check_and_create_database to initialize tables
    check_and_create_database()
    return str(temp_db)

def test_store_and_retrieve_task(mock_db_path):
    task_data = {
        'channel_id': '12345',
        'assignees': ['UserA', 'UserB'],
        'details': 'Fix the bug',
        'deadline': '01/01/2026 12:00 PM',
        'temp_channel_link': 'http://discord.com/channels/123/123',
        'assigner': 'Boss',
        'status': 'Pending',
        'title': 'Bug Fix'
    }
    
    # Store the task
    _store_task_in_database_sync(task_data)
    
    # Retrieve the task
    retrieved = _retrieve_task_from_database_sync('12345')
    
    assert retrieved is not None
    assert retrieved['title'] == 'Bug Fix'
    assert len(retrieved['assignees']) == 2

def test_retrieve_all_tasks(mock_db_path):
    task_data = {
        'channel_id': '45678',
        'assignees': ['UserA'],
        'details': 'Update doc',
        'deadline': '05/01/2026 12:00 PM',
        'temp_channel_link': 'http://discord.com/channels/123/456',
        'assigner': 'Boss',
        'status': 'Pending',
        'title': 'Doc Update'
    }
    
    _store_task_in_database_sync(task_data)
    
    tasks = _retrieve_all_tasks_from_database_sync()
    
    assert len(tasks) == 1
    assert str(tasks[0]['channel_id']) == '45678'
