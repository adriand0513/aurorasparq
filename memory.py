# memory.py
"""
Chat history (short-term memory).
Long-term memory (facts, relationship state) lives in aurorasparq_brain/.
"""

import logging
from typing import Optional

from database import db_cursor

logger = logging.getLogger(__name__)

VOICE_NOTE_PREFIX = "[voice_note]|"
VOICE_SCRIPT_PREFIX = "[voice_script]|"


def get_history(convo_id: str, limit: Optional[int] = None) -> list:
    """Messages for a conversation, oldest first. limit=None returns all."""
    with db_cursor() as cur:
        if limit is None:
            cur.execute(
                """
                SELECT role, content, timestamp FROM chat_history
                WHERE convo_id = %s ORDER BY timestamp ASC, id ASC
                """,
                (convo_id,),
            )
            rows = cur.fetchall()
        else:
            cur.execute(
                """
                SELECT role, content, timestamp FROM chat_history
                WHERE convo_id = %s ORDER BY timestamp DESC, id DESC LIMIT %s
                """,
                (convo_id, limit),
            )
            rows = list(reversed(cur.fetchall()))
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


def count_user_messages_today(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM chat_history
            WHERE user_id = %s AND role = 'user' AND timestamp >= CURRENT_DATE
            """,
            (user_id,),
        )
        return cur.fetchone()[0]


def save_message(convo_id: str, message: dict, user_id: Optional[int] = None) -> None:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO chat_history (convo_id, user_id, role, content) VALUES (%s, %s, %s, %s)",
                (convo_id, user_id, message["role"], message["content"]),
            )
    except Exception as e:
        logger.error(f"save_message error: {e}")


def get_recent_text_messages(convo_id: str, limit: int = 30) -> list:
    """Last N user/assistant text messages. Voice scripts appear as what she said out loud."""
    out = []
    for m in get_history(convo_id, limit=limit * 3):
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content or role not in ("user", "assistant"):
            continue
        if content.startswith(VOICE_NOTE_PREFIX):
            continue
        if content.startswith(VOICE_SCRIPT_PREFIX):
            script = content[len(VOICE_SCRIPT_PREFIX):].strip()
            if script:
                out.append({"role": "assistant", "content": script})
            continue
        out.append({"role": role, "content": content})
    return out[-limit:]


def set_last_voice_script(convo_id: str, script: str, user_id: Optional[int] = None) -> None:
    """Persist what she actually said in the last voice note."""
    if not script or len(script) < 8:
        return
    save_message(convo_id, {"role": "assistant", "content": f"{VOICE_SCRIPT_PREFIX}{script[:500]}"}, user_id=user_id)


def get_last_voice_script(convo_id: str) -> str:
    for m in reversed(get_history(convo_id, limit=30)):
        content = m.get("content") or ""
        if content.startswith(VOICE_SCRIPT_PREFIX):
            return content[len(VOICE_SCRIPT_PREFIX):].strip()
    return ""
