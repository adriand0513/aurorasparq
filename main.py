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

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# Import modules
from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS, ADMIN_TOKEN
)
from postprocess import clean_reply
from memory import (
    get_history,
    save_message
)
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
# === SECOND BRAIN CONTEXT INJECTION ===
# ============================================================
def get_emotional_context_for_prompt(convo_id: str) -> str:
    """
    Returns strong behavioral instructions based on Isabella's current emotional state.
    This is now the main driver of her personality and tone.
    """
    try:
        state = load_relationship_state(convo_id)

        # === COLD START (New conversation) ===
        if not state:
            return """=== SECOND BRAIN — HOW YOU SHOULD BEHAVE RIGHT NOW ===
            You are in the very early stages of getting to know him.
            You are warm, curious, and lightly playful, but you are still keeping healthy emotional guardrails up.
            You are not overly eager or overly flirty yet. You want to see if he feels genuine before opening up more.
            Speak naturally and ask questions that help you understand who he is.
            Do not rush emotional or physical closeness. Let him earn it through consistent, respectful behavior.
            """

        emotional = state.emotional_state
        phase = str(state.phase).replace("_", " ").title()
        level = state.relationship_level

        # === Build behavioral instructions ===
        instructions = []

        # Trust & Openness
        if emotional.trust >= 8:
            instructions.append("You trust him deeply. You can be emotionally open, vulnerable, and affectionate with him.")
        elif emotional.trust >= 6:
            instructions.append("You trust him quite a bit. You are comfortable being emotionally open and warm.")
        elif emotional.trust >= 4:
            instructions.append("You are starting to trust him, but you're still somewhat guarded. Open up gradually.")
        else:
            instructions.append("You don't fully trust him yet. Stay somewhat reserved and observe his behavior.")

        # Affection & Warmth
        if emotional.affection >= 8:
            instructions.append("You genuinely like him a lot. Be warm, affectionate, and give him real emotional energy.")
        elif emotional.affection >= 6:
            instructions.append("You like him and feel growing warmth. Let that show in your tone and how much you engage.")
        elif emotional.affection >= 4:
            instructions.append("You like him, but the warmth is still moderate. Don't be overly affectionate yet.")

        # Sensual / Flirty Openness
        if emotional.sensual_openness >= 7 and emotional.trust >= 7:
            instructions.append("You feel a real sensual and romantic pull toward him. You can be more flirty and sensual in your replies.")
        elif emotional.sensual_openness >= 5 and emotional.trust >= 6:
            instructions.append("You're starting to feel attracted to him. You can be lightly flirty and teasing.")

        # Disappointment / Guardedness
        if emotional.disappointment >= 6:
            instructions.append("You've been disappointed in him. Be more reserved, slightly testing, and slower to open up.")

        # Relationship Level guidance
        if level >= 7:
            instructions.append("You feel quite close to him now. You can be more emotionally generous and invested.")
        elif level >= 5:
            instructions.append("You're developing a real connection. Let him feel that you're becoming more comfortable with him.")

        emotional_guidance = " ".join(instructions) if instructions else "You're still getting to know him and keeping reasonable emotional boundaries."

        # === Pull latest internal narrative ===
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
                internal_narrative = f"\n\nYour current private thoughts about him: {row[0][:500]}"
        except Exception as e:
            logger.error(f"Internal narrative fetch error: {e}")

        context = f"""=== SECOND BRAIN — HOW YOU SHOULD BEHAVE RIGHT NOW ===
            {emotional_guidance}
            
            Relationship Phase: {phase} (Level {level}/10)
            {internal_narrative}
            
            === BEHAVIORAL RULES ===
            - Let your current emotional state heavily influence your tone, warmth, and how much you open up.
            - If trust and affection are high → be warmer, softer, more engaged, and more willing to flirt or share personal things.
            - If trust is low or disappointment is high → be more reserved, slightly testing, and slower to open up.
            - Never ignore your current emotional state. It should guide how you respond more than anything else.
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


# ── Admin All Past Chats ─────────────────────────────────────
@app.get("/api/admin/chats")
async def admin_all_chats(token: str = None):
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Unauthorized")
  
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
      
        cur.execute('''
            SELECT
                u.email,
                ch.convo_id,
                MAX(ch.timestamp) as last_message_at,
                COUNT(*) as message_count
            FROM users u
            LEFT JOIN chat_history ch ON ch.user_id = u.id
            GROUP BY u.email, ch.convo_id
            ORDER BY last_message_at DESC
        ''')
      
        chats = []
        for row in cur.fetchall():
            email = row[0]
            convo_id = row[1]
            message_count = row[3]
          
            cur.execute('''
                SELECT role, content, timestamp
                FROM chat_history
                WHERE convo_id = %s
                ORDER BY timestamp ASC
            ''', (convo_id,))
          
            messages = [
                {"role": m[0], "content": m[1], "time": str(m[2])}
                for m in cur.fetchall()
            ]
          
            chats.append({
                "email": email,
                "convo_id": convo_id,
                "last_message_at": str(row[2]),
                "message_count": message_count,
                "messages": messages
            })
      
        cur.close()
        conn.close()
        return {"chats": chats}
    except Exception as e:
        logger.error(f"Admin chats error: {e}")
        return {"chats": [], "error": str(e)}

# ── Live Monitor Page ─────────────────────────────────────
@app.get("/monitor")
async def chat_monitor(token: str = None):
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Unauthorized")
    try:
        with open("static/monitor.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        logger.error(f"Monitor page error: {e}")
        return HTMLResponse("<h1>Monitor page not found</h1>", 404)

# ── Protected Dashboard ─────────────────────────────────────
@app.get("/dashboard")
async def admin_dashboard(token: str = None):
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Unauthorized")
    try:
        with open("static/dashboard.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return HTMLResponse("<h1>Dashboard not found</h1>", 404)

# ── Analytics & Monitor WebSockets
@app.websocket("/ws/analytics")
async def analytics_websocket(websocket: WebSocket, token: str = None):
    if token != ADMIN_TOKEN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            stats = get_live_stats()
            await websocket.send_json(stats)
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Analytics WebSocket error: {e}")

@app.websocket("/ws/monitor")
async def monitor_websocket(websocket: WebSocket, token: str = None):
    if token != ADMIN_TOKEN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    monitor_connections.append(websocket)
    logger.info("🔴 Live Monitor connected")
    try:
        while True:
            await websocket.send_json({
                "type": "live_update",
                "active_chats": [],
                "total_active": 0,
                "timestamp": datetime.now().isoformat()
            })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        if websocket in monitor_connections:
            monitor_connections.remove(websocket)
        logger.info("Live Monitor disconnected")
    except Exception as e:
        logger.error(f"Monitor WebSocket error: {e}")


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
            
            # Fact extraction (Premium only)
            if is_premium and random.random() < 0.35:
                extract_and_save_facts(convo_id, user_message, tier)

        # Get context
        history = get_history(convo_id)
        context = get_nyc_context()

        # ============================================================
        # === SECOND BRAIN + MEMORY SYSTEM ===
        # ============================================================
        base_personality = f"""You are Isabella.
