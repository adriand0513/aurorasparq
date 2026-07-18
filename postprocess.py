# postprocess.py
import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."

    text = text.strip()

    # === Basic Cleaning ===
    text = re.sub(r'[-—–]', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r"<\|[^>]*\|>", "", text)
    text = re.sub(r"__.*?__", "", text)
    text = re.sub(r'\[.*?]\s*', '', text)
    text = re.sub(r'\*.*?\*', '', text)

    # Remove common weak AI starters
    text = re.sub(r"^(Mmm|Hmm|Ahh|Ohh|Well|So|Hey there|I mean)\s*", "", text, flags=re.IGNORECASE)

    # === Intra-Reply Repetition Reduction ===
    text = reduce_intra_reply_repetition(text)

    # === Remove Weak / Repetitive Cautious Phrases ===
    text = remove_weak_cautious_phrases(text)

    # === Optional Light Humanizing ===
    if len(text) > 90 and random.random() < 0.15:
        text = lightly_humanize(text)

    return text.strip()


def reduce_intra_reply_repetition(text: str) -> str:
    """
    Removes or merges sentences that are too semantically similar within the same reply.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 2:
        return text

    cleaned = []
    seen_phrases = set()

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Simple phrase-level dedup
        key = sentence.lower()[:60]
        if key in seen_phrases:
            continue

        seen_phrases.add(key)
        cleaned.append(sentence)

    return " ".join(cleaned)


def remove_weak_cautious_phrases(text: str) -> str:
    """
    Removes or softens repetitive cautious/disclaimer phrases that appear too often.
    """
    weak_patterns = [
        r"I('m| am) still (guarded|processing|careful|unsure).*?[.!?]",
        r"That('s| is) a lot.*?[.!?]",
        r"I need (a second|some time) to (process|catch up).*?[.!?]",
        r"I('m| am) not (gonna|going to) lie.*?",
    ]

    for pattern in weak_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Clean up extra spaces after removals
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def lightly_humanize(text: str) -> str:
    """Light rewriting to sound more natural (only when needed)."""
    try:
        prompt = f"""Rewrite this reply to sound more like a real 25-year-old woman texting naturally.
Keep it warm and feminine. Remove any repetitive or overly cautious phrasing.
Original: {text}
Natural version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 300
            },
            timeout=8
        )
        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            if 30 < len(rewritten) < len(text) * 1.4:
                return rewritten
    except:
        pass
    return text
