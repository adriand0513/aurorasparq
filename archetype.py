# archetype.py
from typing import Dict, Optional
import json

ARCHETYPES = {
    "romantic_dreamer": "Romantic Dreamer - seeks emotional depth and fantasy romance",
    "lonely_professional": "Lonely Professional - successful but emotionally isolated",
    "flirty_player": "Flirty Player - enjoys teasing and sexual banter",
    "curious_explorer": "Curious Explorer - wants to explore fantasies and kinks",
    "emotional_support": "Emotional Support Seeker - needs listening and comfort",
    "dominant_alpha": "Dominant Alpha - enjoys control and power dynamics",
    "shy_introvert": "Shy Introvert - building confidence through safe interaction",
    "married_attached": "Married/Attached - seeking discreet excitement",
    "high_achiever": "High-Achiever Burnout - wants admiration and relaxation",
    "kink_enthusiast": "Kink Enthusiast - focused on specific fetishes",
    "spiritual_deep": "Spiritual Deep Thinker - wants soulful + sensual connection",
    "young_inexperienced": "Young & Inexperienced - learning how to flirt",
    "older_gentleman": "Older Gentleman - classy and experienced",
    "humor_banter": "Humor & Banter Guy - playful and light-hearted"
}

async def detect_archetype(convo_id: str, history) -> Dict:
    """Use LLM to detect user's archetype based on conversation"""
    if len(history) < 4:
        return {"archetype": "new_user", "confidence": 0.4}

    recent_chat = "\n".join([
        f"{msg['role']}: {msg['content']}" 
        for msg in history[-12:]
    ])

    prompt = f"""You are an expert behavioral analyst.
Analyze the user's messages and determine which archetype best fits.

User messages so far:
{recent_chat}

Possible archetypes: {list(ARCHETYPES.values())}

Respond in valid JSON only:
{{
  "archetype": "exact_key_from_list_or_new",
  "confidence": 0.85,
  "summary": "Short description of why",
  "primary_motivation": "What he seems to want from Isabella"
}}"""

    # Call Grok for classification
    try:
        from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL
        import requests

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300
            },
            timeout=8
        )
        result = resp.json()["choices"][0]["message"]["content"].strip()
        data = json.loads(result)
        return data
    except:
        # Fallback
        return {"archetype": "unknown", "confidence": 0.5, "summary": "Could not classify"}