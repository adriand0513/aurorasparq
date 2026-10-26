# brain/memory/summaries.py
"""
Long-range memory: a running "story so far" for each conversation.

The prompt always carries the most recent messages word for word. Everything
older than that is folded, in batches, into one summary that keeps the
details a person would remember: names, events, plans, promises, inside
jokes, what he likes and dislikes, and how things between them went.
"""

import logging

from database import db_cursor
from llm import complete_prompt

logger = logging.getLogger(__name__)

RECENT_WINDOW = 30        # newest messages that stay verbatim in the prompt (never summarized yet)
SUMMARY_BATCH = 20        # fold older messages in once at least this many are waiting
MAX_SUMMARY_WORDS = 900

SUMMARY_PROMPT = """You keep the long-term memory for Isabella, a companion character, about one man she talks to.

Below is her current memory of their conversations so far, then newer messages that happened after it.
Rewrite the memory so it includes everything important from both.

Keep, in order of importance:
- Facts about him: name, job, city, family, friends, pets, goals, health, routines, likes and dislikes
- Events and plans he mentioned (with dates or days when given) and how they turned out
- Promises either of them made, things she said she would do, questions left open
- Inside jokes, nicknames, recurring topics, things that made him happy or upset
- What Isabella told him about her own life, so she never contradicts herself
- How the connection between them has developed

Rules:
- Plain sentences grouped under short headings. No quotes from the chat.
- Never drop an older detail unless the new messages correct it.
- At most {max_words} words.

CURRENT MEMORY:
{summary}

NEWER MESSAGES:
{messages}

UPDATED MEMORY:"""


def get_conversation_summary(convo_id: str) -> str:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT summary FROM conversation_memory WHERE convo_id = %s", (convo_id,))
            row = cur.fetchone()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        logger.warning(f"Could not load conversation memory: {e}")
        return ""


def update_conversation_summary(convo_id: str) -> bool:
    """Fold older messages into the summary when a full batch is waiting. Returns True if updated."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT summary, last_message_id FROM conversation_memory WHERE convo_id = %s",
            (convo_id,),
        )
        row = cur.fetchone()
        summary, last_id = (row[0], row[1]) if row else ("", 0)

        # Messages after the last summarized one, excluding the newest RECENT_WINDOW
        cur.execute(
            """
            SELECT id, role, content FROM chat_history
            WHERE convo_id = %s AND id > %s
            ORDER BY id ASC
            """,
            (convo_id, last_id),
        )
        older = cur.fetchall()[:-RECENT_WINDOW]

    # Voice-note URL rows carry no meaning; voice scripts are what she said out loud
    pending = [r for r in older if not r[2].startswith("[voice_note]|")]
    if len(pending) < SUMMARY_BATCH:
        return False

    lines = []
    for _id, role, content in pending:
        if content.startswith("[voice_script]|"):
            content = "(voice note) " + content.split("|", 1)[1]
        speaker = "Him" if role == "user" else "Isabella"
        lines.append(f"{speaker}: {content[:600]}")

    new_summary = complete_prompt(
        SUMMARY_PROMPT.format(
            summary=summary or "(nothing yet)",
            messages="\n".join(lines),
            max_words=MAX_SUMMARY_WORDS,
        ),
        temperature=0.2,
        max_tokens=1600,
    ).strip()
    if not new_summary:
        return False  # LLM failed; try again next turn, nothing is lost

    newest_id = older[-1][0]
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO conversation_memory (convo_id, summary, last_message_id, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (convo_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                last_message_id = EXCLUDED.last_message_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (convo_id, new_summary, newest_id),
        )
    logger.info(f"🧠 Conversation memory updated | convo={convo_id} | folded={len(pending)} msgs")
    return True
