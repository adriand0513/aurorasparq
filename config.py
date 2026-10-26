# config.py
"""All settings come from environment variables (.env locally, Render dashboard in production)."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Database (PostgreSQL only) ──────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

# ── xAI (chat + memory + reflection) ────────────────────────
XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_API_BASE = os.getenv("XAI_API_BASE", "https://api.x.ai/v1/chat/completions")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.20")
XAI_TEMPERATURE = float(os.getenv("XAI_TEMPERATURE", "0.84"))
XAI_MAX_TOKENS = int(os.getenv("XAI_MAX_TOKENS", "1024"))

# ── ElevenLabs (voice notes) ────────────────────────────────
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")
# Render persistent disk. Falls back to a local folder when the disk is not mounted.
AUDIO_DIR = os.getenv("AUDIO_DIR", "/var/data/audio")

# ── Auth ────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# ── Stripe ──────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# ── Site ────────────────────────────────────────────────────
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://www.aurorasparq.com").rstrip("/")

# ── Plans ───────────────────────────────────────────────────
FREE_DAILY_MESSAGE_LIMIT = int(os.getenv("FREE_DAILY_MESSAGE_LIMIT", "5"))
PAID_TIERS = {"premium", "ultimate"}

# ── Required settings ───────────────────────────────────────
_missing = [
    name for name, value in {
        "DATABASE_URL": DATABASE_URL,
        "XAI_API_KEY": XAI_API_KEY,
        "JWT_SECRET": JWT_SECRET,
    }.items() if not value
]
if _missing:
    raise ValueError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        "Login and chat will not work without them."
    )

for _name, _value in {
    "STRIPE_SECRET_KEY": STRIPE_SECRET_KEY,
    "STRIPE_WEBHOOK_SECRET": STRIPE_WEBHOOK_SECRET,
    "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
    "ELEVENLABS_VOICE_ID": ELEVENLABS_VOICE_ID,
}.items():
    if not _value:
        logger.warning(f"{_name} is not set; the feature that needs it is disabled")
