# main.py - MINIMAL WORKING VERSION
import os
import re
import random
import time
import logging
from datetime import datetime
from typing import Dict, List
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Aurora Sparq")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Simple Guards ─────────────────────────────────────
last_reply_time = defaultdict(float)

# ── Routes ────────────────────────────────────────────
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
        return HTMLResponse("<h1>chat.html not found in static folder</h1>", status_code=500)
    except Exception as e:
        logger.error(f"Error serving chat: {e}")
        return HTMLResponse(f"<h1>Error: {e}</h1>", status_code=500)

@app.post("/api/login")
async def login_user(body: Dict[str, str] = Body(...)):
    email = body.get("email", "").strip().lower()
    first_name = body.get("first_name", "").strip()
    last_name = body.get("last_name", "").strip()

    logger.info(f"Login attempt: {email}")

    if not email or not first_name or not last_name:
        raise HTTPException(400, "All fields required")

    # TODO: Connect to memory.py later
    logger.info(f"✅ Login accepted for {email}")
    return {"success": True, "email": email}

@app.post("/api/reply")
async def generate_reply(body: Dict[str, str] = Body(...)):
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")

    # Prevent duplicate rapid replies
    now = time.time()
    if now - last_reply_time[email] < REPLY_COOLDOWN_SECONDS:
        return JSONResponse({"replies": [], "voice_note": ""}, status_code=200)

    last_reply_time[email] = now
    if is_rate_limited(email):
        return JSONResponse({"replies": ["Slow down baby... 😏"], "voice_note": ""}, status_code=200)

    try:
        context = get_nyc_context()
        history = get_history(email)
        if len(history) > 50:
            history = history[-50:]

        # Silence / Return detection
        silence_note = ""
        if history:
            last_user_msg = next((msg for msg in reversed(history) if msg.get("role") == "user"), None)
            if last_user_msg and "timestamp" in last_user_msg:
                try:
                    last_time = datetime.fromisoformat(str(last_user_msg["timestamp"]).replace("Z", "+00:00"))
                    minutes_ago = int((datetime.now(ZoneInfo("UTC")) - last_time).total_seconds() / 60)
                    if minutes_ago > 90:
                        silence_note = "The user has been away for a while. Greet them warmly and flirt a little."
                except:
                    pass

        # Build rich context
        relevant_facts = get_relevant_facts(email, limit=6)
        rel_level = get_relationship_level(email)
        pet_name = get_pet_name(email)

        memory_summary = ""
        if relevant_facts:
            memory_summary = "Important things you know about him: " + " | ".join(relevant_facts[:5])

        system_prompt = get_system_prompt(
            user_name=None,
            current_time=context["time"],
            weather=context["weather"]
        )

        if memory_summary:
            system_prompt += f"\n\n{memory_summary}"
        system_prompt += f"\nCurrent relationship level: {rel_level}/10"
        if pet_name:
            system_prompt += f"\nYou sometimes call him '{pet_name}' affectionately."

        if silence_note:
            system_prompt += f"\n\n{silence_note}"

        # Prepare messages for Grok
        messages = [{"role": "system", "content": system_prompt}] + history[-25:]

        # Call xAI Grok
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": XAI_MODEL,
            "messages": messages,
            "temperature": XAI_TEMPERATURE,
            "max_tokens": XAI_MAX_TOKENS,
        }

        resp = requests.post(XAI_API_BASE, headers=headers, json=data, timeout=80)
        resp.raise_for_status()
        raw_reply = resp.json()["choices"][0]["message"]["content"].strip()

        reply = clean_reply(raw_reply)
        bubbles = split_into_bubbles(reply)

        # Voice note logic
        voice_note = ""
        emotional = any(word in reply.lower() for word in ["miss", "love", "kiss", "horny", "sexy", "touch", "want", "crave"])
        if emotional and random.random() < 0.42 and bubbles:
            try:
                voice_note = generate_voice_note(bubbles[-1])
            except Exception as e:
                logger.warning(f"Voice note failed: {e}")

        # Save to memory
        for bubble in bubbles:
            save_message(email, {
                "role": "assistant",
                "content": bubble,
                "voice_note": voice_note
            })

        # Relationship & summarization
        if emotional and random.random() < 0.4:
            update_relationship(email, delta=1)

        if len(history) % 15 == 0 and len(history) > 20:
            summarize_recent_chat(email)

        return {"replies": bubbles, "voice_note": voice_note}

    except Exception as e:
        logger.error(f"Reply generation failed for {email}: {e}", exc_info=True)
        return JSONResponse({
            "replies": ["Sorry baby, I'm a little shy right now... Can you say that again? 😘"],
            "voice_note": ""
        }, status_code=200)
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
