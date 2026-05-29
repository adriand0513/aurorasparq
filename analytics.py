# analytics.py - PostgreSQL Version (Fixed JSON Serialization)
import psycopg2
import json
from datetime import datetime
from collections import defaultdict
from config import DATABASE_URL

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def ensure_analytics_table():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS analytics_events (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                convo_id TEXT,
                user_id INTEGER,
                metadata TEXT,
                duration_ms INTEGER
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_analytics_time ON analytics_events(timestamp)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_analytics_convo ON analytics_events(convo_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics_events(user_id)')
        conn.commit()
        print("✅ Analytics table ensured in PostgreSQL")
    except Exception as e:
        print(f"Warning: Could not ensure analytics table: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()


ensure_analytics_table()


def log_event(event_type: str, convo_id: str = None, user_id: int = None,
              metadata: dict = None, duration_ms: int = None):
    """Log any analytics event - Safe for JSON"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Fix: Convert any datetime objects to string for JSON
        if metadata:
            safe_metadata = {}
            for key, value in metadata.items():
                if hasattr(value, 'isoformat'):  # datetime object
                    safe_metadata[key] = value.isoformat()
                else:
                    safe_metadata[key] = value
            metadata = safe_metadata
        
        cur.execute('''
            INSERT INTO analytics_events
            (event_type, convo_id, user_id, metadata, duration_ms)
            VALUES (%s, %s, %s, %s, %s)
        ''', (
            event_type,
            convo_id,
            user_id,
            json.dumps(metadata) if metadata else None,
            duration_ms
        ))
        conn.commit()
    except Exception as e:
        print(f"Analytics log error: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()


def get_live_stats():
    """Main dashboard stats with retention & engagement"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Total Registered Users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0] or 0

    # Daily Signups
    cur.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = CURRENT_DATE")
    daily_signups = cur.fetchone()[0] or 0

    # Active Users (last 24h)
    cur.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'message_sent'
        AND timestamp > NOW() - INTERVAL '1 day'
    ''')
    active_users_24h = cur.fetchone()[0] or 0

    # Messages per minute
    cur.execute('''
        SELECT COUNT(*)
        FROM analytics_events
        WHERE timestamp > NOW() - INTERVAL '1 minute'
        AND event_type IN ('message_sent', 'message_received')
    ''')
    messages_per_min = cur.fetchone()[0] or 0

    # Average Response Time
    cur.execute('''
        SELECT AVG(duration_ms)
        FROM analytics_events
        WHERE event_type = 'response_generated'
        AND duration_ms IS NOT NULL
        AND timestamp > NOW() - INTERVAL '1 hour'
    ''')
    avg_response = round(cur.fetchone()[0] or 0)

    # Retention Rate (7-day)
    cur.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'user_registered'
        AND timestamp > NOW() - INTERVAL '8 days'
    ''')
    new_users = cur.fetchone()[0] or 1

    cur.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'message_sent'
        AND timestamp > NOW() - INTERVAL '7 days'
    ''')
    returning_users = cur.fetchone()[0] or 0
    retention_rate = round((returning_users / new_users) * 100, 1)

    # Engagement Rate
    cur.execute('''
        SELECT COUNT(*)
        FROM analytics_events
        WHERE event_type IN ('message_sent', 'message_received')
        AND timestamp > NOW() - INTERVAL '7 days'
    ''')
    total_messages = cur.fetchone()[0] or 0

    cur.execute('''
        SELECT COUNT(DISTINCT user_id)
        FROM analytics_events
        WHERE event_type = 'message_sent'
        AND timestamp > NOW() - INTERVAL '7 days'
    ''')
    active_users_week = cur.fetchone()[0] or 1
    engagement_rate = round(total_messages / active_users_week, 1)

    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT metadata
        FROM analytics_events
        WHERE event_type = 'archetype_detected'
    ''')
    counts = defaultdict(int)
    for row in cur.fetchall():
        if row[0]:
            try:
                data = json.loads(row[0])
                arch = data.get("archetype")
                if arch:
                    counts[arch] += 1
            except:
                pass
    cur.close()
    conn.close()
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
