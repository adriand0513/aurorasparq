# brain/memory/__init__.py
"""
Memory System for Isabella's Second Brain.
This module handles facts, retrieval, and conversation summaries.
"""

from .facts import (
    extract_and_save_facts,
    get_relevant_facts
)

from .retrieval import (
    get_relevant_memories,
    get_memory_context_for_prompt
)

from .summaries import (
    generate_and_save_summary,
    get_recent_summaries
)

__all__ = [
    # Facts
    "extract_and_save_facts",
    "get_relevant_facts",
    # Retrieval
    "get_relevant_memories",
    "get_memory_context_for_prompt",
    # Summaries
    "generate_and_save_summary",
    "get_recent_summaries",
]
