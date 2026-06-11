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

from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
import uvicorn
import asyncio

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
    get_history, save_message, get_relevant_facts,
    get_relationship_level, get_pet_name
)
from analytics import log_event, get_live_stats
from auth import register_user, authenticate_user, create_access_token, get_current_user, get_db_connection, ensure_users_table
from archetype import detect_archetype

from relationship_state import (
    get_relationship_state,
    update_relationship_state,
    add_narrative_moment
)

from payment import router as payment_router


logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Isabella Chatbot", default_response_class=DateTimeJSONResponse)
app.mount("/static", StaticFiles(directory="static"), name="static")

ensure_users_table()

app.include_router(payment_router)
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
    """Return daily message usage for the current user"""
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

        return {
            "daily_count": daily_count,
            "daily_limit": 30 if user.get("subscription_tier", "free").lower() == "free" else 9999,
            "remaining": max(0, 30 - daily_count) if user.get("subscription_tier", "free").lower() == "free" else "unlimited"
        }
    except Exception as e:
        logger.error(f"Usage endpoint error: {e}")
        return {"daily_count": 0, "daily_limit": 30, "remaining": 30}

@app.get("/success")
async def payment_success(session_id: str = None):
    try:
        # Optional: Verify the session if you want
        if session_id:
            # You can add verification here later
            pass
        with open("static/success.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Upgrade Successful! Redirecting...</h1><script>setTimeout(() => window.location.href='/chat', 2000);</script>")


# ── Admin All Past Chats ─────────────────────────────────────
@app.get("/api/admin/chats")
async def admin_all_chats(token: str = None):
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Unauthorized")
   
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
       
        # Get all chats summary
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
           
            # Fetch ALL messages (no LIMIT) or a high reasonable limit
            cur.execute('''
                SELECT role, content, timestamp
                FROM chat_history
                WHERE convo_id = %s
                ORDER BY timestamp ASC
            ''', (convo_id,))
           
            messages = [
                {
                    "role": m[0], 
                    "content": m[1], 
                    "time": str(m[2])
                } 
                for m in cur.fetchall()
            ]
           
            chats.append({
                "email": email,
                "convo_id": convo_id,
                "last_message_at": str(row[2]),
                "message_count": message_count,
                "messages": messages   # Now returns ALL messages
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

# ── Analytics & Monitor WebSockets (unchanged for now)
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

    # ==================== TIER ENFORCEMENT (PostgreSQL) ====================
    tier = user.get("subscription_tier", "free").lower()
    is_premium = tier in ["premium", "ultimate"]

    if not is_premium:
        daily_limit = 30
        
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
                    "Hey papi 💕 You've reached your daily free message limit (30 messages). "
                    "Upgrade to Premium or Ultimate for unlimited chats with me all day ✨"
                ]
            }

    # ── Rate Limiting ─────────────────────────────────────
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

        # === Get Unified Relationship State ===
        state = get_relationship_state(convo_id)
        history = get_history(convo_id)

        # Sanitize history for xAI
        def sanitize_for_json(data):
            if isinstance(data, list):
                return [sanitize_for_json(item) for item in data]
            if isinstance(data, dict):
                return {k: sanitize_for_json(v) for k, v in data.items()}
            if isinstance(data, datetime):
                return data.isoformat()
            return data

        clean_history = sanitize_for_json(history)

        # Get NYC context
        context = get_nyc_context()

        # === Build System Prompt with Tier Awareness ===
        system_prompt = get_system_prompt(
            user_name=user.get("full_name"),
            current_time=context.get("time", ""),
            weather=context.get("weather", ""),
            state=state,
            tier=tier  # ← Tier-specific behavior
        )

        relevant_facts = get_relevant_facts(convo_id, limit=5)
        rel_level = state.get("level", 1) if state else 1
        pet_name = state.get("pet_name") if state else None

        if relevant_facts:
            system_prompt += f"\n\nKey facts about him: {' | '.join(relevant_facts[:4])}"
        system_prompt += f"\nCurrent relationship level: {rel_level}/10."
        if pet_name:
            system_prompt += f" You sometimes call him '{pet_name}'."

        messages = [{"role": "system", "content": system_prompt}] + clean_history[-12:]

        # ── Call xAI ─────────────────────────────────────
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

        duration_ms = int((time.time() - start_time) * 1000)
        log_event("response_generated", convo_id, user_id=user.get("id"), duration_ms=duration_ms)

        # === Update Unified State ===
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

        return {"replies": bubbles}

    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}", exc_info=True)
        return {"replies": []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
