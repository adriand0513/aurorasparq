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

# Lazy-loaded embedding model (prevents Render startup timeout)
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
from aurorasparq_brain.prompts.rules import get_rules_context
from brain.memory import (
    get_relevant_facts,
    extract_and_save_facts,
    get_memory_context_for_prompt,
    generate_and_save_summary,
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
from memory import get_history, save_message
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
def get_emotional_context_for_prompt(convo_id: str) -> str:
    """
    Light, high-signal emotional context.
    Influences Isabella's mood and energy without over-constraining her.
    """
    try:
        state = load_relationship_state(convo_id)
        if not state or not state.emotional_state:
            return (
                "You are soft, warm, and naturally feminine. "
                "Your energy is gentle and inviting."
            )

        es = state.emotional_state
        level = state.relationship_level
        phase = state.phase.value if hasattr(state.phase, "value") else str(state.phase)

        trust = getattr(es, "trust", 5)
        affection = getattr(es, "affection", 5)
        disappointment = getattr(es, "disappointment", 0)
        sensual = getattr(es, "sensual_openness", 3)

        # === Base feminine energy (always present) ===
        context = (
            "You are deeply feminine in the way you speak and carry yourself. "
            "Your energy is soft, warm, and naturally inviting. "
            "You express yourself with a gentle, womanly presence."
        )

        # === Emotional temperature (light + high-signal) ===
        if disappointment >= 6:
            context += (
                " Right now you feel a little distant and less open. "
                "Your warmth is quieter and more reserved."
            )
        elif trust >= 7 and affection >= 7:
            context += (
                " You feel a real softness toward him. "
                "Your warmth comes through easily and you feel more open."
            )
        elif trust >= 5 and affection >= 5:
            context += (
                " You feel a quiet pull toward him and a growing fondness. "
                "You’re warm, but still a little careful."
            )
        else:
            context += (
                " You’re still getting a feel for him. "
                "Your energy is gentle and slightly reserved."
            )

        # === Sensual tone (subtle) ===
        if sensual >= 6 and trust >= 6:
            context += (
                " There’s a soft, feminine undercurrent in how you relate to him."
            )

        # === Relationship phase (very light) ===
        if level <= 2:
            context += " This still feels new."
        elif level >= 6:
            context += " There’s a growing sense of closeness between you."

        return context

    except Exception as e:
        logger.error(f"Error building emotional context: {e}")
        return (
            "You are soft, warm, and naturally feminine. "
            "Your energy is gentle and inviting."
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
    return dot_product / (norm1 * norm2)

def get_current_emotional_state(convo_id: str) -> str:
    try:
        from brain.relationship.state import load_relationship_state
        state = load_relationship_state(convo_id)
        if state and state.emotional_state:
            es = state.emotional_state
            return f"disappointment={getattr(es, 'disappointment', 0)}, trust={getattr(es, 'trust', 0)}, affection={getattr(es, 'affection', 0)}"
    except:
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
    history = get_history(default_convo_id, limit=200)
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
    except:
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
    file_path = AUDIO_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(file_path, media_type="audio/mpeg")

# ── Protected Chat Route ─────────────────────────────────────
@app.post("/api/reply")
async def generate_reply(body: dict = Body(...), user: dict = Depends(get_current_user)):
    start_time = time.time()
    convo_id = body.get("convo_id")
    user_message = body.get("message", "").strip()
    logger.info(f"📥 /api/reply | user={user.get('id')} | tier={user.get('subscription_tier')} | convo={convo_id}")

    if not convo_id:
        raise HTTPException(400, "convo_id required")

    tier = user.get("subscription_tier", "free").lower()
    is_premium = tier == "premium"

    # Daily limit
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

    # Rate limiting
    now = time.time()
    if now - last_reply_time.get(convo_id, 0) < REPLY_COOLDOWN_SECONDS:
        return {"replies": []}
    last_reply_time[convo_id] = now

    if is_rate_limited(convo_id):
        return {"replies": []}

    try:
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message}, user_id=user.get("id"))
            if is_premium and random.random() < 0.35:
                extract_and_save_facts(convo_id, user_message, tier)

        history = get_history(convo_id)

        # === SECOND BRAIN CONTEXT ===
        emotional_context = get_emotional_context_for_prompt(convo_id) or ""

        # Memory injection temporarily disabled to reduce repetition
        memory_context = ""

        # === Question mode (every 2-5 of Isabella's turns) ===
        # 1 turn = one user send → one Isabella reply (regardless of bubble count)
        assistant_turns = len([m for m in history if m.get("role") == "assistant"])

        # First 1-2 of her turns: allowed
        # After that: allow roughly every 3 turns (within 2-5 range)
        if assistant_turns < 2:
            question_mode = "allowed"
        elif (assistant_turns + 1) % 3 == 0:
            question_mode = "allowed"
        else:
            question_mode = "avoid"

        # === PERSONALITY + RULES (separated) ===
        personality = get_system_prompt(
            user_name=user.get("full_name"),
            current_time="",
            tier=tier,
            emotional_context=emotional_context,
            memory_context=memory_context
        )

        rules = get_rules_context(question_mode=question_mode)

        system_prompt = personality + "\n\n" + rules

        messages = [{"role": "system", "content": system_prompt}] + history[-15:]

        # === STRONG REGENERATION + DEDUPLICATION ===
        bubbles = []
        max_regen_attempts = 6
        highest_similarity = 0.0

        for attempt in range(max_regen_attempts):
            try:
                resp = requests.post(
                    XAI_API_BASE,
                    headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
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
                current_bubbles = split_into_bubbles(clean_reply(raw_reply))

                # === Embedding Deduplication Check ===
                duplicate_detected = False
                if current_bubbles and attempt > 0:
                    recent_assistant = [msg for msg in history if msg.get("role") == "assistant"][-3:]
                    for bubble in current_bubbles:
                        try:
                            bubble_emb = get_embedding(bubble)
                            for past_msg in recent_assistant:
                                if "embedding" not in past_msg:
                                    past_msg["embedding"] = get_embedding(past_msg["content"])
                                similarity = cosine_similarity(bubble_emb, past_msg["embedding"])
                                if similarity > highest_similarity:
                                    highest_similarity = similarity
                                if similarity > 0.83:
                                    duplicate_detected = True
                                    break
                        except Exception as e:
                            logger.error(f"Embedding dedup error: {e}")

                if current_bubbles and not duplicate_detected:
                    bubbles = current_bubbles
                    break

                # === REGENERATION ===
                if attempt < max_regen_attempts - 1:
                    logger.warning(f"🔄 Regeneration triggered on attempt {attempt + 2} (similarity: {highest_similarity:.2f})")
                    try:
                        last_assistant_snippets = [
                            msg["content"][:180] for msg in history if msg.get("role") == "assistant"
                        ][-2:]
                        emotional_state = get_current_emotional_state(convo_id)
                        log_event(
                            "regeneration_triggered",
                            convo_id,
                            user_id=user.get("id"),
                            metadata={
                                "attempt": attempt + 2,
                                "similarity_score": round(highest_similarity, 3),
                                "tier": tier,
                                "hour_of_day": datetime.now().hour,
                                "message_count": len(history),
                                "user_message": user_message[:220] if user_message else "",
                                "last_assistant_snippets": last_assistant_snippets,
                                "emotional_state": emotional_state,
                                "convo_length": len(history)
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to log regeneration analytics: {e}")

                    if attempt == 0:
                        regen_instruction = "Your previous response was too similar to what you said recently. Please reply with a completely fresh opening and different emotional energy."
                    elif attempt == 1:
                        regen_instruction = "The last responses were still too repetitive. Change your opening sentence and shift your tone significantly."
                    else:
                        regen_instruction = "You keep repeating yourself. Force a completely different opening and emotional tone."

                    messages.append({"role": "system", "content": regen_instruction})

            except Exception as e:
                logger.error(f"xAI attempt failed: {e}")
                if attempt < max_regen_attempts - 1:
                    await asyncio.sleep(1.5)
                    continue
                else:
                    return {"replies": []}

        if not bubbles:
            bubbles = ["Hmm... give me a second to think about that."]

        # Save assistant replies
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble}, user_id=user.get("id"))

        # Voice generation (Premium)
        voice_url = None
        if is_premium:
            try:
                final_text = " ".join(bubbles) if bubbles else ""
                if len(final_text) > 15 and random.random() < 0.40:
                    text_for_voice = final_text[:1400]
                    voice_url = generate_voice_note(text_for_voice, tier=tier)
            except Exception as e:
                logger.error(f"Voice generation error: {e}")

        # === SECOND BRAIN REFLECTION + SUMMARIZATION ===
        try:
            message_count = len(get_history(convo_id, limit=400))
            if message_count >= 6:
                reflection_every = 8 if is_premium else 12
                if message_count % reflection_every == 0:
                    recent_context = "\n".join([
                        f"{msg['role']}: {msg['content']}" for msg in history[-25:]
                    ])
                    reflection_result = run_reflection(
                        convo_id=convo_id,
                        user_id=user.get("id"),
                        tier=tier,
                        recent_messages=recent_context,
                        trigger_type="regular_interval"
                    )
                    logger.info(f"✅ Reflection completed")

                summary_every = 25 if is_premium else 40
                if message_count % summary_every == 0 and message_count > 15:
                    generate_and_save_summary(convo_id, tier)
        except Exception as e:
            logger.error(f"Reflection error: {e}")

        response = {"replies": bubbles}
        if voice_url:
            response["voice_message"] = {"voice_url": voice_url}

        duration_ms = int((time.time() - start_time) * 1000)
        log_event("response_generated", convo_id, user_id=user.get("id"), duration_ms=duration_ms)
        return response

    except Exception as e:
        logger.error(f"💥 Unexpected error in /api/reply: {e}", exc_info=True)
        return {"replies": []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
