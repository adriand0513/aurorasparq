# main.py - Aurora Sparq (with User Login)
import os
import re
import json
import random
import time
import logging
import csv
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from typing import Dict, List
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aurora Sparq")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Import memory (user-based)
from memory import (
    create_or_get_user,
    get_history,
    save_message,
    get_relevant_facts,
    get_relationship_level,
    get_pet_name,
    update_relationship,
    summarize_recent_chat
)

# ── Config (add your own config.py or put keys here) ─────────────────────
from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS,
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
)

from prompt import get_system_prompt
from postprocess import clean_reply
from voice import generate_voice_note

# ── Guards & Rate Limiting ───────────────────────────────────────────────
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 6

convo_rate_limits = defaultdict(list)
def is_rate_limited(identifier: str, max_per_minute: int = 15):
    now = time.time()
    convo_rate_limits[identifier] = [t for t in convo_rate_limits[identifier] if now - t < 60]
    convo_rate_limits[identifier].append(now)
    return len(convo_rate_limits[identifier]) > max_per_minute

# ── Routes ───────────────────────────────────────────────────────────────
@app.get("/")
async def home():
    return RedirectResponse(url="/chat?v=0521")  # ← Change this number when you update

@app.get("/chat")
async def chat_page():
    try:
        with open("static/chat.html", "r", encoding="utf-8") as f:
            content = f.read()
        
        response = HTMLResponse(content)
        
        # === STRONG CACHE BUSTING ===
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Surrogate-Control"] = "no-store"
        response.headers["Vary"] = "Accept-Encoding, User-Agent"
        
        return response
    except FileNotFoundError:
        return HTMLResponse("<h1>chat.html not found</h1>", status_code=404)

# ── USER LOGIN ───────────────────────────────────────────────────────────
@app.post("/api/login")
async def login_user(body: Dict = Body(...)):
    email = body.get("email", "").strip().lower()
    first_name = body.get("first_name", "").strip()
    last_name = body.get("last_name", "").strip()

    if not email or not first_name or not last_name:
        raise HTTPException(400, "All fields are required")

    create_or_get_user(email, first_name, last_name)
    logger.info(f"User logged in: {email}")

    return {"success": True, "email": email}

# ── SEND MESSAGE ─────────────────────────────────────────────────────────
@app.post("/api/send")
async def send_message(body: Dict = Body(...)):
    email = body.get("email", "").strip().lower()
    message = body.get("message", "").strip()

    if not email or not message:
        raise HTTPException(400, "email and message required")

    if is_rate_limited(email):
        raise HTTPException(429, "Slow down...")

    save_message(email, {"role": "user", "content": message})
    return {"success": True}

# ── GENERATE REPLY ───────────────────────────────────────────────────────
@app.post("/api/reply")
async def generate_reply(body: Dict = Body(...)):
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")

    # Cooldown guard
    now = time.time()
    if now - last_reply_time[email] < REPLY_COOLDOWN_SECONDS:
        return {"replies": [], "voice_note": ""}
    last_reply_time[email] = now

    if is_rate_limited(email):
        return {"replies": [], "voice_note": ""}

    # ... (your full reply generation logic here - I'll give you the full version if needed)

    # For now, a minimal version so login works:
    return {
        "replies": ["Hey there! I'm Isabella. What would you like to talk about?"],
        "voice_note": ""
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
