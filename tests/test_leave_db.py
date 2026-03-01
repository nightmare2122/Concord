"""
tests/test_leave_db.py
Leave database manager unit tests using temporary SQLite files.
"""

import pytest
import sqlite3
import os
import sys
from unittest.mock import patch

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Bots'))
from db_managers import leave_db_manager as db


@pytest.fixture
def mock_dbs(tmp_path):
    """Create isolated temporary leave and dynamic update databases per test."""
    test_leave_db = tmp_path / "test_leave_details.db"
    test_dyn_db = tmp_path / "test_dynamic_updates.db"

    with patch('db_managers.leave_db_manager.db_leave_details_path', str(test_leave_db)), \
         patch('db_managers.leave_db_manager.db_dynamic_updates_path', str(test_dyn_db)):
        yield test_leave_db, test_dyn_db


# ─── Table creation / deletion ────────────────────────────────────────────────

def test_create_and_delete_user_table(mock_dbs):
    nickname = "TestUser!@#"
    sanitized = db.sanitize_table_name(nickname)

    db._create_user_table_sync(nickname)
    assert sanitized in db.get_all_tables_sync()

    db._delete_user_table_sync(nickname)
    assert sanitized not in db.get_all_tables_sync()

def test_create_user_table_idempotent(mock_dbs):
    """Creating the same user table twice should not raise an error."""
    db._create_user_table_sync("Alice")
    db._create_user_table_sync("Alice")  # Second call should be harmless
    assert db.sanitize_table_name("Alice") in db.get_all_tables_sync()

def test_sanitize_table_name_strips_special_chars():
    """sanitize_table_name should replace non-alphanumeric characters with underscores."""
    result = db.sanitize_table_name("Hello World #123!")
    assert " " not in result
    assert "#" not in result
    assert "!" not in result


# ─── Dynamic user management ──────────────────────────────────────────────────

def test_dynamic_user_management(mock_dbs):
    """Insert a dynamic user and verify default values, then delete."""
    nickname = "JaneDoe"
    user_id = 12345
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO dynamic_updates (nickname, user_id) VALUES (?, ?)',
            (nickname, user_id)
        )

    with db.get_dynamic_conn() as conn:
        result = conn.execute(
            'SELECT last_leave_taken, total_casual_leave, total_sick_leave FROM dynamic_updates WHERE user_id = ?',
            (user_id,)
        ).fetchone()

    assert result == (None, 0.0, 0.0)

    with db.get_dynamic_conn() as conn:
        conn.execute('DELETE FROM dynamic_updates WHERE user_id = ?', (user_id,))
        gone = conn.execute('SELECT * FROM dynamic_updates WHERE user_id = ?', (user_id,)).fetchone()
    assert gone is None

def test_dynamic_table_duplicate_insert_ignored(mock_dbs):
    """INSERT OR IGNORE should not raise on duplicate user_id."""
    db._create_dynamic_table_sync()
    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT OR IGNORE INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', ("Dup", 111))
        conn.execute('INSERT OR IGNORE INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', ("Dup", 111))
        count = conn.execute('SELECT COUNT(*) FROM dynamic_updates WHERE user_id = 111').fetchone()[0]
    assert count == 1


# ─── Leave insertion, approval, and balance update ────────────────────────────

def test_full_leave_insertion_and_approval(mock_dbs):
    nickname = "JohnSmith"
    user_id = 999
    table_name = db.sanitize_table_name(nickname)

    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))

    data = ("FULL DAY", "SICK", "01-01-2026", "03-01-2026", 3.0, "04-01-2026", None, "PENDING", None)
    with db.get_leave_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            data
        )
        leave_id = cursor.lastrowid
    assert leave_id == 1

    # Approve and update balances
    with db.get_leave_conn() as conn:
        conn.execute(f"UPDATE {table_name} SET leave_status = 'Accepted' WHERE leave_id = ?", (leave_id,))
    with db.get_dynamic_conn() as conn:
        conn.execute(
            "UPDATE dynamic_updates SET total_sick_leave = total_sick_leave + ?, last_leave_taken = ? WHERE user_id = ?",
            (3.0, "03-01-2026", user_id)
        )

    with db.get_leave_conn() as conn:
        row = conn.execute(
            f"SELECT leave_reason, number_of_days_off FROM {table_name} WHERE leave_id = ? AND leave_status = 'Accepted'",
            (leave_id,)
        ).fetchone()
    assert row == ("SICK", 3.0)

    with db.get_dynamic_conn() as conn:
        dyn = conn.execute(
            'SELECT last_leave_taken, total_casual_leave, total_sick_leave FROM dynamic_updates WHERE user_id = ?',
            (user_id,)
        ).fetchone()
    assert dyn[2] == 3.0   # sick leave deducted
    assert dyn[0] == "03-01-2026"


