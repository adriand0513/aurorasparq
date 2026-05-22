# main.py - Isabella Chatbot (Final - Auth + Analytics + Archetypes)
import os
import re
import time
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from typing import Dict, List
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
import uvicorn
import asyncio

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# Import all modules
from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS, ADMIN_TOKEN
)
from prompt import get_system_prompt
from postprocess import clean_reply
from memory import (
    get_history, save_message, get_relevant_facts,
    get_relationship_level, get_pet_name
)
from analytics import log_event, get_live_stats
from auth import register_user, authenticate_user, create_access_token, get_current_user
from archetype import detect_archetype   # New

logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Isabella Chatbot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Guards ─────────────────────────────────────
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 4.5
convo_rate_limits = defaultdict(list)

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


# ── Protected Dashboard ─────────────────────────────────────
@app.get("/dashboard")
async def admin_dashboard(token: str = None):
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Unauthorized - Invalid admin token")
    try:
        with open("static/dashboard.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return HTMLResponse("<h1>Dashboard not found</h1>", 404)


# ── Analytics WebSocket ─────────────────────────────────────
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
        logger.error(f"WebSocket error: {e}")


# ── Protected Chat Route with Archetype Detection ─────────────────────────────────────
@app.post("/api/reply")
async def generate_reply(body: dict = Body(...), user: dict = Depends(get_current_user)):
    start_time = time.time()
    
    convo_id = body.get("convo_id")
    user_message = body.get("message", "").strip()

    logger.info(f"📥 /api/reply | user={user['id']} | convo={convo_id} | msg='{user_message[:80]}'")

    if not convo_id:
        raise HTTPException(400, "convo_id required")

    # Cooldown & Rate Limit
    now = time.time()
    if now - last_reply_time.get(convo_id, 0) < REPLY_COOLDOWN_SECONDS:
        return JSONResponse({"replies": []}, status_code=200)

    last_reply_time[convo_id] = now

    if is_rate_limited(convo_id):
        return JSONResponse({"replies": []}, status_code=200)

    try:
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message})

        history = get_history(convo_id)

        # Archetype Detection (runs periodically)
        if len(history) >= 5 and len(history) % 7 == 0:
            try:
                arch = await detect_archetype(convo_id, history)
                log_event("archetype_detected", convo_id, user_id=user["id"], 
                         metadata={
                             "archetype": arch.get("archetype"),
                             "confidence": arch.get("confidence"),
                             "summary": arch.get("summary")
                         })
            except Exception as e:
                logger.warning(f"Archetype detection failed: {e}")

        context = get_nyc_context()

        system_prompt = get_system_prompt(
            user_name=user.get("full_name"),
            current_time=context.get("time", ""),
            weather=context.get("weather", "")
        )

        relevant_facts = get_relevant_facts(convo_id, limit=5)
        rel_level = get_relationship_level(convo_id)
        pet_name = get_pet_name(convo_id)

        if relevant_facts:
            system_prompt += f"\n\nKey facts about him: {' | '.join(relevant_facts[:4])}"
        system_prompt += f"\nCurrent relationship closeness: Level {rel_level}/10."
        if pet_name:
            system_prompt += f" You sometimes call him '{pet_name}'."

        messages = [{"role": "system", "content": system_prompt}] + history[-20:]

        # Call Grok
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
        bubbles = split_into_bubbles(clean_reply(raw_reply))

        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble})

        duration_ms = int((time.time() - start_time) * 1000)
        log_event("response_generated", convo_id, user_id=user["id"], duration_ms=duration_ms)

        logger.info(f"✅ Generated {len(bubbles)} bubbles | Latency: {duration_ms}ms")
        return {"replies": bubbles}

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_event("error", convo_id, user_id=user["id"], metadata={"error": str(e)}, duration_ms=duration_ms)
        logger.error(f"💥 CRITICAL ERROR: {e}", exc_info=True)
        return {"replies": ["Sorry, I'm having trouble responding right now..."]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
