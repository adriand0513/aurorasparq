# postprocess.py
"""
Post-processing module for Isabella's responses.
Handles cleaning, repetition reduction, and natural message bubble splitting.
"""

import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL


def clean_reply(text: str) -> str:
    """
    Main cleaning and repetition reduction function.
    Runs before splitting into bubbles.
    """
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
    Removes sentences that are too similar within the same reply.
    Helps prevent the model from repeating the same idea multiple times.
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

        # Simple but effective phrase-level deduplication
        key = sentence.lower()[:65]
        if key in seen_phrases:
            continue

        seen_phrases.add(key)
        cleaned.append(sentence)

    return " ".join(cleaned)


def remove_weak_cautious_phrases(text: str) -> str:
    """
    Removes or reduces repetitive cautious/disclaimer language
    that often appears when Isabella is in a guarded emotional state.
    """
    weak_patterns = [
        r"I('m| am) still (guarded|processing|careful|unsure|trying to figure this out).*?[.!?]",
        r"That('s| is) a lot.*?[.!?]",
        r"I need (a second|some time|to think) to (process|catch up|figure this out).*?[.!?]",
        r"I('m| am) not (gonna|going to) lie.*?",
        r"This is (a lot|moving kind of fast).*?[.!?]",
    ]

    for pattern in weak_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Clean up extra spaces left behind
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def lightly_humanize(text: str) -> str:
    """
    Light rewriting using the LLM when the response feels too robotic or repetitive.
    Only triggers occasionally to avoid over-editing.
    """
    try:
        prompt = f"""Rewrite this reply to sound more like a real 25-year-old woman texting naturally.
Keep it warm, feminine, and emotionally honest. Remove repetitive or overly cautious phrasing.
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
    except Exception:
        pass
    return text


def split_into_bubbles(text: str, max_chars: int = 220) -> list:
    """
    Splits cleaned text into natural message bubbles.
    Tries to create human-like message length and pacing.
    """
    if not text:
        return []

    text = text.strip()

    # Split on strong natural boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)

    bubbles = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Start a new bubble if adding this sentence would exceed max length
        if len(current) + len(sentence) + 1 > max_chars and current:
            bubbles.append(current.strip())
            current = sentence
        else:
            if current:
                current += " " + sentence
            else:
                current = sentence

    if current:
        bubbles.append(current.strip())

    # Merge very short bubbles with the previous one when possible
    final_bubbles = []
    for bubble in bubbles:
        if final_bubbles and len(bubble) < 40 and len(final_bubbles[-1]) + len(bubble) < max_chars:
            final_bubbles[-1] += " " + bubble
        else:
            final_bubbles.append(bubble)

    return final_bubbles
