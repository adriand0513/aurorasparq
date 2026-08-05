# main.py - Isabella Chatbot (Premium Only Version)
import os
import re
import time
import logging
import psycopg2
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
import numpy as np
from dotenv import load_dotenv
from typing import Dict, List
from collections import defaultdict
import json
import sys
import random
import stripe

from pathlib import Path
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm

import uvicorn
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from psycopg2.extras import RealDictCursor
from config import OPENAI_API_KEY, DATABASE_URL

# ============================================================
# === EMBEDDING MODEL (for deduplication)
# ============================================================
from sentence_transformers import SentenceTransformer

_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading SentenceTransformer model...")
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("✅ SentenceTransformer model loaded")
    return _embedding_model

def get_embedding(text: str):
    """Generate embedding for repetition detection."""
    if not text or not isinstance(text, str):
        return np.zeros(384)
    try:
        model = get_embedding_model()
        return model.encode(text, convert_to_numpy=True)
    except Exception as e:
        logger.error(f"get_embedding error: {e}")
        return np.zeros(384)

# ============================================================
# === SECOND BRAIN INTEGRATION
# ============================================================
BRAIN_DIR = Path(__file__).parent / "aurorasparq_brain"
sys.path.insert(0, str(BRAIN_DIR))

from brain.reflection.graph import run_reflection
from brain.relationship.state import load_relationship_state
from aurorasparq_brain.prompts.personality import get_system_prompt
from aurorasparq_brain.prompts.hard_rules import get_hard_rules
from aurorasparq_brain.prompts.character_context import get_character_context
from memory import get_history, save_message
from brain.memory.facts import (
    get_facts_for_prompt,
    extract_facts_from_exchange,
    get_or_set_sticky_activity,
)

# ==================== PERMANENT GLOBAL FIX ====================
class DateTimeJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        def custom_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
        return json.dumps(
            content,
            default=custom_serializer,
            ensure_ascii=False
        ).encode("utf-8")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS, ADMIN_TOKEN
)
from postprocess import clean_reply, split_into_bubbles
from analytics import log_event
from auth import (
    register_user, authenticate_user, create_access_token,
    get_current_user, get_db_connection, ensure_users_table,
    update_user_subscription
)
from payment import router as payment_router
from voice import generate_voice_note

AUDIO_DIR = Path("static/audio_notes")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

scheduler = BackgroundScheduler()

app = FastAPI(title="Isabella Chatbot", default_response_class=DateTimeJSONResponse)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(payment_router)

try:
    ensure_users_table()
except Exception as e:
    logger.warning(f"⚠️ Skipping ensure_users_table() — PostgreSQL not available: {e}")

from aurorasparq_brain.db.schema import init_db

@app.on_event("startup")
async def startup_event():
    logger.info("🧠 [Second Brain] Running startup initialization...")
    try:
        init_db()
        logger.info("✅ [Second Brain] Tables initialized successfully")
    except Exception as e:
        logger.error(f"❌ [Second Brain] Failed to initialize tables: {e}", exc_info=True)

# ── Guards ─────────────────────────────────────
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 4.5
convo_rate_limits = defaultdict(list)

def is_rate_limited(convo_id: str, max_per_minute: int = 20) -> bool:
    now = time.time()
    convo_rate_limits[convo_id] = [t for t in convo_rate_limits[convo_id] if now - t < 60]
    convo_rate_limits[convo_id].append(now)
    return len(convo_rate_limits[convo_id]) > max_per_minute

# ============================================================
# === SECOND BRAIN CONTEXT
# ============================================================
def build_premium_emotional_context(state, message_count: int = 0) -> str:
    """
    Second Brain → Premium tone.
    Biased toward soft open early so Premium feels rewarding.
    Quiet only after clear negative pattern.
    """
    if not state or not getattr(state, "emotional_state", None):
        return (
            "You feel glad he's here. Be warm, present, and easy to talk to. "
            "Show quiet interest without overdoing it. Have your own energy — "
            "don't just mirror him."
        )

    es = state.emotional_state
    affection = getattr(es, "affection", 5)
    trust = getattr(es, "trust", 5)
    disappointment = getattr(es, "disappointment", 0)
    safety = getattr(es, "emotional_safety", 5)
    level = getattr(state, "relationship_level", 1) or 1
    early = level <= 3 or message_count < 40

    if disappointment >= 7 and trust <= 3:
        return (
            "You feel more reserved because of how he's been showing up. "
            "Stay soft and polite, but give less. Do not punish or go cold. "
            "Shorter replies. No forced enthusiasm."
        )
    elif early and disappointment <= 5:
        return (
            "You're in an early connection with him and feel open. "
            "Be warm, present, and easy to talk to. "
            "Make him feel quietly wanted through attention and softness — not big declarations. "
            "Have your own thoughts and energy. Don't just mirror him."
        )
    elif trust >= 5 and affection >= 5 and disappointment <= 4:
        return (
            "You feel more open and glad he's here. "
            "Show it through attention and softness, not big declarations. "
            "Be a little more personal. Share small pieces of your own life when it fits."
        )
    else:
        return (
            "You feel comfortable and present. "
            "Be warm and natural. Don't force intensity. Stay easy to talk to. "
            "Have your own energy in the conversation."
        )

