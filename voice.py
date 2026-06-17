# voice.py - Updated for Persistent Disk + Tier Logic
import os
import requests
import re
import time
import random
from pathlib import Path
from typing import Optional

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# Persistent disk path (Render)
AUDIO_DIR = Path("/var/data/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def expand_abbreviations_for_tts(text: str) -> str:
    """Expand common texting abbreviations for natural TTS pronunciation."""
    expansions = {
        r'\baf\b': 'as fuck', r'\bAF\b': 'as fuck', r'\basf\b': 'as fuck',
        r'\bbc\b': 'because', r'\bBC\b': 'because', r'\bbcs\b': 'because',
        r'\btbh\b': 'to be honest', r'\bTBH\b': 'to be honest',
        r'\bfr\b': 'for real', r'\bFR\b': 'for real', r'\bfrfr\b': 'for real for real',
        r'\bngl\b': 'not gonna lie', r'\bNGL\b': 'not gonna lie',
        r'\bidk\b': 'I don’t know', r'\bIDK\b': 'I don’t know',
        r'\bmin\b': 'minute', r'\bmins\b': 'minutes',
        r'\bprobs\b': 'probably', r'\bdef\b': 'definitely',
        r'\brn\b': 'right now', r'\bRN\b': 'right now',
        r'\bbrb\b': 'be right back', r'\bttyl\b': 'talk to you later',
        r'\bg2g\b': 'got to go', r'\batm\b': 'at the moment',
        r'\bsmh\b': 'shaking my head', r'\bfomo\b': 'fear of missing out',
        r'\bimo\b': 'in my opinion', r'\bbffr\b': 'be for real',
        r'\bpmo\b': 'pisses me off', r'\bwtf\b': 'what the fuck',
        r'\bidc\b': 'I don’t care', r'\bnvm\b': 'never mind',
        r'\blmk\b': 'let me know', r'\bily\b': 'I love you',
        r'\bomw\b': 'on my way', r'\bicl\b': 'I can’t lie',
        r'\batp\b': 'at this point',
    }
    for pattern, repl in expansions.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def should_generate_voice(tier: str) -> bool:
    """
    Decide whether Isabella should reply with voice based on tier.
    - Premium: 11% chance
    - Ultimate: 58% chance
    """
    if tier == "ultimate":
        return random.random() < 0.58
    elif tier == "premium":
        return random.random() < 0.11
    return False


def generate_voice_note(text: str, tier: str = "premium", add_pause: bool = True) -> Optional[str]:
    """
    Generate a voice note using ElevenLabs.
    Returns the public URL if successful, otherwise None.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        print("ElevenLabs keys missing - skipping voice note")
        return None

    if not should_generate_voice(tier):
        return None

    # Prepare TTS-optimized text
    tts_text = expand_abbreviations_for_tts(text)

    # Add natural pauses for longer messages
    if add_pause and len(tts_text) > 60:
        tts_text = re.sub(r'([.!?])\s+', r'\1... ', tts_text)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    # Voice settings tuned for seductive/intimate feel
    payload = {
        "text": tts_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.75,
            "speed": 0.92,
            "use_speaker_boost": True
        }
    }

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            print(f"Generating voice note for {tier} (attempt {attempt+1})")
            response = requests.post(url, json=payload, headers=headers, timeout=40)
            response.raise_for_status()

            # Save to persistent disk
            timestamp = int(time.time())
            rand_suffix = random.randint(1000, 9999)
            filename = f"vn_{timestamp}_{rand_suffix}.mp3"
            filepath = AUDIO_DIR / filename

            with open(filepath, "wb") as f:
                f.write(response.content)

            print(f"Voice note saved: {filepath}")
            return f"/audio/{filename}"   # Public URL route we'll create

        except requests.exceptions.RequestException as e:
            print(f"ElevenLabs attempt {attempt+1} failed: {e}")
            if attempt < max_retries:
                time.sleep(1.5)
            else:
                print("Max retries reached - skipping voice note")
                return None

    return None
