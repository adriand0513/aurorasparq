# brain/memory/retrieval.py
"""
Smart memory retrieval module.
Retrieves relevant facts + summaries to give Isabella better long-term memory.
"""

import logging
from typing import List, Dict, Optional
from brain.memory.facts import get_relevant_facts
from brain.memory.summaries import get_recent_summaries

logger = logging.getLogger(__name__)


def get_relevant_memories(
    convo_id: str, 
    current_message: str = "", 
    max_facts: int = 6,
    max_summaries: int = 2
) -> str:
    """
    Main function to retrieve relevant memory context.
    Now includes both important facts and recent conversation summaries.
    """
    memory_parts = []

    # === 1. Get Important Facts ===
    try:
        facts = get_relevant_facts(convo_id, limit=max_facts)
        if facts:
            facts_text = "\n".join([f"- {fact}" for fact in facts])
            memory_parts.append(f"**Key facts about the user:**\n{facts_text}")
    except Exception as e:
        logger.error(f"Error retrieving facts: {e}")

    # === 2. Get Recent Conversation Summaries ===
    try:
        summaries = get_recent_summaries(convo_id, limit=max_summaries)
        if summaries:
            summaries_text = "\n\n".join([f"- {s}" for s in summaries])
            memory_parts.append(f"**Recent conversation context:**\n{summaries_text}")
    except Exception as e:
        logger.error(f"Error retrieving summaries: {e}")

    if not memory_parts:
        return ""

    # Combine everything into one clean memory block
    full_memory = "\n\n".join(memory_parts)

    return f"""=== MEMORY CONTEXT ===
{full_memory}
=== END MEMORY CONTEXT ==="""


def get_memory_context_for_prompt(convo_id: str, current_message: str = "") -> str:
    """
    Clean wrapper function used by main.py.
    Returns memory context formatted for prompt injection.
    """
    try:
        memory_context = get_relevant_memories(convo_id, current_message)
        return memory_context
    except Exception as e:
        logger.error(f"get_memory_context_for_prompt error: {e}")
        return ""