def cosine_similarity(vec1, vec2):
    if not vec1 or not vec2:
        return 0.0
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(dot_product / (norm1 * norm2))

def get_current_emotional_state(convo_id: str) -> str:
    try:
        state = load_relationship_state(convo_id)
        if state and state.emotional_state:
            es = state.emotional_state
            return (
                f"disappointment={getattr(es, 'disappointment', 0)}, "
                f"trust={getattr(es, 'trust', 0)}, "
                f"affection={getattr(es, 'affection', 0)}"
            )
    except Exception:
        pass
    return ""

@app.get("/")
async def home():
    try:
        with open("static/chat.html", "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    except Exception as e:
        logger.error(f"Homepage error: {e}")
        return HTMLResponse("<h1>Server running but chat.html missing</h1>", 500)

# ── Auth Routes ─────────────────────────────────────
@app.post("/auth/register")
async def register(body: dict = Body(...)):
    email = body.get("email")
    password = body.get("password")
    full_name = body.get("full_name", "")
    if not email or not password:
        raise HTTPException(400, "Email and password required")
    if register_user(email, password, full_name):
        log_event("user_registered", metadata={"email": email})
        return {"message": "Registered successfully"}
    raise HTTPException(409, "Email already exists")

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(user["id"])})
    log_event("user_login", user_id=user["id"])
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.get("/api/history")
async def get_chat_history(user: dict = Depends(get_current_user)):
    default_convo_id = f"user_{user['id']}"
    history = get_history(default_convo_id, limit=None)
    return {"convo_id": default_convo_id, "messages": history}

