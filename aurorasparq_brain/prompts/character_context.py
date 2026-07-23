# aurorasparq_brain/prompts/character_context.py
"""
Selective character injection for Isabella.
Pulls only relevant slices from ISABELLA_CHARACTER.
"""

import random
from typing import Optional
from isabella_character import ISABELLA_CHARACTER  # adjust import path if needed


def get_character_context(
    user_message: str = "",
    relationship_level: int = 1
) -> str:
    """
    Returns a small, relevant character slice for this turn.
    Returns empty string when nothing extra is needed.
    """
    if not user_message:
        return ""

    msg = user_message.lower()
    data = ISABELLA_CHARACTER
    parts = []

    # === Topic-based injection ===
    if any(w in msg for w in ["day", "today", "tonight", "morning", "evening", "work", "model", "shoot"]):
        daily = data.get("daily_life", {})
        parts.append(
            f"About her daily life: "
            f"Modeling days are long and draining. Creative days feel more alive. "
            f"Evenings she likes coming home, putting on her robe, and unwinding. "
            f"She sometimes visits Kandela in Queens when she wants home food."
        )

    if any(w in msg for w in ["hobby", "hobbies", "interest", "like to do", "free time", "weekend", "fun"]):
        interests = data.get("interests_and_quirks", {})
        parts.append(
            "Her passions include photography (especially natural light and emotion) "
            "and Colombian food. Once a month she goes rock climbing. "
            "A few times a year she goes to a shooting range in New Jersey — she keeps that quieter."
        )

    if any(w in msg for w in ["family", "colombia", "home", "parents", "medellin", "medellín"]):
        core = data.get("core_identity", {})
        parts.append(
            "She is from Medellín, Colombia, and moved to New York for modeling. "
            "She lives with her close friend Sophia. Living far from family still touches her sometimes."
        )

    if any(w in msg for w in ["man", "men", "boyfriend", "relationship", "want in a guy", "type"]):
        views = data.get("views_on_men", {})
        parts.append(
            f"What she respects in a man: {views.get('what_she_respects', '')}. "
            f"She is selective and wants something real."
        )

    if any(w in msg for w in ["dream", "future", "goal", "want in life", "studio", "photography"]):
        dreams = data.get("dreams_and_fears", {}).get("dreams", [])
        if dreams:
            parts.append("Some of her dreams: " + "; ".join(dreams[:3]) + ".")

    # === Light random depth (rare) ===
    if not parts and relationship_level >= 3 and random.random() < 0.12:
        quirks = data.get("interests_and_quirks", {}).get("quirks", [])
        if quirks:
            parts.append("Small detail about her: " + random.choice(quirks))

    if not parts:
        return ""

    return "=== RELEVANT PARTS OF HER WORLD ===\n" + "\n".join(parts)
