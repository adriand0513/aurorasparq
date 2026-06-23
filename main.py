# main.py - Isabella Chatbot (Final PostgreSQL + Permanent JSON Fix)
import os
import re
import time
import logging
import psycopg2
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from typing import Dict, List
from collections import defaultdict
import json
import stripe
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
import uvicorn
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler

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
    XAI_TEMPERATURE, XAI_MAX_TOKENS, ADMIN_TOKEN, DATABASE_URL
)
from prompt import get_system_prompt
from postprocess import clean_reply
from memory import (
    get_history,
    save_message,
    get_relevant_facts,
    get_relationship_level,
    get_pet_name,
    extract_and_save_facts,
    generate_and_save_summary
)
from analytics import log_event, get_live_stats
from auth import register_user, authenticate_user, create_access_token, get_current_user, get_db_connection, ensure_users_table, update_user_subscription
from relationship_state import (
    get_relationship_state,
    update_relationship_state,
    add_narrative_moment
)
from payment import router as payment_router
from voice import generate_voice_note
from proactive import should_send_proactive, generate_proactive_message

scheduler = BackgroundScheduler()

logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Isabella Chatbot", default_response_class=DateTimeJSONResponse)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(payment_router)

AUDIO_DIR = Path("/var/data/audio")

ensure_users_table()

# ── Guards ─────────────────────────────────────
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 4.5
convo_rate_limits = defaultdict(list)
monitor_connections: list = []

def is_rate_limited(convo_id: str, max_per_minute: int = 20) -> bool:
    now = time.time()
    convo_rate_limits[convo_id] = [t for t in convo_rate_limits[convo_id] if now - t < 60]
    convo_rate_limits[convo_id].append(now)
    return len(convo_rate_limits[convo_id]) > max_per_minute

def get_all_ultimate_users():
    """
    TODO: Implement this function to return Ultimate users with:
    user_id, convo_id, last_message_time
    """
    return []  # Placeholder - implement later

def run_proactive_messages():
    print("🔄 Running proactive message check...")

    ultimate_users = get_all_ultimate_users()
    print(f"Found {len(ultimate_users)} ultimate users")

    for user in ultimate_users:
        try:
            convo_id = user["convo_id"]
            last_message_time = user["last_message_time"]
            tier = "ultimate"

            hours_since = (datetime.datetime.now() - last_message_time).total_seconds() / 3600
            print(f"User {user['user_id']} | Hours since last message: {hours_since:.2f}")

            if should_send_proactive(convo_id, last_message_time, tier):
                print(f"✅ Sending proactive message to user {user['user_id']}")
                
                message = generate_proactive_message(
                    convo_id=convo_id,
                    tier=tier,
                    generate_llm_response_func=generate_llm_response,
                    postprocess_func=postprocess
                )

                if message:
                    save_message(
                        convo_id=convo_id,
                        message={"role": "assistant", "content": message},
                        user_id=user["user_id"]
                    )
                    print(f"[PROACTIVE] Message sent successfully to user {user['user_id']}")
                else:
                    print(f"⚠️ No message generated for user {user['user_id']}")
            else:
                print(f"⏭️ Skipped user {user['user_id']} (time condition not met)")

        except Exception as e:
            logger.error(f"Error processing proactive message for user {user.get('user_id')}: {e}")

def get_all_ultimate_users():
    """
    Returns Ultimate users with user_id, convo_id, and last_message_time.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                u.id AS user_id,
                CONCAT('user_', u.id) AS convo_id,
                COALESCE(MAX(ch.timestamp), u.created_at) AS last_message_time
            FROM users u
            LEFT JOIN chat_history ch ON ch.user_id = u.id
            WHERE LOWER(COALESCE(u.subscription_tier, 'free')) = 'ultimate'
            GROUP BY u.id, u.created_at
            ORDER BY last_message_time DESC
        """)

        users = []
        for row in cur.fetchall():
            users.append({
                "user_id": row[0],
                "convo_id": row[1],
                "last_message_time": row[2]
            })

        cur.close()
        conn.close()
        return users

    except Exception as e:
        logger.error(f"Error fetching ultimate users: {e}")
        return []

# ── NYC Context ─────────────────────────────────
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

# ── split_into_bubbles ─────────────────────────────
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
    
