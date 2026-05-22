# migrate_db.py - Safe, idempotent database migration script for Isabella chatbot
# Simplified: No email/phone verification columns
import sqlite3
import os
import logging
from datetime import datetime
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

# ── Load DB path from .env (consistent with main app) ────────────────────────
load_dotenv()
DB_PATH = os.getenv("DB_PATH", "users.db")  # fallback to users.db
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

        # ── Migrate users table ──────────────────────────────────────────────
        # No verification columns added (removed email/phone OTP support)
        # If legacy verification columns exist from old migrations, log warning
        for legacy_col in ["is_email_verified", "email_verified_at", "phone", "is_phone_verified", "phone_verified_at"]:
            if column_exists("users", legacy_col, conn):
                logger.warning(
                    f"Found legacy verification column '{legacy_col}' - "
                    "consider dropping it manually if no longer needed "
                    "(SQLite does not support DROP COLUMN easily)"
                )

        # Ensure core users columns are present (already created by init_db)
        logger.info("Users table columns verified (no verification fields added)")

        # ── Migrate user_pics table ──────────────────────────────────────────
        if not table_exists("user_pics", conn):
            c.execute("""
                CREATE TABLE user_pics (
                    user_id INTEGER PRIMARY KEY,
                    pic_count_this_month INTEGER DEFAULT 0,
                    month_year TEXT DEFAULT (strftime('%Y-%m', 'now')),
                    seen_pics TEXT DEFAULT '',
                    last_pic_timestamp DATETIME,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            logger.info("Created user_pics table")
        else:
            logger.info("user_pics table already exists")

        # Ensure user_pics columns (idempotent)
        for col, col_type in [
            ("pic_count_this_month", "INTEGER DEFAULT 0"),
            ("month_year", "TEXT DEFAULT (strftime('%Y-%m', 'now'))"),
            ("seen_pics", "TEXT DEFAULT ''"),
            ("last_pic_timestamp", "DATETIME")
        ]:
            if not column_exists("user_pics", col, conn):
                c.execute(f"ALTER TABLE user_pics ADD COLUMN {col} {col_type}")
                logger.info(f"Added '{col}' to user_pics")

        # ── Create violations table if missing ───────────────────────────────
        if not table_exists("violations", conn):
            c.execute("""
                CREATE TABLE violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            logger.info("Created violations table")
        else:
            logger.info("violations table already exists")

        # ── Optional: Add indexes for performance ────────────────────────────
        c.execute("CREATE INDEX IF NOT EXISTS idx_violations_user_id ON violations(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_user_id ON chat_history(user_id)")

        conn.commit()
        logger.info("Migration completed successfully!")

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

        # ── Analytics Tables ─────────────────────────────────────────────────
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
        
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_time ON analytics_events(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_convo ON analytics_events(convo_id)')

if __name__ == "__main__":
    print("Starting database migration...")
    migrate()
    print("Migration script finished. Check migration.log for details.")
