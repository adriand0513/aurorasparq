# postprocess.py - Stronger Repetition Reduction + Natural Flow
import re
import random
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL


def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."

    text = text.strip()

    # === BASIC CLEANING ===
    text = re.sub(r'[-—–]', ' ', text)           # Remove dashes
    text = re.sub(r'\s{2,}', ' ', text)          # Clean extra spaces
    text = re.sub(r"<\|[^>]*\|>", "", text)      # Remove special tokens
    text = re.sub(r"__.*?__", "", text)
    text = re.sub(r'\[.*?]\s*', '', text)
    text = re.sub(r'\*.*?\*', '', text)

    # Remove common AI starter phrases
    text = re.sub(r"^(Mmm|Hmm|Ahh|Ohh|Well|So|Hey there)\s*", "", text, flags=re.IGNORECASE)

    # === REPETITION REDUCTION (Stronger Version) ===
    text = reduce_repetition(text)

    # === LIGHT HUMANIZING (only on longer replies) ===
    if len(text) > 120 and random.random() < 0.15:
        text = humanize_text(text)

    return text.strip()


def reduce_repetition(text: str, max_overlap: float = 0.55) -> str:
    """
    Reduces repetition by removing sentences that are too similar 
    to previously seen sentences in the same reply.
    """
    if not text:
        return text

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 2:
        return text

    cleaned_sentences = []
    seen_word_sets = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Get set of words in current sentence
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
            cleaned_sentences.append(sentence)
            seen_word_sets.append(current_words)

    # Safety fallback: if too much was removed, return original
    if len(cleaned_sentences) < max(2, len(sentences) // 2):
        return text

    return " ".join(cleaned_sentences)


def humanize_text(text: str) -> str:
    """
    Occasionally rewrites longer replies to sound more natural.
    """
    try:
        humanize_prompt = f"""Rewrite this reply to sound like a real 25-year-old woman texting naturally.
Keep it warm, feminine, and slightly seductive. Avoid sounding robotic or repetitive.
Do not add any explanations or prefixes.

Original: {text}
Natural version:"""

        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": humanize_prompt}],
                "temperature": 0.75,
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
