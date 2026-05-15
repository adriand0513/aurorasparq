# main.py - Isabella Chatbot Server (COMPLETE)
import os
import re
import random
import time
import logging
import csv
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from typing import Dict, List
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Config imports
from config import (
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    XAI_API_KEY, XAI_API_BASE, XAI_MODEL,
    XAI_TEMPERATURE, XAI_MAX_TOKENS
)
from prompt import get_system_prompt
from postprocess import clean_reply
from voice import generate_voice_note
from analytics import router as analytics_router

# Memory System
from memory import (
    create_or_get_user,
    get_history,
    save_message,
    get_relevant_facts,
    get_relationship_level,
    get_pet_name,
    update_relationship,
    summarize_recent_chat,
)

logger.info(f"Starting Isabella server - {datetime.now().isoformat()}")

app = FastAPI(title="Aurora Sparq")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(analytics_router)

# Guards
last_reply_time = defaultdict(float)
REPLY_COOLDOWN_SECONDS = 6

convo_rate_limits = defaultdict(list)

def is_rate_limited(user_email: str, max_per_minute: int = 20) -> bool:
    now = time.time()
    convo_rate_limits[user_email] = [t for t in convo_rate_limits[user_email] if now - t < 60]
    convo_rate_limits[user_email].append(now)
    return len(convo_rate_limits[user_email]) > max_per_minute

# CSV Logging
CSV_LOG_FILE = "isabella_private_logs.csv"

def init_csv_log():
    if not os.path.exists(CSV_LOG_FILE):
        with open(CSV_LOG_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "user_email", "user_message", "isabella_reply", "emotion", "voice_note_generated"])
        logger.info("Created private CSV log file")

init_csv_log()

# Emotion Detection
EMOTION_MAP = {
    "flirty": ["sexy", "horny", "kiss", "touch", "want you", "miss you"],
    "playful": ["lol", "haha", "tease", "funny"],
    "warm": ["sweet", "cute", "smile", "happy"],
    "seductive": ["body", "curves", "crave", "feel"],
    "teasing": ["trouble", "naughty", "careful"],
    "neutral": []
}

def detect_emotion(text: str) -> str:
    if not text: return "neutral"
    text_lower = text.lower()
    for emotion, keywords in EMOTION_MAP.items():
        if any(kw in text_lower for kw in keywords):
            return emotion
    return "neutral"

# NYC Context
def get_nyc_context() -> Dict[str, str]:
    nyc_tz = ZoneInfo("America/New_York")
    now_nyc = datetime.now(nyc_tz)
    time_str = now_nyc.strftime("%I:%M %p on %A, %B %d")
    try:
        r = requests.get("https://wttr.in/NYC?format=%c+%t+%w", timeout=5)
        if r.status_code == 200:
            parts = r.text.strip().split()
            weather = f"{parts[0]} {parts[1]}, wind {parts[2]}" if len(parts) >= 3 else r.text.strip()
        else:
            weather = "cool and clear"
    except:
        weather = "chilly evening"
    return {"time": time_str, "weather": weather}

# Split replies
def split_into_bubbles(text: str) -> List[str]:
    if not text.strip(): return ["..."]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        paragraphs = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence: continue
            if current and random.random() < 0.45 and len(paragraphs) < 3:
                paragraphs.append(current.strip())
                current = sentence
            else:
                current += " " + sentence if current else sentence
        if current:
            paragraphs.append(current.strip())
    return [p.strip() for p in paragraphs if p.strip()]

# ==================== ROUTES ====================

@app.get("/")
async def home():
    return RedirectResponse(url="/chat")

@app.get("/chat")
async def chat_page():
    try:
        with open("static/chat.html", "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response
    except FileNotFoundError:
        logger.error("chat.html not found!")
        return HTMLResponse("<h1>chat.html not found</h1>", status_code=500)

@app.post("/api/login")
async def login_user(body: Dict[str, str] = Body(...)):
    email = body.get("email", "").strip().lower()
    first_name = body.get("first_name", "").strip()
    last_name = body.get("last_name", "").strip()

    logger.info(f"Login attempt: {email}")

    if not email or not first_name or not last_name:
        raise HTTPException(400, "All fields are required")

    try:
        create_or_get_user(email, first_name, last_name)
        logger.info(f"✅ User created/logged in: {email}")
        return {"success": True, "email": email}
    except Exception as e:
        logger.error(f"Login failed for {email}: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create user profile")

@app.post("/api/reply")
async def generate_reply(body: Dict[str, str] = Body(...)):
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")

    now = time.time()
    if now - last_reply_time[email] < REPLY_COOLDOWN_SECONDS:
        return JSONResponse({"replies": [], "voice_note": ""}, status_code=200)

    last_reply_time[email] = now
    if is_rate_limited(email):
        return JSONResponse({"replies": [], "voice_note": ""}, status_code=200)

    # Full reply logic
    context = get_nyc_context()
    history = get_history(email)
    if len(history) > 40:
        history = history[-40:]

    silence_note = ""
    if history:
        last_user = next((msg for msg in reversed(history) if msg.get("role") == "user"), None)
        if last_user and "timestamp" in last_user:
            try:
                last_time = datetime.fromisoformat(str(last_user["timestamp"]).replace("Z", "+00:00"))
                gap = int((datetime.now(ZoneInfo("UTC")) - last_time).total_seconds() / 60)
                if gap > 60:
                    silence_note = "The user just came back after some time. Respond naturally."
            except:
                pass

    relevant_facts = get_relevant_facts(email, limit=5)
    rel_level = get_relationship_level(email)
    pet_name = get_pet_name(email)

    memory_summary = "Key things you remember about him: " + " | ".join(relevant_facts[:4]) if relevant_facts else ""

    system_prompt = get_system_prompt(
        user_name=None,
        current_time=context["time"],
        weather=context["weather"]
    )
    if memory_summary:
        system_prompt += f"\n\n{memory_summary}"
    system_prompt += f"\nCurrent relationship closeness: Level {rel_level}/10."
    if pet_name:
        system_prompt += f" You sometimes call him '{pet_name}' naturally."
    if silence_note:
        system_prompt += f"\n\n{silence_note}"

    messages = [{"role": "system", "content": system_prompt}] + history[-22:]

    # Call xAI
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": XAI_MODEL,
        "messages": messages,
        "temperature": XAI_TEMPERATURE,
        "max_tokens": XAI_MAX_TOKENS,
    }

    try:
        resp = requests.post(XAI_API_BASE, headers=headers, json=data, timeout=90)
        resp.raise_for_status()
        raw_reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"XAI error: {e}")
        return JSONResponse({"replies": ["Hey there 😊"], "voice_note": ""}, status_code=200)

    reply = clean_reply(raw_reply)
    bubbles = split_into_bubbles(reply)

    voice_note = ""
    if any(kw in reply.lower() for kw in ["miss", "love", "kiss", "horny", "sexy"]):
        try:
            if random.random() < 0.4 and bubbles:
                voice_note = generate_voice_note(bubbles[-1])
        except:
            pass

    for bubble in bubbles:
        save_message(email, {"role": "assistant", "content": bubble, "voice_note": voice_note})

    return {"replies": bubbles, "voice_note": voice_note}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
