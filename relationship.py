# relationship.py - Advanced Relationship System
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)
DB_PATH = os.path.abspath(os.getenv("DB_PATH", "isabella.db"))


def init_relationship_table():
    """Create relationship table with improved structure"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            convo_id TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            notes TEXT,
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ Relationship system initialized")


def get_relationship_level(convo_id: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT level FROM relationship_state WHERE convo_id = ?", (convo_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1


def get_pet_name(convo_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT pet_name FROM relationship_state WHERE convo_id = ?", (convo_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else "babe"


def update_relationship(convo_id: str, delta: int = 1, pet_name: Optional[str] = None, note: Optional[str] = None):
    """Update relationship with safety and logging"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        current = get_relationship_level(convo_id)
        new_level = max(1, min(10, current + delta))

        c.execute('''
            INSERT INTO relationship_state 
            (convo_id, level, pet_name, notes, last_interaction)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(convo_id) DO UPDATE SET
                level = ?,
                pet_name = COALESCE(?, pet_name),
                notes = CASE 
                    WHEN ? IS NOT NULL THEN COALESCE(notes || '\n' || ?, notes)
                    ELSE notes 
                END,
                last_interaction = CURRENT_TIMESTAMP
        ''', (convo_id, new_level, pet_name, note, new_level, pet_name, note, note))
        
        conn.commit()
        logger.info(f"❤️ Relationship updated | convo={convo_id} | level={new_level} | delta={delta}")
        
    except Exception as e:
        logger.error(f"Error updating relationship for {convo_id}: {e}")
    finally:
        conn.close()


def apply_relationship_decay():
    """Decay relationship level for inactive users (call periodically)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Decay 1 level if no interaction in last 7 days
        c.execute('''
            UPDATE relationship_state 
            SET level = MAX(1, level - 1)
            WHERE last_interaction < datetime('now', '-7 days')
            AND level > 1
        ''')
        decayed = c.rowcount
        conn.commit()
        
        if decayed > 0:
            logger.info(f"⏳ Applied decay to {decayed} relationships")
    except Exception as e:
        logger.error(f"Decay error: {e}")
    finally:
        conn.close()


def reset_relationship(convo_id: str):
    """Reset relationship to default"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO relationship_state (convo_id, level, pet_name, notes, last_interaction)
            VALUES (?, 1, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(convo_id) DO UPDATE SET
                level = 1,
                pet_name = NULL,
                notes = NULL,
                last_interaction = CURRENT_TIMESTAMP
        ''', (convo_id,))
        conn.commit()
        logger.info(f"🔄 Relationship reset for convo {convo_id}")
    except Exception as e:
        logger.error(f"Reset error: {e}")
    finally:
        conn.close()


def add_relationship_note(convo_id: str, note: str, max_notes: int = 10):
    """Add note with size limit"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get current notes and limit length
        c.execute("SELECT notes FROM relationship_state WHERE convo_id = ?", (convo_id,))
        row = c.fetchone()
        current_notes = row[0] if row else ""
        
        new_notes = (current_notes + "\n" + note).strip() if current_notes else note
        
        # Keep only last N notes
        notes_list = new_notes.split("\n")[-max_notes:]
        trimmed_notes = "\n".join(notes_list)
        
        c.execute('''
            INSERT INTO relationship_state (convo_id, notes, last_interaction)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(convo_id) DO UPDATE SET
                notes = ?,
                last_interaction = CURRENT_TIMESTAMP
        ''', (convo_id, trimmed_notes, trimmed_notes))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Note error: {e}")
    finally:
        conn.close()


# Initialize
init_relationship_table()
