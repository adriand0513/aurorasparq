# analytics.py
"""Lightweight event log. Never lets an analytics failure break a request."""

import json
import logging
from typing import Optional

from database import db_cursor

logger = logging.getLogger(__name__)


def log_event(
    event_type: str,
    convo_id: Optional[str] = None,
    user_id: Optional[int] = None,
    metadata: Optional[dict] = None,
    duration_ms: Optional[int] = None,
) -> None:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO analytics_events (event_type, convo_id, user_id, metadata, duration_ms)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    event_type,
                    convo_id,
                    user_id,
                    json.dumps(metadata, default=str) if metadata else None,
                    duration_ms,
                ),
            )
    except Exception as e:
        logger.warning(f"Analytics log error: {e}")
