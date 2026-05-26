# postprocess.py - Clean, Natural, and Safe
import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."

    text = text.strip()

    # Remove common AI artifacts
    text = re.sub(r"<\|[^>]*\|>", "", text)
    text = re.sub(r"__.*?__", "", text)
    text = re.sub(r'\[.*?]\s*', '', text)
    text = re.sub(r'\*.*?\*', '', text)
    text = re.sub(r'[-—–]{2,}', ' ', text)      # Remove excessive dashes
    text = re.sub(r'\s{2,}', ' ', text)

    # Remove dangerous or AI-revealing starters
    text = re.sub(r"^(Mmm|Hmm|Ahh|Ohh|Well|So|Hey there)\s*", "", text, flags=re.IGNORECASE)

    # Smart LLM Safety + Humanizing Pass
    try:
        safety_prompt = f"""Rewrite this message from Isabella to be natural, classy, seductive, and human.

Rules:
- Never mention being an AI, chatbot, or virtual anything.
- Never offer calls, meetings, or real-life contact.
- Keep her warm, slightly flirty, and real.
- Remove any awkward phrasing or instructions.

Original: {text}

Just return the clean, natural version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": safety_prompt}],
                "temperature": 0.7,
                "max_tokens": 280
            },
            timeout=8
        )

        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            if 20 < len(rewritten) < len(text) * 1.35:
                text = rewritten
    except:
        pass  # Fail silently, use original text

    # Light human touch
    if random.random() < 0.15 and not text.endswith(('...', '.', '!', '?')):
        text += random.choice([' …', ' haha'])

    return text.strip()
