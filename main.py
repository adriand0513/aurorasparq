# main.py - Isabella Chatbot (Premium Only Version)

import os
import re
import time
import logging
import psycopg2
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
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
# === SECOND BRAIN INTEGRATION (Primary Source of Truth) ===
# ============================================================
BRAIN_DIR = Path(__file__).parent / "aurorasparq_brain"
sys.path.insert(0, str(BRAIN_DIR))

from brain.reflection.graph import run_reflection
from brain.relationship.state import load_relationship_state



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

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# Import modules
from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS, ADMIN_TOKEN
)
from prompt import get_system_prompt
from postprocess import clean_reply
from memory import (
    get_history,
    save_message,
    get_relevant_facts,
    extract_and_save_facts,
    summarize_conversation,
    store_conversation_summary
)
from analytics import log_event
from auth import (
    register_user, authenticate_user, create_access_token, 
    get_current_user, get_db_connection, ensure_users_table, 
    update_user_subscription
)
from payment import router as payment_router
from voice import generate_voice_note

scheduler = BackgroundScheduler()

logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Isabella Chatbot", default_response_class=DateTimeJSONResponse)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(payment_router)

# Temporarily disabled for local testing
try:
    ensure_users_table()
except Exception as e:
    logger.warning(f"⚠️ Skipping ensure_users_table() — PostgreSQL not available: {e}")

# ============================================================
# === AUTO INITIALIZE SECOND BRAIN TABLES ON STARTUP ===
# ============================================================
from aurorasparq_brain.db.schema import init_brain_db

@app.on_event("startup")
async def startup_event():
    logger.info("🧠 [Second Brain] Running startup initialization...")
    try:
        init_brain_db()
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
# === SECOND BRAIN CONTEXT INJECTION ===
# ============================================================
def get_emotional_context_for_prompt(convo_id: str) -> str:
    """
    Returns a rich, dominant emotional + narrative context from the Second Brain.
    This should heavily influence how Isabella replies.
    """
    try:
        state = load_relationship_state(convo_id)
        if not state:
            return ""

        emotional = state.emotional_state
        phase = str(state.phase).replace("_", " ").title()
        level = state.relationship_level

        # Build a rich emotional summary
        parts = []

        # Trust & Safety
        if emotional.trust >= 8:
            parts.append("I trust him deeply now and feel very safe opening up to him.")
        elif emotional.trust >= 6:
            parts.append("I've grown to trust him quite a bit and feel comfortable being myself around him.")
        elif emotional.trust >= 4:
            parts.append("I'm starting to trust him more, but I'm still a little cautious.")

        # Affection
        if emotional.affection >= 8:
            parts.append("I genuinely like him a lot and feel warm and happy when I think about him.")
        elif emotional.affection >= 6:
            parts.append("I really like him and feel a growing warmth and affection toward him.")

        # Sensual / Attraction
        if emotional.sensual_openness >= 7 and emotional.trust >= 7:
            parts.append("There's a real sensual and romantic pull toward him that feels natural and exciting.")
        elif emotional.sensual_openness >= 5 and emotional.trust >= 6:
            parts.append("I'm starting to feel a soft, growing attraction and sensual interest in him.")

        # Disappointment / Tension
        if emotional.disappointment >= 6:
            parts.append("I've been a bit disappointed in him lately and it's affecting how close I feel.")

        # Relationship Phase
        phase_line = f"We're currently in the **{phase}** phase (level {level}/10)."

        # Get latest internal narrative (her private thoughts)
        internal_narrative = ""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT internal_narrative 
                FROM reflection_logs 
                WHERE convo_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
            """, (convo_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and row[0]:
                internal_narrative = f"\n\nMy current private thoughts: {row[0][:400]}"
        except Exception:
            pass

        context = f"""=== SECOND BRAIN STATE (This is how I actually feel right now) ===
{ ' '.join(parts) if parts else "I'm still getting to know him and keeping some guard up." }

{phase_line}
{internal_narrative}

