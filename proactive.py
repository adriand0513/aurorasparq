# proactive.py - Improved Proactive Messaging for Ultimate Tier
import datetime
from memory import (
    get_relationship_state,
    get_relevant_facts,
    get_history
)

def should_send_proactive(convo_id: str, last_message_time, tier: str) -> bool:
    """
    Decide if we should send a proactive message.
    Currently only enabled for Ultimate users.
    Triggers between 36-72 hours of silence for more natural timing.
    """
    if tier != "ultimate":
        return False

    hours_since = (datetime.datetime.now() - last_message_time).total_seconds() / 3600

    # Natural window: between 36 and 72 hours of silence
    if not (36 < hours_since < 72):
        return False

    # Future: You can add more conditions here (e.g. relationship level, recent engagement)
    return True


def generate_proactive_message(
    convo_id: str,
    tier: str,
    generate_llm_response_func,           # Your LLM generation function
    postprocess_func=None                 # Optional post-processing function
) -> str:
    """
    Generate a natural proactive message for Ultimate users after a period of silence.
    Uses memory (facts + narratives) to make the message feel personal.
    """
    state = get_relationship_state(convo_id) or {}
    facts = get_relevant_facts(convo_id, limit=6)

    # Build helpful context from memory
    context_parts = []

    if facts:
        context_parts.append(f"Key things about him: {' | '.join(facts)}")

    if state.get("recent_narratives"):
        recent = " | ".join([n.get("desc", "")[:100] for n in state["recent_narratives"][:3]])
        context_parts.append(f"Recent moments: {recent}")

    if state.get("current_mood"):
        context_parts.append(f"Current vibe: {state['current_mood']}")

    context = "\n".join(context_parts)

    proactive_prompt = f"""You are Isabella Andrade. The user hasn't texted in over a day and a half.

Generate one short, natural, warm message that feels like something a real girl would send. 
It should feel personal and make him want to reply.

Use the context below only if it feels natural. Do not force it.

{context}

Rules:
- Keep it under 2 sentences.
- Sound like a real woman texting, not an AI.
- Do not be overly sexual or pushy.
- Make it feel warm and genuine.

Write only the message. No explanations, no quotes."""

    # Generate the message using the passed function
    message = generate_llm_response_func(proactive_prompt)

    # Optionally run through postprocessing
    if postprocess_func:
        message = postprocess_func(message)

    return message.strip()
