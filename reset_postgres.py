import asyncio
import os
import psycopg
from dotenv import load_dotenv
import sys

# Add project root to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Bots'))

from db_managers.task_db_manager import initialize_task_db
from db_managers.leave_db_manager import initialize_leave_db
from db_managers.discovery_db_manager import _initialize_discovery_db_sync

load_dotenv()

# PostgreSQL Credentials
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "concord_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

def get_conn():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

async def reset_database():
    print(f"Connecting to {DB_NAME} on {DB_HOST}:{DB_PORT}...")
    
    confirm = input(f"WARNING: This will delete ALL data in {DB_NAME}. Are you sure? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted.")
        return

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Disable triggers to avoid foreign key issues during mass drop
                cur.execute("SET session_replication_role = 'replica';")
                
                # Fetch all tables in current schema
                cur.execute("""
                    SELECT tablename FROM pg_tables 
                    WHERE schemaname = 'public'
                """)
                tables = cur.fetchall()
                
                for table in tables:
                    table_name = table[0]
                    print(f"Dropping table: {table_name}")
                    cur.execute(f"DROP TABLE IF EXISTS \"{table_name}\" CASCADE")
                
                cur.execute("SET session_replication_role = 'origin';")
                conn.commit()
                print("All tables dropped successfully.")

        print("Re-initializing schemas...")
        
        # Initialize Discovery (Sync function)
        _initialize_discovery_db_sync()
        print("✔ Discovery schema initialized.")
        
        # Initialize Tasks (Async)
        await initialize_task_db()
        print("✔ Task schema initialized.")
        
        # Initialize Leave (Async)
        await initialize_leave_db()
        print("✔ Leave schema initialized.")

        print("\nDatabase reset complete. The bot is ready for a fresh start.")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(reset_database())