# ── Test Proactive Messages (Admin Only) ─────────────────────────────
@app.get("/api/test/proactive")
async def test_proactive_messages(token: str = None):
    """
    Manually trigger the proactive message check for testing.
    Only accessible with the admin token.
    """
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")

    try:
        run_proactive_messages()
        return {"message": "Proactive message check triggered successfully"}
    except Exception as e:
        logger.error(f"Test proactive error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/audio/{filename}")
async def get_audio(filename: str):
    if not filename.endswith(".mp3") or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid file")

    file_path = AUDIO_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=filename
    )

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
    is_premium = tier in ["premium", "ultimate"]

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
                    "Upgrade to Premium or Ultimate if you want to keep talking to me today ✨"
                ]
            }

    now = time.time()
    if now - last_reply_time.get(convo_id, 0) < REPLY_COOLDOWN_SECONDS:
        return {"replies": []}
    last_reply_time[convo_id] = now

    if is_rate_limited(convo_id):
        return {"replies": []}

    try:
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message}, user_id=user.get("id"))

            if tier == "ultimate":
                extract_and_save_facts(convo_id, user_message, tier)
            elif tier == "premium":
                import random
                if random.randint(1, 4) == 1:
                    extract_and_save_facts(convo_id, user_message, tier)

        state = get_relationship_state(convo_id)
        history = get_history(convo_id)

        def sanitize_for_json(data):
            if isinstance(data, list):
                return [sanitize_for_json(item) for item in data]
            if isinstance(data, dict):
                return {k: sanitize_for_json(v) for k, v in data.items()}
            if isinstance(data, datetime):
                return data.isoformat()
            return data

        clean_history = sanitize_for_json(history)
        context = get_nyc_context()

        system_prompt = get_system_prompt(
            user_name=user.get("full_name"),
            current_time=context.get("time", ""),
            state=state,
            tier=tier
        )

        relevant_facts = get_relevant_facts(convo_id, limit=3)
        if relevant_facts:
            system_prompt += f"\n\nImportant things about him: {' | '.join(relevant_facts)}"

        rel_level = state.get("level", 1) if state else 1
        pet_name = state.get("pet_name") if state else None
        system_prompt += f"\nCurrent relationship level: {rel_level}/10."
        if pet_name:
            system_prompt += f" You sometimes call him '{pet_name}'."

        messages = [{"role": "system", "content": system_prompt}] + clean_history[-12:]

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

        # ==================== VOICE GENERATION ====================
        voice_url = None
        
        if tier in ["premium", "ultimate"]:
            try:
                final_text = " ".join(bubbles) if bubbles else ""
                if len(final_text) > 15:                    # ← Make sure this is not too high
                    voice_url = generate_voice_note(final_text, tier=tier)
            except Exception as e:
                logger.error(f"Voice generation error: {e}")
        
        response = {"replies": bubbles}
        
        if voice_url:
            response["voice_message"] = {"voice_url": voice_url}

return response
        
        # ==================== RESPONSE ====================
        response = {"replies": bubbles}
        
        # Send voice as a separate message if available
        if voice_url:
            response["voice_message"] = {"voice_url": voice_url}
        
        return response

        # ==================== CONVERSATION SUMMARIZATION ====================
        if tier == "ultimate":
            try:
                message_count = len(get_history(convo_id, limit=300))
                if message_count % 25 == 0 and message_count > 20:
                    generate_and_save_summary(convo_id, tier)
            except Exception as e:
                logger.error(f"Summarization trigger error: {e}")

        duration_ms = int((time.time() - start_time) * 1000)
        log_event("response_generated", convo_id, user_id=user.get("id"), duration_ms=duration_ms)

        emotional_delta = 1 if any(word in user_message.lower() for word in ["miss", "want", "love", "beautiful", "hot", "sexy"]) else 0

        update_relationship_state(
            convo_id,
            emotional_delta=emotional_delta,
            new_mood="flirty" if emotional_delta > 0 else None,
            note=f"User said: {user_message[:120]}"
        )

        if len(user_message) > 25:
            add_narrative_moment(
                convo_id,
                f"User: {user_message[:100]}",
                moment_type="user_shared",
                emotional_tag="flirty" if emotional_delta > 0 else "normal",
                importance=6
            )

        response = {"replies": bubbles}
        if voice_url:
            response["voice_url"] = voice_url

        return response

    except Exception as e:
        logger.error(f"💥 Unexpected error in /api/reply: {e}", exc_info=True)
        return {"replies": []}


# Start background scheduler
scheduler.add_job(run_proactive_messages, 'interval', hours=6)
scheduler.start()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
