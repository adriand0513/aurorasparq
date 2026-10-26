# llm.py
"""One place that talks to the xAI chat completions API."""

import logging

import requests

from config import XAI_API_BASE, XAI_API_KEY, XAI_MODEL

logger = logging.getLogger(__name__)


def chat_completion(
    messages: list,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: int = 60,
) -> str:
    """Return the model's reply text. Raises on HTTP or format errors."""
    resp = requests.post(
        XAI_API_BASE,
        headers={
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": XAI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete_prompt(prompt: str, temperature: float = 0.4, max_tokens: int = 1200) -> str:
    """Single user-turn prompt. Returns "" instead of raising (for background work)."""
    try:
        return chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return ""
