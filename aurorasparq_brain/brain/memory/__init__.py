# brain/memory/__init__.py
"""Long-term fact memory for Isabella's Second Brain."""

from .facts import (
    add_fact,
    extract_facts_from_exchange,
    get_facts_for_prompt,
    get_or_set_sticky_activity,
)
from .summaries import get_conversation_summary, update_conversation_summary

__all__ = [
    "get_conversation_summary",
    "update_conversation_summary",
    "add_fact",
    "get_facts_for_prompt",
    "extract_facts_from_exchange",
    "get_or_set_sticky_activity",
]
