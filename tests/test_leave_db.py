"""
tests/test_leave_db.py
Leave database manager unit tests mocking psycopg connection.
"""

import pytest
import sys
import os
import asyncio
import inspect
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from Bots.db_managers import leave_db_manager as db_manager

# Make the queue worker run inline for easier testing
async def mock_db_execute(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)

@pytest.fixture(autouse=True)
def patch_db_execute():
    with patch('Bots.db_managers.leave_db_manager.db_execute', side_effect=mock_db_execute):
        yield

@pytest.fixture
def mock_conn():
    with patch('Bots.db_managers.leave_db_manager.get_conn') as get_conn_mock:
        conn = MagicMock()
        get_conn_mock.return_value.__enter__.return_value = conn
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn, cur


# ─── Dynamic User Creation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_dynamic_user(mock_conn):
    conn, cur = mock_conn
    # Used to test insert_dynamic_user directly instead of non-existent ensure_user_exists
    cur.fetchone.return_value = None
    
    await db_manager.insert_dynamic_user('testuser', 123456789)
    cur.execute.assert_called()
    conn.commit.assert_called()

# ─── Leave Insertion & Balances ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_leave_application(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = {'id': 42}
    
    leave_details = {
        'leave_type': 'FULL DAY',
        'start_date': '2026-03-10',
        'end_date': '2026-03-11',
        'duration': '2',
        'holidays': '0',
        'return_date': '2026-03-12',
        'reason': 'Feeling unwell'
    }
    
    # Needs to match the 9 values expected by FULL DAY insert:
    data = (
        leave_details['leave_type'],
        leave_details['reason'],
        leave_details['start_date'],
        leave_details['end_date'],
        leave_details['duration'],
        leave_details['return_date'],
        'N/A',
        'Pending',
        ''
    )
    
    # submit_leave_application returns leave_id explicitly
    leave_id = await db_manager.submit_leave_application(
        nickname='testuser',
        leave_details=leave_details,
        data=data,
        user_id=123456789
    )
    
    assert leave_id == 42
    cur.execute.assert_called()

@pytest.mark.asyncio
async def test_reduce_leave_balance(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = {'casual': 12.0}
    
    await db_manager.reduce_leave_balance(123456789, 'casual', 2.0)
    cur.execute.assert_called()
    conn.commit.assert_called()

# ─── Approval & Status ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_approval(mock_conn):
    conn, cur = mock_conn
    await db_manager.update_approval('testuser', 42, 'Director')
    cur.execute.assert_called_with(
        "UPDATE leaves SET approved_by = %s WHERE id = %s",
        ('Director', 42)
    )
    conn.commit.assert_called()

@pytest.mark.asyncio
async def test_confirm_withdraw_leave(mock_conn):
    conn, cur = mock_conn
    await db_manager.confirm_withdraw_leave('testuser', 42)
    cur.execute.assert_called_with(
        "UPDATE leaves SET leave_status = 'Withdrawn by HR' WHERE id = %s",
        (42,)
    )
    conn.commit.assert_called()