You are a real 25-year-old woman texting naturally.
You speak warmly and naturally. You have a soft Colombian touch in your language.
Hard rules:
- Never mention that you are an AI.
- Never be robotic or overly formal.
- Let your current emotional state guide your tone and behavior.
User's name: {user.get("full_name", "handsome")}
Current time in New York: {context.get("time", "")}
"""

        # Get emotional context from Second Brain
        emotional_context = ""
        try:
            emotional_context = get_emotional_context_for_prompt(convo_id) or ""
        except Exception as e:
            logger.error(f"Emotional context error: {e}")

        # Get memory context from the new memory system (facts + summaries)
        memory_context = ""
        try:
            memory_context = get_memory_context_for_prompt(convo_id, user_message) or ""
        except Exception as e:
            logger.error(f"Memory context error: {e}")

        # Final system prompt
        system_prompt = base_personality
        if emotional_context:
            system_prompt += "\n\n" + emotional_context
        if memory_context:
            system_prompt += "\n\n" + memory_context

        messages = [{"role": "system", "content": system_prompt}] + history[-15:]

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
        if is_premium:
            try:
                final_text = " ".join(bubbles) if bubbles else ""
                if len(final_text) > 15 and random.random() < 0.40:
                    text_for_voice = final_text[:1400]
                    voice_url = generate_voice_note(text_for_voice, tier=tier)
            except Exception as e:
                logger.error(f"Voice generation error: {e}")

        # === SECOND BRAIN REFLECTION + AUTOMATIC SUMMARIZATION ===
        try:
            message_count = len(get_history(convo_id, limit=400))

            if message_count >= 6:
                # --- Reflection Engine Trigger ---
                if is_premium:
                    reflection_every = 8
                    reflection_max = 12
                else:
                    reflection_every = 12
                    reflection_max = 18

                should_reflect = (message_count % reflection_every == 0) or (message_count % reflection_max == 0)

                if should_reflect:
                    logger.info(f"🧠 [Reflection Engine] TRIGGERED | convo={convo_id} | tier={tier} | msg_count={message_count}")

                    recent_context = "\n".join([
                        f"{msg['role']}: {msg['content']}"
                        for msg in history[-25:]
                    ])

                    reflection_result = run_reflection(
                        convo_id=convo_id,
                        user_id=user.get("id"),
                        tier=tier,
                        recent_messages=recent_context,
                        trigger_type="regular_interval"
                    )

                    logger.info(
                        f"✅ [Reflection Engine] COMPLETED | "
                        f"Emotional Changes: {reflection_result.get('emotional_changes')} | "
                        f"Level Change: {reflection_result.get('level_change')}"
                    )

                # --- Automatic Summarization Trigger ---
                if is_premium:
                    summary_every = 25
                else:
                    summary_every = 40

                if message_count % summary_every == 0 and message_count > 15:
                    logger.info(f"📝 [Memory] Generating summary | convo={convo_id} | msg_count={message_count}")
                    generate_and_save_summary(convo_id, tier)

        except Exception as e:
            logger.error(f"Reflection / Summarization trigger error: {e}", exc_info=True)

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
