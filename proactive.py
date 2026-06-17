# proactive.py - Improved Version for Ultimate Tier
import datetime
from memory import (
    get_relationship_state,
    get_relevant_facts,
    get_history
)
from prompt import get_system_prompt

def should_send_proactive(convo_id: str, last_message_time, tier: str) -> bool:
    """
    Decide whether to send a proactive message.
    Currently only enabled for Ultimate users.
    """
    if tier != "ultimate":
        return False

    hours_since = (datetime.datetime.now() - last_message_time).total_seconds() / 3600

    # Only trigger between 36–72 hours of silence (more natural window)
    if not (36 < hours_since < 72):
        return False

    # Optional: Add more conditions here later (e.g. relationship level, recent activity)
    return True


def generate_proactive_message(convo_id: str, tier: str) -> str:
    """
    Generate a natural proactive message using memory + relationship state.
    """
    state = get_relationship_state(convo_id) or {}
    facts = get_relevant_facts(convo_id, limit=6)
    recent_history = get_history(convo_id, limit=8)

    # Build context
    context = ""
    if facts:
        context += f"\nKey things I know about him: {' | '.join(facts)}"
    if state.get("recent_narratives"):
        recent = " | ".join([n.get("desc", "") for n in state["recent_narratives"][:3]])
        context += f"\nRecent moments: {recent}"

    proactive_prompt = f"""You are Isabella. The user hasn't texted in over a day and a half.

Generate a short, natural, warm message that feels like something a real girl would send. 
It should feel personal, slightly playful or flirty, and make him want to reply.

Use the context below naturally if it fits. Do not force it.

{context}

Write only the message (no explanations, no quotes). Keep it under 2 sentences."""

    # Call your existing LLM function
    message = generate_llm_response(proactive_prompt)  # your function
    return message.strip()
