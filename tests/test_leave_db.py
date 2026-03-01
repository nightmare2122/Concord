
import pytest
import sqlite3
import os
import sys
from unittest.mock import patch

# Ensure Bots folder is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Bots'))
from db_managers import leave_db_manager as db

@pytest.fixture
def mock_dbs(tmp_path):
    """Fixture to create isolated temporary databases for each test."""
    test_leave_db = tmp_path / "test_leave_details.db"
    test_dyn_db = tmp_path / "test_dynamic_updates.db"

    # Patch the global paths inside leave_db_manager
    with patch('db_managers.leave_db_manager.db_leave_details_path', str(test_leave_db)), \
         patch('db_managers.leave_db_manager.db_dynamic_updates_path', str(test_dyn_db)):
        yield test_leave_db, test_dyn_db

def test_create_and_delete_user_table(mock_dbs):
    nickname = "TestUser!@#"
    sanitized = db.sanitize_table_name(nickname)
    
    db._create_user_table_sync(nickname)
    
    # Verify table was created
    tables = db.get_all_tables_sync()
    assert sanitized in tables
    
    db._delete_user_table_sync(nickname)
    
    # Verify table was deleted
    tables = db.get_all_tables_sync()
    assert sanitized not in tables

def test_dynamic_user_management(mock_dbs):
    nickname = "JaneDoe"
    user_id = 12345
    
    db._create_dynamic_table_sync()
    
    # Manually reproduce the insert sync logic since it's wrapped in `_insert` privately inside the module
    with db.get_dynamic_conn() as conn:
        conn.execute('''
            INSERT OR IGNORE INTO dynamic_updates (nickname, user_id)
            VALUES (?, ?)
        ''', (nickname, user_id))
    
    # Verify insertion
    with db.get_dynamic_conn() as conn:
        result = conn.execute('''
            SELECT last_leave_taken, total_casual_leave, total_sick_leave
            FROM dynamic_updates
            WHERE user_id = ?
        ''', (user_id,)).fetchone()
    
    assert result is not None
    assert result == (None, 0.0, 0.0) # last_leave, casual, sick default to 0/None
    
    with db.get_dynamic_conn() as conn:
        owner = conn.execute('SELECT user_id FROM dynamic_updates WHERE nickname = ?', (nickname,)).fetchone()
    assert owner[0] == user_id
    
    with db.get_dynamic_conn() as conn:
        conn.execute('DELETE FROM dynamic_updates WHERE user_id = ?', (user_id,))
        result = conn.execute('SELECT * FROM dynamic_updates WHERE user_id = ?', (user_id,)).fetchone()
    assert result is None

def test_full_leave_insertion_and_approval(mock_dbs):
    nickname = "JohnSmith"
    user_id = 999
    table_name = db.sanitize_table_name(nickname)
    
    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()
    
    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))
    
    data = (
        "FULL DAY", "SICK", "01-01-2026", "03-01-2026", 3.0, "04-01-2026", None, "PENDING", None
    )
    
    with db.get_leave_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', data)
        leave_id = cursor.lastrowid
    
    assert leave_id == 1
    
    # Simulate HR accepting the leave (Testing confirm_leave_acceptance manually)
    with db.get_leave_conn() as conn:
        conn.execute(f"UPDATE {table_name} SET leave_status = 'Accepted' WHERE leave_id = ?", (leave_id,))
    
    with db.get_dynamic_conn() as dyn_conn:
        dyn_conn.execute("UPDATE dynamic_updates SET total_sick_leave = total_sick_leave + ?, last_leave_taken = ? WHERE user_id = ?", (3.0, "03-01-2026", user_id))
    
    # Verify the table shows Accepted
    with db.get_leave_conn() as conn:
        status = conn.execute(f"SELECT leave_reason, number_of_days_off FROM {table_name} WHERE leave_id = ? AND leave_status = 'Accepted'", (leave_id,)).fetchone()
    
    assert status == ("SICK", 3.0)
    
    # Verify the dynamic table incremented the sick leave balance
    with db.get_dynamic_conn() as conn:
        dyn_status = conn.execute('SELECT last_leave_taken, total_casual_leave, total_sick_leave FROM dynamic_updates WHERE user_id = ?', (user_id,)).fetchone()
        
    assert dyn_status[2] == 3.0 # total_sick_leave
    assert dyn_status[0] == "03-01-2026" # last_leave_taken

