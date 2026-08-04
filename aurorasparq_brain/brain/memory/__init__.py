# brain/memory/__init__.py
"""
Memory System for Isabella's Second Brain.
Handles facts, sticky activity, retrieval, and conversation summaries.
"""

from .facts import (
    add_fact,
    get_facts_for_prompt,
    extract_facts_from_exchange,
    get_or_set_sticky_activity,
)

# Optional / older modules — keep if these files still exist
try:
    from .retrieval import (
        get_relevant_memories,
        get_memory_context_for_prompt,
    )
except ImportError:
    get_relevant_memories = None
    get_memory_context_for_prompt = None

try:
    from .summaries import (
        generate_and_save_summary,
        get_recent_summaries,
    )
except ImportError:
    generate_and_save_summary = None
    get_recent_summaries = None

__all__ = [
    # Facts (current)
    "add_fact",
    "get_facts_for_prompt",
    "extract_facts_from_exchange",
    "get_or_set_sticky_activity",
    # Retrieval
    "get_relevant_memories",
    "get_memory_context_for_prompt",
    # Summaries
    "generate_and_save_summary",
    "get_recent_summaries",
]