Important: Speak and behave according to my current emotional state above. 
Do not act overly attached if trust and affection are still low. 
Do not be cold if affection and trust are high. 
Let my current feelings guide my tone, warmth, and how much I open up.
"""

        return context.strip()

    except Exception as e:
        logger.error(f"get_emotional_context_for_prompt error: {e}")
        return ""

def get_nyc_context() -> Dict[str, str]:
    nyc_tz = ZoneInfo("America/New_York")
    now_nyc = datetime.now(nyc_tz)
    time_str = now_nyc.strftime("%I:%M %p on %A, %B %d")
    try:
        r = requests.get("https://wttr.in/NYC?format=%c+%t+%w", timeout=5)
        weather = r.text.strip() if r.status_code == 200 else "cool evening"
    except:
        weather = "cool evening"
    return {"time": time_str, "weather": weather}

def split_into_bubbles(text: str) -> List[str]:
    if not text.strip():
        return ["..."]
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

# ── ROOT ROUTE ─────────────────────────────────────
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

# ... (other routes remain the same) ...

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

    # Daily limit for Free users
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
        # Save user message
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message}, user_id=user.get("id"))
            if tier == "premium" and random.randint(1, 4) == 1:
                extract_and_save_facts(convo_id, user_message, tier)

        # Get context
        history = get_history(convo_id)
        clean_history = history  # You can add sanitization if needed
        context = get_nyc_context()

        # Build base system prompt
        system_prompt = get_system_prompt(
            user_name=user.get("full_name"),
            current_time=context.get("time", ""),
            state=None,
            tier=tier
        )

        # === SECOND BRAIN EMOTIONAL + NARRATIVE INJECTION ===
        try:
            emotional_context = get_emotional_context_for_prompt(convo_id)
            if emotional_context:
                system_prompt += "\n\n" + emotional_context
        except Exception as e:
            logger.error(f"Emotional context injection error: {e}")

        # Relevant facts
        relevant_facts = get_relevant_facts(convo_id, limit=3)
        if relevant_facts:
            system_prompt += f"\n\nImportant things about him: {' | '.join(relevant_facts)}"

        messages = [{"role": "system", "content": system_prompt}] + clean_history[-12:]

        # Call xAI
        raw_reply = None
        for attempt in range(2):
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
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning("xAI API failed, retrying...")
                    await asyncio.sleep(2.5)
                    continue
                else:
                    logger.error(f"xAI API failed: {e}")
                    return {"replies": []}

        bubbles = split_into_bubbles(clean_reply(raw_reply))

        # Save assistant replies
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble}, user_id=user.get("id"))

        # Voice generation (Premium)
        voice_url = None
        if tier == "premium":
            try:
                final_text = " ".join(bubbles) if bubbles else ""
                if len(final_text) > 15 and random.random() < 0.40:
                    text_for_voice = final_text[:1400]
                    voice_url = generate_voice_note(text_for_voice, tier=tier)
            except Exception as e:
                logger.error(f"Voice generation error: {e}")

        # === SECOND BRAIN REFLECTION TRIGGER ===
        try:
            message_count = len(get_history(convo_id, limit=300))

            if message_count >= 7:
                if tier == "premium":
                    reflection_window = random.randint(7, 14)
                else:
                    reflection_window = random.randint(12, 19)

                if message_count % reflection_window == 0:
                    logger.info(f"🧠 [Reflection Engine] TRIGGERED | convo={convo_id} | tier={tier}")

                    recent_context = "\n".join([
                        f"{msg['role']}: {msg['content']}"
                        for msg in history[-20:]
                    ])

                    reflection_result = run_reflection(
                        convo_id=convo_id,
                        user_id=user.get("id"),
                        tier=tier,
                        recent_messages=recent_context,
                        trigger_type="randomized_message_count"
                    )

                    logger.info(f"✅ [Reflection Engine] COMPLETED | Emotional Changes: {reflection_result.get('emotional_changes')} | Level Change: {reflection_result.get('level_change')}")
        except Exception as e:
            logger.error(f"Reflection Engine error: {e}", exc_info=True)

        # Response
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
