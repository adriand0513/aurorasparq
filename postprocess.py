# postprocess.py - Improved Repetition Reduction + Natural Flow
import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."

    text = text.strip()

    # === BASIC CLEANING ===
    text = re.sub(r'[-—–]', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r"<\|[^>]*\|>", "", text)
    text = re.sub(r"__.*?__", "", text)
    text = re.sub(r'\[.*?]\s*', '', text)
    text = re.sub(r'\*.*?\*', '', text)

    # Remove common weak AI starters
    text = re.sub(r"^(Mmm|Hmm|Ahh|Ohh|Well|So|Hey there|Yeah|Like)\s*", "", text, flags=re.IGNORECASE)

    # === STRONG REPETITION REDUCTION ===
    text = reduce_repetition(text)

    # === AGGRESSIVE PATTERN REDUCTION (New) ===
    text = reduce_repetitive_patterns(text)

    # === LLM REWRITE IF STILL REPETITIVE ===
    if detect_high_repetition(text) and random.random() < 0.30:
        text = rewrite_for_variety(text)

    # === LIGHT HUMANIZING ===
    if len(text) > 100 and random.random() < 0.15:
        text = humanize_text(text)

    return text.strip()


def reduce_repetition(text: str, max_overlap: float = 0.55) -> str:
    """
    Removes sentences that are too semantically or lexically similar to previous ones.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 2:
        return text

    cleaned = []
    seen_word_sets = []

    for sentence in sentences:
        words = set(re.findall(r'\b\w+\b', sentence.lower()))
        if not words:
            continue

        is_repetitive = False
        for prev_words in seen_word_sets:
            overlap = len(words & prev_words) / max(len(words), 1)
            if overlap > max_overlap:
                is_repetitive = True
                break

        if not is_repetitive:
            cleaned.append(sentence)
            seen_word_sets.append(words)

    return " ".join(cleaned)


def reduce_repetitive_patterns(text: str) -> str:
    """
    Reduces common repetitive structures (especially cautious/boundary phrases).
    """
    # Common repetitive cautious patterns
    patterns = [
        r"let'?s (just )?talk first",
        r"we('re| are) (still )?(basically )?strangers",
        r"i (barely|don'?t really) know you",
        r"slow down( a bit)?",
        r"we('ve| have) (barely|only) (said|been talking for)",
        r"let'?s (just )?see what happens( naturally)?",
    ]

    for pattern in patterns:
        # Only keep the first occurrence of these patterns
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if len(matches) > 1:
            for match in matches[1:]:
                text = text[:match.start()] + text[match.end():]

    return text


def detect_high_repetition(text: str) -> bool:
    """Detect if the text still has significant repetition."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 3:
        return False

    word_sets = [set(re.findall(r'\b\w+\b', s.lower())) for s in sentences]
    overlaps = 0
    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            if word_sets[i] and word_sets[j]:
                overlap = len(word_sets[i] & word_sets[j]) / max(len(word_sets[i]), 1)
                if overlap > 0.45:
                    overlaps += 1

    return overlaps >= 2


def rewrite_for_variety(text: str) -> str:
    """Use LLM to rewrite repetitive text with more natural variety."""
    try:
        rewrite_prompt = f"""Rewrite this reply to sound like a real 25-year-old woman texting.
Make it warm, natural, and varied. Avoid repeating similar sentence structures or cautious phrases.
Keep the same meaning and emotional tone.

Original: {text}

Natural version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": rewrite_prompt}],
                "temperature": 0.85,
                "max_tokens": 400
            },
            timeout=12
        )
        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            if 30 < len(rewritten) < len(text) * 1.6:
                return rewritten
    except Exception:
        pass
    return text


def humanize_text(text: str) -> str:
    """Light humanizing for longer replies."""
    try:
        prompt = f"""Rewrite this reply to sound like a real 25-year-old Colombian woman texting naturally.
Keep it warm, feminine, and conversational. Avoid robotic phrasing.

Original: {text}

Natural version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.78,
                "max_tokens": 350
            },
            timeout=10
        )
        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            if 35 < len(rewritten) < len(text) * 1.5:
                return rewritten
    except:
        pass
    return text
