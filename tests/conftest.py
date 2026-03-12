"""
Global test configuration for Concord bot.
Mocks out the async database executor queue so tests do not hang.
"""

import pytest
import asyncio
import inspect
from unittest.mock import patch

# Inline DB executor so it resolves immediately instead of queueing
async def mock_db_execute(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)

@pytest.fixture(autouse=True)
def patch_db_execute_global():
    with patch('asyncio.sleep', return_value=None):
        with patch('Bots.db_managers.base_db.db_execute', side_effect=mock_db_execute):
            # We also need to patch the direct imports inside db_managers in case they are bound early
            with patch('Bots.db_managers.task_db_manager.db_execute', side_effect=mock_db_execute, create=True):
                with patch('Bots.db_managers.leave_db_manager.db_execute', side_effect=mock_db_execute, create=True):
                    with patch('Bots.db_managers.discovery_db_manager.db_execute', side_effect=mock_db_execute, create=True):
                        yield
