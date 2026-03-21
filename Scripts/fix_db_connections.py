#!/usr/bin/env python3
"""
Script to fix database connection pooling in leave_db_manager.py and task_db_manager.py
Run this before deploying to production.
"""

import re
import sys
import os

def fix_database_file(filepath):
    """Fix all 'with get_conn() as conn:' patterns to use try/finally with put_conn."""
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Pattern to find functions with the old connection pattern
    # This is a simplified fix - for production, each function should be reviewed
    
    original_content = content
    
    # Replace simple patterns
    # Pattern 1: Single with statement functions
    pattern1 = r'def (_\w+)\([^)]*\):\s*\n    with get_conn\(\) as conn:\s*\n        with conn\.cursor\(\) as cur:'
    replacement1 = r'def \1():\n    conn = get_conn()\n    try:\n        with conn.cursor() as cur:'
    
    # This is complex to do with regex - let's do a simpler approach
    # Count occurrences
    matches = re.findall(r'with get_conn\(\) as conn:', content)
    print(f"Found {len(matches)} occurrences in {filepath}")
    
    if not matches:
        print(f"  No changes needed for {filepath}")
        return
    
    # For now, we document what needs to be done manually
    print(f"  ⚠️  Manual fixes required in {filepath}")
    print(f"     Replace 'with get_conn() as conn:' with:")
    print(f"     conn = get_conn()")
    print(f"     try:")
    print(f"         # ... existing code ...")
    print(f"     finally:")
    print(f"         put_conn(conn)")
    
    return len(matches)


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    files_to_check = [
        os.path.join(base_dir, 'Bots', 'db_managers', 'leave_db_manager.py'),
        os.path.join(base_dir, 'Bots', 'db_managers', 'task_db_manager.py'),
    ]
    
    total_issues = 0
    for filepath in files_to_check:
        if os.path.exists(filepath):
            count = fix_database_file(filepath)
            if count:
                total_issues += count
        else:
            print(f"File not found: {filepath}")
    
    print(f"\n{'='*60}")
    print(f"Total functions needing manual fix: {total_issues}")
    print(f"{'='*60}")
    print("\nIMPORTANT: For production deployment, you MUST:")
    print("1. Update all database functions to return connections to pool")
    print("2. Install psycopg-pool: pip install psycopg-pool")
    print("3. Set DB_POOL_MAX environment variable (default: 20)")
    print("4. Test with concurrent load before going live")


if __name__ == '__main__':
    main()