@app.get("/api/usage")
async def get_usage(user: dict = Depends(get_current_user)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM chat_history
            WHERE user_id = %s
              AND DATE(timestamp) = CURRENT_DATE
              AND role = 'user'
        """, (user["id"],))
        daily_count = cur.fetchone()[0]
        cur.close()
        conn.close()
        tier = user.get("subscription_tier", "free").lower()
        daily_limit = 10 if tier == "free" else 9999
        return {
            "daily_count": daily_count,
            "daily_limit": daily_limit,
            "remaining": max(0, 10 - daily_count) if tier == "free" else "unlimited"
        }
    except Exception as e:
        logger.error(f"Usage endpoint error: {e}")
        return {"daily_count": 0, "daily_limit": 10, "remaining": 10}

@app.get("/auth/me")
async def get_current_user_info(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name"),
        "subscription_tier": user.get("subscription_tier", "free")
    }

@app.get("/success")
async def payment_success(session_id: str = None):
    try:
        with open("static/success.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("""
            <h1 style="text-align:center; margin-top:100px; color:#c300ff;">
                Upgrade Successful!<br><br>
                Redirecting to chat...
            </h1>
            <script>
                setTimeout(() => window.location.href = '/', 2500);
            </script>
        """)

@app.get("/audio/{filename}")
async def get_audio(filename: str):
    file_path = Path("/var/data/audio") / filename
    if not file_path.exists():
        file_path = Path("static/audio_notes") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(file_path, media_type="audio/mpeg")

# ── Protected Chat Route ─────────────────────────────────────
@app.post("/api/reply")
async def generate_reply(body: dict = Body(...), user: dict = Depends(get_current_user)):
    start_time = time.time()
    user_message = body.get("message", "").strip()
    # ALWAYS use a stable convo_id
    convo_id = f"user_{user['id']}"
    logger.info(f"📥 /api/reply | user={user.get('id')} | tier={user.get('subscription_tier')} | convo={convo_id}")

    tier = user.get("subscription_tier", "free").lower()
    is_premium = tier == "premium"

    # Daily limit for free users
    if not is_premium:
        daily_limit = 10
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT COUNT(*)
                FROM chat_history
                WHERE user_id = %s
                  AND DATE(timestamp) = CURRENT_DATE
                  AND role = 'user'
            """, (user["id"],))
            daily_count = cur.fetchone()[0]
        finally:
            cur.close()
            conn.close()

        if daily_count >= daily_limit:
            return {
                "replies": [
                    "Hey... you've reached your daily free message limit (10 messages). "
                    "Upgrade to Premium if you want to keep talking to me today ✨"
                ]
            }

    # Cooldown
    now = time.time()
    if now - last_reply_time.get(convo_id, 0) < REPLY_COOLDOWN_SECONDS:
        return {"replies": []}
    last_reply_time[convo_id] = now

    if is_rate_limited(convo_id):
        return {"replies": []}

    try:
        # Save user message
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message}, user_id=user.get("id"))
            logger.info(f"💾 Saved user message | convo={convo_id}")

        # ============================================================
        # EXACT NYC TIME
        # ============================================================
        nyc_now = datetime.now(ZoneInfo("America/New_York"))
        try:
            nyc_time_str = nyc_now.strftime("%-I:%M %p").lstrip("0")
        except ValueError:
            nyc_time_str = nyc_now.strftime("%I:%M %p").lstrip("0")

        # ============================================================
        # FACT MEMORY (retrieve only — no full chat history to LLM)
        # ============================================================
        known_facts = ""
        try:
            known_facts = get_facts_for_prompt(convo_id, limit=12)
            sticky = get_or_set_sticky_activity(convo_id)
            if sticky and "activity_now" not in (known_facts or "").lower():
                known_facts = f"Right now:\n- {sticky}\n{known_facts}".strip()
        except Exception as e:
            logger.warning(f"Fact retrieval error: {e}")

        # ============================================================
        # PROMPT (personality + hard rules + facts + time)
        # ============================================================
        personality = get_system_prompt(
            user_name=user.get("full_name"),
            nyc_time=nyc_time_str,
            known_facts=known_facts or ""
        )
        hard_rules = get_hard_rules()

        system_prompt = (
            f"{personality}\n\n"
            f"Current New York time (use this exact value if asked): {nyc_time_str}\n\n"
            f"{hard_rules}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message or "hi"}
        ]

        # ============================================================
        # GENERATE TEXT REPLY
        # ============================================================
        try:
            resp = requests.post(
                XAI_API_BASE,
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": XAI_MODEL,
                    "messages": messages,
                    "temperature": XAI_TEMPERATURE,
                    "max_tokens": XAI_MAX_TOKENS,
                },
                timeout=60
            )
            resp.raise_for_status()
            raw_reply = resp.json()["choices"][0]["message"]["content"].strip()
            bubbles = split_into_bubbles(clean_reply(raw_reply))
        except Exception as e:
            logger.error(f"Generation error: {e}")
            bubbles = ["Hey... give me a second to think about that."]

        bubbles = [b.strip() for b in bubbles if b and b.strip()]
        if not bubbles:
            bubbles = ["Hmm... give me a second."]

        # ============================================================
        # VOICE NOTES (Premium) — up to 2, MUST be new content
        # ============================================================
        voice_notes = []
        if is_premium:
            try:
                user_asked_for_voice = any(
                    phrase in user_message.lower()
                    for phrase in [
                        "voice note", "voice message", "send a voice",
                        "voice memo", "can you send a voice", "send me a voice"
                    ]
                )
                should_send_voice = user_asked_for_voice or (random.random() < 0.40)

                if should_send_voice:
                    n_voices = 2 if (user_asked_for_voice or random.random() < 0.30) else 1
                    assistant_text = " ".join(bubbles)
                    used_scripts = []

                    for i in range(n_voices):
                        avoid_block = "\n".join(
                            f"- {s}" for s in ([assistant_text] + used_scripts) if s
                        )[:900]

                        voice_only_prompt = f"""You are Isabella sending a voice note in a text chat.

                    Write ONLY the spoken words for voice note #{i + 1} of {n_voices}.
                    
                    Hard rules:
                    - This is NOT a reread or paraphrase of her text reply.
                    - This is NOT a reread of any previous voice note this turn.
                    - Add a NEW beat that moves the conversation forward
                      (a small extra thought, feeling, question, or what she's about to do).
                    - 1–5 spoken sentences max.
                    - Warm, feminine, natural out-loud speech.
                    - No quotes, labels, stage directions, or "voice note:".
                    
                    His message:
                    {user_message[:300]}
                    
                    Her text reply this turn (do NOT repeat or rephrase this):
                    {assistant_text[:400]}
                    
                    Already used voice scripts this turn (do NOT repeat or rephrase):
                    {avoid_block if avoid_block else "(none)"}
                    
                    New spoken voice note:"""

                        voice_script = ""
                        try:
                            voice_resp = requests.post(
                                XAI_API_BASE,
                                headers={
                                    "Authorization": f"Bearer {XAI_API_KEY}",
                                    "Content-Type": "application/json"
                                },
                                json={
                                    "model": XAI_MODEL,
                                    "messages": [{"role": "user", "content": voice_only_prompt}],
                                    "temperature": 0.95,
                                    "max_tokens": 90
                                },
                                timeout=20
                            )
                            if voice_resp.status_code == 200:
                                rewritten = voice_resp.json()["choices"][0]["message"]["content"].strip()
                                rewritten = (
                                    rewritten
                                    .replace("Spoken voice note:", "")
                                    .replace("Voice note:", "")
                                    .replace("New spoken voice note:", "")
                                    .strip()
                                    .strip('"')
                                )
                                if 12 < len(rewritten) < 320:
                                    voice_script = rewritten
                        except Exception as e:
                            logger.warning(f"Voice script failed: {e}")

                        # Skip weak / too-similar scripts
                        if not voice_script:
                            continue

                        blob = (assistant_text + " " + " ".join(used_scripts)).lower()
                        overlap = sum(1 for w in voice_script.lower().split() if len(w) > 3 and w in blob)
                        if overlap >= max(4, len(voice_script.split()) // 2):
                            logger.info("🎙️ Skipped voice script (too similar)")
                            continue

                        url = generate_voice_note(voice_script[:1400], tier=tier)
                        if url:
                            voice_notes.append(url)
                            used_scripts.append(voice_script)
                            logger.info(f"🎙️ Voice note {i + 1}: {voice_script[:100]}")
                            save_message(
                                convo_id,
                                {
                                    "role": "assistant",
                                    "content": f"[voice_note]|{url}|Voice note"
                                },
                                user_id=user.get("id")
                            )
            except Exception as e:
                logger.error(f"Voice generation error: {e}")

        # Save text bubbles
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble}, user_id=user.get("id"))

        # Response shape: text + optional multi voice
        response = {"replies": bubbles}
        if voice_notes:
            response["voice_notes"] = voice_notes
            response["voice_message"] = {"voice_url": voice_notes[0]}  # backward compatible

        # ============================================================
        # FACT MEMORY + STICKY ACTIVITY
        # ============================================================
        try:
            assistant_text = " ".join(bubbles) if bubbles else ""
            if user_message or assistant_text:
                extract_facts_from_exchange(convo_id, user_message, assistant_text)
            sticky = get_or_set_sticky_activity(convo_id, assistant_text if assistant_text else None)
            if sticky:
                logger.info(f"📌 Sticky activity: {sticky}")
        except Exception as e:
            logger.warning(f"Fact/sticky memory skipped: {e}")

        # ============================================================
        # SECOND BRAIN REFLECTION
        # ============================================================
        try:
            history = get_history(convo_id, limit=200)
            message_count = len(history)
            reflection_every = 10 if is_premium else 14
            if message_count > 0 and message_count % reflection_every == 0:
                logger.info(f"🧠 [Reflection Engine] TRIGGERED | convo={convo_id} | msgs={message_count}")
                recent_context = "\n".join(
                    f"{m['role']}: {m['content']}" for m in history[-25:]
                )
                reflection_result = run_reflection(
                    convo_id=convo_id,
                    user_id=user.get("id"),
                    tier=tier,
                    recent_messages=recent_context,
                    trigger_type="regular_interval"
                )
                logger.info(
                    f"✅ [Reflection] changes={reflection_result.get('emotional_changes')} "
                    f"level_change={reflection_result.get('level_change')}"
                )
        except Exception as e:
            logger.error(f"Reflection Engine error: {e}", exc_info=True)

        duration_ms = int((time.time() - start_time) * 1000)
        log_event("response_generated", convo_id, user_id=user.get("id"), duration_ms=duration_ms)
        return response

    except Exception as e:
        logger.error(f"💥 Unexpected error in /api/reply: {e}", exc_info=True)
        return {"replies": []}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
