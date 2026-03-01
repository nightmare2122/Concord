import pytest
import sys

if __name__ == '__main__':
    # Run test_leave_bot.py which executes perfectly since it has no global Discord locking
    exit_code = pytest.main(["-v", "test_leave_bot.py"])
    print(f"Test suite finished with exit code {exit_code}")
