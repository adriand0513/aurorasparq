# postprocess.py - Advanced Repetition Reduction + Natural Flow (Cleaned)
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
    text = re.sub(r"^(Mmm|Hmm|Ahh|Ohh|Well|So|Hey there)\s*", "", text, flags=re.IGNORECASE)

    # === REPETITION REDUCTION ===
    text = reduce_repetition(text)

    # === OPTIONAL LLM REWRITE FOR HIGH REPETITION ===
    if detect_high_repetition(text) and random.random() < 0.25:
        text = rewrite_for_variety(text)

    # === LIGHT HUMANIZING ===
    if len(text) > 110 and random.random() < 0.12:
        text = humanize_text(text)

    # === FINAL CLEANUP (Important) ===
    text = final_cleanup(text)

    return text.strip()


def reduce_repetition(text: str, max_overlap: float = 0.52) -> str:
    """Removes sentences that are too semantically similar to previous ones."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 2:
        return text

    cleaned = []
    seen_word_sets = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        current_words = set(re.findall(r'\b\w+\b', sentence.lower()))
        is_repetitive = False

        for prev_words in seen_word_sets:
            if len(current_words) == 0:
                is_repetitive = True
                break
            overlap = len(current_words & prev_words) / len(current_words)
            if overlap > max_overlap:
                is_repetitive = True
                break

        if not is_repetitive:
            cleaned.append(sentence)
            seen_word_sets.append(current_words)

    if len(cleaned) < max(2, len(sentences) // 2):
        return text

    return " ".join(cleaned)


def detect_high_repetition(text: str) -> bool:
    """Quick check to see if the text still feels repetitive."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 3:
        return False

    word_sets = [set(re.findall(r'\b\w+\b', s.lower())) for s in sentences if s.strip()]
    repetitive_count = 0

    for i in range(1, len(word_sets)):
        overlap = len(word_sets[i] & word_sets[i-1]) / max(len(word_sets[i]), 1)
        if overlap > 0.45:
            repetitive_count += 1

    return repetitive_count >= 2


def rewrite_for_variety(text: str) -> str:
    """Uses LLM to rewrite when repetition is detected."""
    try:
        rewrite_prompt = f"""Rewrite this message to sound more natural and less repetitive.
Keep the same warm, feminine tone. Vary the sentence structure.
Do not add any prefixes like "Natural version" or explanations.

Original: {text}

Rewritten version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": rewrite_prompt}],
                "temperature": 0.75,
                "max_tokens": 350
            },
            timeout=10
        )
        if resp.status_code == 200:
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean any bad prefixes the LLM might have added
            rewritten = re.sub(r'^(Natural version:|Natural Version:|\*\*Natural version:\*\*)', '', rewritten, flags=re.IGNORECASE).strip()
            if 25 < len(rewritten) < len(text) * 1.6:
                return rewritten
    except Exception:
        pass
    return text


def humanize_text(text: str) -> str:
    """Light humanizing for longer replies."""
    try:
        prompt = f"""Rewrite this reply to sound like a real 25-year-old woman texting naturally.
Keep it warm, feminine, and natural. Avoid robotic or repetitive phrasing.
Do not add any prefixes.

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
            # Clean any bad prefixes the LLM might have added
            rewritten = re.sub(r'^(Natural version:|Natural Version:|\*\*Natural version:\*\*)', '', rewritten, flags=re.IGNORECASE).strip()
            if 30 < len(rewritten) < len(text) * 1.5:
                return rewritten
    except:
        pass
    return text


def final_cleanup(text: str) -> str:
    """Final pass to remove any remaining bad prefixes or artifacts."""
    text = text.strip()

    # Remove common bad prefixes that LLMs sometimes add
    text = re.sub(r'^\*\*Natural version:\*\*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^Natural version:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\*\*Natural Version:\*\*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(Natural Version|Natural version):\s*', '', text, flags=re.IGNORECASE)

    # Remove other common LLM artifacts
    text = re.sub(r'^\*\*.*?\*\*:\s*', '', text)
    text = re.sub(r'^(Response|Answer|Reply|Version):\s*', '', text, flags=re.IGNORECASE)

    # Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()
