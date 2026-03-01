"""
run_bot_tests.py — Run the full Concord test suite.
Usage: python tests/run_bot_tests.py  (from the repo root)
"""

import pytest
import sys
import os

if __name__ == '__main__':
    # Always resolve paths relative to this script so it works from any CWD
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    exit_code = pytest.main(["-v", "--tb=short", tests_dir])
    print(f"\nTest suite finished with exit code {exit_code}")
    sys.exit(exit_code)
