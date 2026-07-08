# brain/memory/retrieval.py
"""
Smart memory retrieval module.
Retrieves the most relevant facts and summaries based on the current conversation.
"""

import logging
import re
from datetime import datetime, timedelta
from brain.memory.facts import get_relevant_facts
from brain.memory.summaries import get_recent_summaries

logger = logging.getLogger(__name__)


def _calculate_relevance_score(text: str, query: str) -> float:
    """Simple keyword-based relevance scoring."""
    if not query:
        return 0.5
    text_lower = text.lower()
    query_words = set(re.findall(r'\b\w+\b', query.lower()))
    if not query_words:
        return 0.5

    matches = sum(1 for word in query_words if word in text_lower)
    return matches / len(query_words)


def get_relevant_memories(
    convo_id: str,
    current_message: str = "",
    max_facts: int = 6,
    max_summaries: int = 2,
    max_total_chars: int = 1200
) -> str:
    """
    Smart memory retrieval.
    Scores facts by importance + relevance to current message.
    """
    memory_parts = []

    # === 1. Get Facts with Relevance Scoring ===
    try:
        facts = get_relevant_facts(convo_id, limit=max_facts * 2)  # Get more to filter

        if facts:
            scored_facts = []
            for fact in facts:
                relevance = _calculate_relevance_score(fact, current_message)
                # Combine importance (we assume higher importance facts come first) + relevance
                score = (0.6 * 0.8) + (0.4 * relevance)  # Simple weighted score
                scored_facts.append((fact, score))

            # Sort by score descending
            scored_facts.sort(key=lambda x: x[1], reverse=True)
            top_facts = [fact for fact, score in scored_facts[:max_facts]]

            if top_facts:
                facts_text = "\n".join([f"- {fact}" for fact in top_facts])
                memory_parts.append(f"**Relevant facts about the user:**\n{facts_text}")
    except Exception as e:
        logger.error(f"Error retrieving facts: {e}")

    # === 2. Get Recent Summaries ===
    try:
        summaries = get_recent_summaries(convo_id, limit=max_summaries)
        if summaries:
            summaries_text = "\n\n".join([f"- {s}" for s in summaries])
            memory_parts.append(f"**Recent conversation context:**\n{summaries_text}")
    except Exception as e:
        logger.error(f"Error retrieving summaries: {e}")

    if not memory_parts:
        return ""

    full_memory = "\n\n".join(memory_parts)

    # Truncate if too long
    if len(full_memory) > max_total_chars:
        full_memory = full_memory[:max_total_chars] + "..."

    return f"""=== MEMORY CONTEXT ===
{full_memory}
=== END MEMORY CONTEXT ==="""


def get_memory_context_for_prompt(convo_id: str, current_message: str = "") -> str:
    """Wrapper used by main.py"""
    try:
        return get_relevant_memories(convo_id, current_message)
    except Exception as e:
        logger.error(f"get_memory_context_for_prompt error: {e}")
        return ""
