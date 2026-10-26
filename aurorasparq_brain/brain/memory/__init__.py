# brain/memory/__init__.py
"""Long-term fact memory for Isabella's Second Brain."""

from .facts import (
    add_fact,
    extract_facts_from_exchange,
    get_facts_for_prompt,
    get_or_set_sticky_activity,
)

__all__ = [
    "add_fact",
    "get_facts_for_prompt",
    "extract_facts_from_exchange",
    "get_or_set_sticky_activity",
]