def test_casual_leave_balance_update(mock_dbs):
    """Approving a casual leave should deduct from total_casual_leave."""
    nickname = "CasualUser"
    user_id = 888
    table_name = db.sanitize_table_name(nickname)

    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))

    with db.get_leave_conn() as conn:
        conn.execute(
            f'INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ("HALF DAY", "CASUAL", "14-03-2026", None, 0.5, None, "FORENOON", "PENDING", None)
        )
        leave_id = conn.execute(f"SELECT last_insert_rowid()").fetchone()[0]

    with db.get_leave_conn() as conn:
        conn.execute(f"UPDATE {table_name} SET leave_status = 'Accepted' WHERE leave_id = ?", (leave_id,))
    with db.get_dynamic_conn() as conn:
        conn.execute(
            "UPDATE dynamic_updates SET total_casual_leave = total_casual_leave + ? WHERE user_id = ?",
            (0.5, user_id)
        )

    with db.get_dynamic_conn() as conn:
        row = conn.execute('SELECT total_casual_leave FROM dynamic_updates WHERE user_id = ?', (user_id,)).fetchone()
    assert row[0] == 0.5


def test_decline_leave_status(mock_dbs):
    """Declining a leave should mark it as Declined, not Accepted."""
    nickname = "DeclineUser"
    user_id = 777
    table_name = db.sanitize_table_name(nickname)
    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))
    with db.get_leave_conn() as conn:
        conn.execute(
            f'INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ("FULL DAY", "CASUAL", "15-03-2026", "15-03-2026", 1.0, "16-03-2026", None, "PENDING", None)
        )
        leave_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Decline it
    with db.get_leave_conn() as conn:
        conn.execute(
            f"UPDATE {table_name} SET leave_status = 'Declined', reason_for_decline = ? WHERE leave_id = ?",
            ("Insufficient notice", leave_id)
        )

    with db.get_leave_conn() as conn:
        row = conn.execute(f"SELECT leave_status, reason_for_decline FROM {table_name} WHERE leave_id = ?", (leave_id,)).fetchone()
    assert row[0] == 'Declined'
    assert row[1] == "Insufficient notice"


def test_multiple_leaves_per_user(mock_dbs):
    """A user can have multiple leave records with sequential IDs."""
    nickname = "MultiLeave"
    user_id = 555
    table_name = db.sanitize_table_name(nickname)
    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))

    with db.get_leave_conn() as conn:
        for i in range(3):
            conn.execute(
                f'INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                ("FULL DAY", "SICK", f"0{i+1}-04-2026", f"0{i+1}-04-2026", 1.0, f"0{i+2}-04-2026", None, "PENDING", None)
            )
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    assert count == 3


def test_withdraw_reverts_leave_status(mock_dbs):
    """Withdrawing a leave should change its status away from Accepted."""
    nickname = "WithdrawUser"
    user_id = 444
    table_name = db.sanitize_table_name(nickname)
    db._create_user_table_sync(nickname)
    db._create_dynamic_table_sync()

    with db.get_dynamic_conn() as conn:
        conn.execute('INSERT INTO dynamic_updates (nickname, user_id) VALUES (?, ?)', (nickname, user_id))
    with db.get_leave_conn() as conn:
        conn.execute(
            f'INSERT INTO {table_name} (leave_type, leave_reason, date_from, date_to, number_of_days_off, resume_office_on, time_off, leave_status, reason_for_decline) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ("FULL DAY", "CASUAL", "10-05-2026", "10-05-2026", 1.0, "11-05-2026", None, "Accepted", None)
        )
        leave_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Withdraw: set status to Withdrawn and revert the casual leave balance
    with db.get_leave_conn() as conn:
        conn.execute(f"UPDATE {table_name} SET leave_status = 'Withdrawn' WHERE leave_id = ?", (leave_id,))
    with db.get_dynamic_conn() as conn:
        conn.execute(
            "UPDATE dynamic_updates SET total_casual_leave = total_casual_leave - ? WHERE user_id = ?",
            (1.0, user_id)
        )

    with db.get_leave_conn() as conn:
        status = conn.execute(f"SELECT leave_status FROM {table_name} WHERE leave_id = ?", (leave_id,)).fetchone()[0]
    assert status == 'Withdrawn'
