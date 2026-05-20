# main.py - Isabella Chatbot (Complete & Stable)
import os
import re
import random
import time
import logging
import csv
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from typing import Dict, List
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

# Import your modules
from config import (
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS
)
from prompt import get_system_prompt
from postprocess import clean_reply
from memory import (
    get_history, save_message, get_relevant_facts,
    get_relationship_level, get_pet_name, summarize_recent_chat
)
from relationship import update_relationship

logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Isabella Chatbot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Guards ─────────────────────────────────────
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 3.0

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
    # Simple split for now
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

# ── Routes ─────────────────────────────────────
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
        return HTMLResponse("<h1>Server Error - chat.html not found</h1>", 500)

@app.post("/api/reply")
async def generate_reply(body: Dict[str, str] = Body(...)):
    convo_id = body.get("convo_id")
    user_message = body.get("message", "").strip()

    logger.info(f"📥 Reply request | convo={convo_id} | msg='{user_message[:80]}'")

    if not convo_id:
        raise HTTPException(400, "convo_id required")

    # Cooldown
    now = time.time()
    if now - last_reply_time.get(convo_id, 0) < REPLY_COOLDOWN_SECONDS:
        return JSONResponse({"replies": [], "voice_note": ""}, status_code=200)

    last_reply_time[convo_id] = now

    if is_rate_limited(convo_id):
        return JSONResponse({"replies": [], "voice_note": ""}, status_code=200)

    try:
        context = get_nyc_context()

        # Save user message
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message})

        history = get_history(convo_id)
        if len(history) > 40:
            history = history[-40:]

        # Build prompt
        system_prompt = get_system_prompt(
            user_name=None,
            current_time=context["time"],
            weather=context["weather"]
        )

        # Add memory
        relevant_facts = get_relevant_facts(convo_id, limit=5)
        rel_level = get_relationship_level(convo_id)
        pet_name = get_pet_name(convo_id)

        if relevant_facts:
            system_prompt += f"\n\nKey facts: {' | '.join(relevant_facts[:4])}"
        system_prompt += f"\nRelationship level: {rel_level}/10"
        if pet_name:
            system_prompt += f" You call him '{pet_name}' sometimes."

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

        # Save replies
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble})

        logger.info(f"✅ Generated {len(bubbles)} replies")
        return {"replies": bubbles, "voice_note": ""}

    except Exception as e:
        logger.error(f"💥 ERROR in generate_reply: {e}", exc_info=True)
        return {"replies": ["Sorry, I'm having trouble responding right now..."], "voice_note": ""}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
