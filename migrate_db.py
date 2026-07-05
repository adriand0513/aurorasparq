# migrate_db.py - Safe, idempotent database migration script for Isabella chatbot
import sqlite3
import os
import logging
from dotenv import load_dotenv

# ── Setup logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("migration.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ── Load DB path ─────────────────────────────────────────────────────────────
load_dotenv()
DB_PATH = os.getenv("DB_PATH", "isabella.db")
logger.info(f"Migration starting - Using database: {os.path.abspath(DB_PATH)}")
logger.info(f"DB file exists? {os.path.exists(DB_PATH)}")


def column_exists(table_name: str, column_name: str, conn: sqlite3.Connection) -> bool:
    """Check if a column already exists in a table."""
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in c.fetchall()]
    return column_name in columns


def table_exists(table_name: str, conn: sqlite3.Connection) -> bool:
    """Check if a table exists."""
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return c.fetchone() is not None


def migrate():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        logger.info("Connected to database successfully")

        # ── Users Table ─────────────────────────────────────────────────────
        if not table_exists("users", conn):
            c.execute('''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    full_name TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_active DATETIME
                )
            ''')
            logger.info("Created users table with full_name column")
        else:
            # Add full_name if missing
            if not column_exists("users", "full_name", conn):
                c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
                logger.info("Added full_name column to existing users table")

        # ── Chat History Table ──────────────────────────────────────────────
        if not table_exists("chat_history", conn):
            c.execute('''
                CREATE TABLE chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    convo_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created chat_history table")
        else:
            # Safe migration for convo_id
            if not column_exists("chat_history", "convo_id", conn):
                c.execute("ALTER TABLE chat_history ADD COLUMN convo_id TEXT")
                logger.info("Added convo_id column to chat_history")

        # ── Key Facts Table ─────────────────────────────────────────────────
        if not table_exists("key_facts", conn):
            c.execute('''
                CREATE TABLE key_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    convo_id TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    importance INTEGER DEFAULT 5,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_recalled DATETIME
                )
            ''')
            logger.info("Created key_facts table")

        # ── Relationship State Table ────────────────────────────────────────
        if not table_exists("relationship_state", conn):
            c.execute('''
                CREATE TABLE relationship_state (
                    convo_id TEXT PRIMARY KEY,
                    level INTEGER DEFAULT 1,
                    pet_name TEXT,
                    notes TEXT,
                    last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("Created relationship_state table")

        # ── Analytics Events Table ──────────────────────────────────────────
        if not table_exists("analytics_events", conn):
            c.execute('''
                CREATE TABLE analytics_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    convo_id TEXT,
                    user_id INTEGER,
                    metadata TEXT,
                    duration_ms INTEGER
                )
            ''')
            logger.info("Created analytics_events table")

        # ── Indexes ─────────────────────────────────────────────────────────
        c.execute('CREATE INDEX IF NOT EXISTS idx_convo_id ON chat_history (convo_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_history (timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_facts_convo ON key_facts (convo_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_time ON analytics_events(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_convo ON analytics_events(convo_id)')

        # Legacy tables (optional)
        if not table_exists("user_pics", conn):
            c.execute("""
                CREATE TABLE user_pics (
                    user_id INTEGER PRIMARY KEY,
                    pic_count_this_month INTEGER DEFAULT 0,
                    month_year TEXT DEFAULT (strftime('%Y-%m', 'now')),
                    seen_pics TEXT DEFAULT '',
                    last_pic_timestamp DATETIME
                )
            """)
            logger.info("Created user_pics table")

        if not table_exists("violations", conn):
            c.execute("""
                CREATE TABLE violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created violations table")

        conn.commit()
        logger.info("✅ Migration completed successfully!")

    except sqlite3.Error as e:
        logger.error(f"SQLite error during migration: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed")


if __name__ == "__main__":
    print("Starting database migration...")
    migrate()
    print("Migration script finished. Check migration.log for details.")