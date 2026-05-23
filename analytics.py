# analytics.py - Enhanced with Daily Signups, Retention & Engagement
import sqlite3
import json
from datetime import datetime
from collections import defaultdict
from config import DB_PATH

def ensure_analytics_table():
    """Create the analytics table if it doesn't exist"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                convo_id TEXT,
                user_id INTEGER,
                metadata TEXT,
                duration_ms INTEGER
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_time ON analytics_events(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_convo ON analytics_events(convo_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics_events(user_id)')
        conn.commit()
        print("✅ Analytics table ensured")
    except Exception as e:
        print(f"Warning: Could not ensure analytics table: {e}")
    finally:
        if conn:
            conn.close()


ensure_analytics_table()


def log_event(event_type: str, convo_id: str = None, user_id: int = None,
              metadata: dict = None, duration_ms: int = None):
    """Log any analytics event"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO analytics_events
            (event_type, convo_id, user_id, metadata, duration_ms)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            event_type,
            convo_id,
            user_id,
            json.dumps(metadata) if metadata else None,
            duration_ms
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Analytics log error: {e}")


def get_live_stats():
    """Main dashboard stats with retention & engagement"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Total Registered Users
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0] or 0

    # Daily Signups (today)
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = DATE('now')")
    daily_signups = c.fetchone()[0] or 0

    # Active Users (last 24h)
    c.execute('''
        SELECT COUNT(DISTINCT user_id) 
        FROM analytics_events 
        WHERE event_type = 'message_sent' 
        AND timestamp > datetime('now', '-1 day')
    ''')
    active_users_24h = c.fetchone()[0] or 0

    # Messages per minute
    c.execute('''
        SELECT COUNT(*) 
        FROM analytics_events 
        WHERE timestamp > datetime('now', '-1 minute')
        AND event_type IN ('message_sent', 'message_received')
    ''')
    messages_per_min = c.fetchone()[0] or 0

    # Average Response Time (last hour)
    c.execute('''
        SELECT AVG(duration_ms) 
        FROM analytics_events 
        WHERE event_type = 'response_generated' 
        AND duration_ms IS NOT NULL
        AND timestamp > datetime('now', '-1 hour')
    ''')
    avg_response = round(c.fetchone()[0] or 0)

    # Retention Rate (7-day)
    c.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'user_registered'
        AND timestamp > datetime('now', '-8 days')
    ''')
    new_users = c.fetchone()[0] or 1

    c.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'message_sent'
        AND timestamp > datetime('now', '-7 days')
    ''')
    returning_users = c.fetchone()[0] or 0
    retention_rate = round((returning_users / new_users) * 100, 1)

    # Engagement Rate (messages per active user in last 7 days)
    c.execute('''
        SELECT COUNT(*) 
        FROM analytics_events 
        WHERE event_type IN ('message_sent', 'message_received')
        AND timestamp > datetime('now', '-7 days')
    ''')
    total_messages = c.fetchone()[0] or 0

    c.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events 
        WHERE event_type = 'message_sent'
        AND timestamp > datetime('now', '-7 days')
    ''')
    active_users_week = c.fetchone()[0] or 1
    engagement_rate = round(total_messages / active_users_week, 1)

    conn.close()

    return {
        "total_users": total_users,
        "daily_signups": daily_signups,
        "active_users_24h": active_users_24h,
        "messages_per_minute": messages_per_min,
        "avg_response_time_ms": avg_response,
        "retention_rate": retention_rate,
        "engagement_rate": engagement_rate,
        "timestamp": datetime.now().isoformat()
    }


def get_archetype_distribution():
    """Get overall archetype statistics"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT metadata
        FROM analytics_events
        WHERE event_type = 'archetype_detected'
    ''')
    counts = defaultdict(int)
    for row in c.fetchall():
        if row[0]:
            try:
                data = json.loads(row[0])
                arch = data.get("archetype")
                if arch:
                    counts[arch] += 1
            except:
                pass
    conn.close()
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
