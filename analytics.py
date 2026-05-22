# analytics.py
import sqlite3
import json
import time
from datetime import datetime
from collections import defaultdict
from config import DB_PATH

def log_event(event_type: str, convo_id: str = None, user_id: int = None, 
              metadata: dict = None, duration_ms: int = None):
    """Log any analytics event"""
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


def get_live_stats():
    """Get real-time aggregated stats"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Active conversations in last 5 minutes
    c.execute('''
        SELECT COUNT(DISTINCT convo_id) 
        FROM analytics_events 
        WHERE timestamp > datetime('now', '-5 minutes')
        AND event_type = 'message_sent'
    ''')
    active_convos = c.fetchone()[0] or 0

    # Messages per minute
    c.execute('''
        SELECT COUNT(*) 
        FROM analytics_events 
        WHERE timestamp > datetime('now', '-1 minute')
        AND event_type IN ('message_sent', 'message_received')
    ''')
    messages_per_min = c.fetchone()[0] or 0

    # Avg response time
    c.execute('''
        SELECT AVG(duration_ms) 
        FROM analytics_events 
        WHERE event_type = 'response_generated' 
        AND duration_ms IS NOT NULL
        AND timestamp > datetime('now', '-30 minutes')
    ''')
    avg_response = round(c.fetchone()[0] or 0)

    conn.close()

    return {
        "active_sessions": active_convos,
        "messages_per_minute": messages_per_min,
        "avg_response_time_ms": avg_response,
        "timestamp": datetime.now().isoformat()
    }


def get_top_topics(limit=10):
    """Simple topic extraction (can be enhanced with LLM later)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT metadata 
        FROM analytics_events 
        WHERE event_type = 'message_sent' 
        ORDER BY timestamp DESC LIMIT 200
    ''')
    rows = c.fetchall()
    conn.close()
    
    # Very basic keyword counting
    keywords = defaultdict(int)
    for row in rows:
        if row[0]:
            try:
                data = json.loads(row[0])
                text = data.get('message', '').lower()
                for word in ['love', 'miss', 'want', 'need', 'sexy', 'date', 'relationship', 'lonely', 'horny', 'flirt']:
                    if word in text:
                        keywords[word] += 1
            except:
                pass
    return dict(sorted(keywords.items(), key=lambda x: x[1], reverse=True)[:limit])
