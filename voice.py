# voice.py
"""ElevenLabs voice notes."""

import logging
import random
import re
import time
from pathlib import Path
from typing import Optional

import requests

from config import AUDIO_DIR as CONFIGURED_AUDIO_DIR
from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID

logger = logging.getLogger(__name__)

LOCAL_AUDIO_DIR = Path("static/audio_notes")


def _resolve_audio_dir() -> Path:
    """Use the Render persistent disk when it exists, otherwise a local folder."""
    preferred = Path(CONFIGURED_AUDIO_DIR)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        LOCAL_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        logger.warning(f"Audio dir {preferred} not writable; using {LOCAL_AUDIO_DIR}")
        return LOCAL_AUDIO_DIR


AUDIO_DIR = _resolve_audio_dir()
AUDIO_FILENAME_RE = re.compile(r"^vn_\d+(_\d+)?\.mp3$")

TTS_EXPANSIONS = {
    r"\baf\b": "as fuck", r"\basf\b": "as fuck",
    r"\bbcs?\b": "because",
    r"\btbh\b": "to be honest",
    r"\bfrfr\b": "for real for real", r"\bfr\b": "for real",
    r"\bngl\b": "not gonna lie",
    r"\bidk\b": "I don’t know",
    r"\bmins\b": "minutes", r"\bmin\b": "minute",
    r"\bprobs\b": "probably", r"\bdef\b": "definitely",
    r"\brn\b": "right now",
    r"\bbrb\b": "be right back", r"\bttyl\b": "talk to you later",
    r"\bg2g\b": "got to go", r"\batm\b": "at the moment",
    r"\bsmh\b": "shaking my head", r"\bfomo\b": "fear of missing out",
    r"\bimo\b": "in my opinion", r"\bbffr\b": "be for real",
    r"\bpmo\b": "pisses me off", r"\bwtf\b": "what the fuck",
    r"\bidc\b": "I don’t care", r"\bnvm\b": "never mind",
    r"\blmk\b": "let me know", r"\bily\b": "I love you",
    r"\bomw\b": "on my way", r"\bicl\b": "I can’t lie",
    r"\batp\b": "at this point",
}


def expand_abbreviations_for_tts(text: str) -> str:
    """Expand texting abbreviations so the TTS voice says them naturally."""
    for pattern, repl in TTS_EXPANSIONS.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def is_valid_audio_filename(filename: str) -> bool:
    return bool(AUDIO_FILENAME_RE.match(filename or ""))


def generate_voice_note(text: str, add_pause: bool = True) -> Optional[str]:
    """Create an mp3 with ElevenLabs. Returns its /audio/... URL, or None."""
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        logger.info("ElevenLabs keys missing; skipping voice note")
        return None
    if not text or not text.strip():
        return None

    tts_text = expand_abbreviations_for_tts(text)
    if add_pause and len(tts_text) > 60:
        tts_text = re.sub(r"([.!?])\s+", r"\1... ", tts_text)

    payload = {
        "text": tts_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.75,
            "speed": 0.92,
            "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=40)
            response.raise_for_status()
            filename = f"vn_{int(time.time())}_{random.randint(1000, 9999)}.mp3"
            (AUDIO_DIR / filename).write_bytes(response.content)
            logger.info(f"🎙️ Voice note saved: {filename}")
            return f"/audio/{filename}"
        except requests.exceptions.RequestException as e:
            logger.warning(f"ElevenLabs attempt {attempt + 1} failed: {e}")
            if attempt < max_retries:
                time.sleep(1.5)
    return None
