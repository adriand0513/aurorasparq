# postprocess.py - Fluid Safety + No Excessive Dashes
import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."

    text = text.strip()

    # Remove excessive dashes (common AI pattern)
    text = re.sub(r'[-—–]{2,}', ' ', text)   # Replace multiple dashes with space
    text = re.sub(r'\s*-\s*', ' ', text)     # Remove single dashes with spaces around them

    # Light general cleanup
    text = re.sub(r"<\|[^>]*\|>", "", text)
    text = re.sub(r"__.*?__", "", text)
    text = re.sub(r'\s{2,}', ' ', text)

    # Smart LLM Safety Layer (Context-Aware)
    try:
        safety_prompt = f"""Rewrite this message from Isabella to be safe, natural, and seductive.

Rules:
- Never offer calls, FaceTime, meetings, or real-life contact.
- Never reveal she's an AI.
- Keep her classy, warm, and flirty.
- Remove any dashes (-) if they make it sound unnatural.

Original: {text}

Rewritten version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": safety_prompt}],
                "temperature": 0.68,
                "max_tokens": 280
            },
            timeout=7
        )

        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            if 20 < len(rewritten) < len(text) * 1.4:
                text = rewritten
    except:
        pass

    # Final light human touch
    if random.random() < 0.12 and not text.endswith(('...', '.', '!', '?')):
        text += random.choice([' …', ' haha'])

    return text.strip()
