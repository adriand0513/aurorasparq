# brain/memory/retrieval.py
"""
Smart Memory Retrieval for Isabella.
Scores facts using Importance + Recency + Relevance.
"""

import logging
import re
from datetime import datetime, timezone
from brain.memory.facts import get_relevant_facts
from brain.memory.summaries import get_recent_summaries

logger = logging.getLogger(__name__)


def _calculate_relevance_score(text: str, query: str) -> float:
    """Keyword-based relevance between 0 and 1."""
    if not query or not text:
        return 0.0
    text_lower = text.lower()
    query_words = set(re.findall(r'\b\w+\b', query.lower()))
    if not query_words:
        return 0.0
    matches = sum(1 for word in query_words if word in text_lower)
    return min(matches / len(query_words), 1.0)


def _calculate_recency_score(last_recalled) -> float:
    """Higher score for more recently recalled/updated facts."""
    if not last_recalled:
        return 0.3  # Default for facts never recalled

    try:
        if isinstance(last_recalled, str):
            last_recalled = datetime.fromisoformat(last_recalled.replace("Z", "+00:00"))

        now = datetime.now(timezone.utc)
        days_since = (now - last_recalled).days

        if days_since <= 1:
            return 1.0
        elif days_since <= 3:
            return 0.85
        elif days_since <= 7:
            return 0.7
        elif days_since <= 14:
            return 0.5
        else:
            return 0.3
    except:
        return 0.4


def get_relevant_memories(
    convo_id: str,
    current_message: str = "",
    max_facts: int = 6,
    max_summaries: int = 2,
    max_total_chars: int = 1100
) -> str:
    """
    Retrieves the most relevant memories using a composite score:
    Importance + Recency + Relevance to current message.
    """
    memory_parts = []

    # === 1. Get Facts with Smart Scoring ===
    try:
        facts_raw = get_relevant_facts(convo_id, limit=max_facts * 2)

        if facts_raw:
            scored_facts = []
            for fact in facts_raw:
                relevance = _calculate_relevance_score(fact, current_message)
                # For now we use a simple importance assumption.
                # Later we can store importance per fact in DB.
                importance = 7  # Default importance
                recency = _calculate_recency_score(None)  # Can be improved if we store timestamps

                # Composite Score
                score = (importance * 0.35) + (recency * 0.35) + (relevance * 0.30)
                scored_facts.append((fact, score))

            # Sort by score and take top results
            scored_facts.sort(key=lambda x: x[1], reverse=True)
            top_facts = [fact for fact, score in scored_facts[:max_facts]]

            if top_facts:
                facts_text = "\n".join([f"- {fact}" for fact in top_facts])
                memory_parts.append(f"**Key things I remember about you:**\n{facts_text}")

    except Exception as e:
        logger.error(f"Error retrieving facts: {e}")

    # === 2. Get Recent Summaries ===
    try:
        summaries = get_recent_summaries(convo_id, limit=max_summaries)
        if summaries:
            summaries_text = "\n\n".join([f"- {s}" for s in summaries])
            memory_parts.append(f"**Recent context from our conversations:**\n{summaries_text}")
    except Exception as e:
        logger.error(f"Error retrieving summaries: {e}")

    if not memory_parts:
        return ""

    full_memory = "\n\n".join(memory_parts)

    # Safety truncate
    if len(full_memory) > max_total_chars:
        full_memory = full_memory[:max_total_chars] + "..."

    return f"""=== WHAT I REMEMBER ===
{full_memory}
=== END MEMORY ==="""


def get_memory_context_for_prompt(convo_id: str, current_message: str = "") -> str:
    """Main function called from main.py"""
    try:
        return get_relevant_memories(convo_id, current_message)
    except Exception as e:
        logger.error(f"get_memory_context_for_prompt error: {e}")
        return ""
