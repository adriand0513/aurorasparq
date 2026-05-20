# main.py - Clean & Stable Isabella Chatbot
import os
import logging
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Isabella Chatbot")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Debug on startup
logger.info(f"Server started at {datetime.now()}")
logger.info(f"Current dir: {os.getcwd()}")
if os.path.exists("static"):
    logger.info(f"Static contents: {os.listdir('static')}")

# ====================== ROUTES ======================

@app.get("/")
async def home():
    try:
        with open("static/chat.html", "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response
    except FileNotFoundError:
        return HTMLResponse("<h1 style='color:white;text-align:center;margin-top:100px;'>chat.html not found in static folder</h1>", 404)
    except Exception as e:
        logger.error(f"Homepage error: {e}")
        return HTMLResponse("<h1>Server Error</h1>", 500)


@app.post("/api/reply")
async def generate_reply(body: Dict[str, str] = Body(...)):
    convo_id = body.get("convo_id")
    user_message = body.get("message", "").strip()

    logger.info(f"📥 Reply request | convo={convo_id} | message='{user_message[:100]}'")

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
        log_prefix = f"Convo {convo_id}"
        context = get_nyc_context()

        # Save user message
        if user_message:
            save_message(convo_id, {"role": "user", "content": user_message})
            logger.info("💾 User message saved to memory")

        # Get history (now includes latest message)
        history = get_history(convo_id)
        if len(history) > 40:
            history = history[-40:]

        # Silence detector
        time_gap_minutes = 0
        silence_note = ""
        if history:
            last_user = None
            for msg in reversed(history):
                if msg.get("role") == "user":
                    last_user = msg
                    break
            if last_user and "timestamp" in last_user:
                try:
                    last_time = datetime.fromisoformat(str(last_user["timestamp"]).replace("Z", "+00:00"))
                    time_gap_minutes = int((datetime.now(ZoneInfo("UTC")) - last_time).total_seconds() / 60)
                    if time_gap_minutes > 60:
                        silence_note = "The user just came back after a while. Respond naturally."
                except:
                    pass

        # Memory & Relationship
        relevant_facts = get_relevant_facts(convo_id, limit=5)
        rel_level = get_relationship_level(convo_id)
        pet_name = get_pet_name(convo_id)

        memory_summary = ""
        if relevant_facts and time_gap_minutes < 180:
            memory_summary = "Key things you remember about him: " + " | ".join(relevant_facts[:4])

        # === Use prompt.py ===
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

        # Build messages for Grok
        recent_history = history[-14:] if time_gap_minutes > 90 else history[-22:]
        messages = [{"role": "system", "content": system_prompt}] + recent_history

        # Call Grok
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

        resp = requests.post(XAI_API_BASE, headers=headers, json=data, timeout=90)
        resp.raise_for_status()
        raw_reply = resp.json()["choices"][0]["message"]["content"].strip()

        reply = clean_reply(raw_reply)
        bubbles = split_into_bubbles(reply)

        voice_note = ""
        # Optional voice note logic (you can keep or remove)
        # if bubbles and random.random() < 0.2:
        #     try:
        #         voice_note = generate_voice_note(bubbles[-1])
        #     except:
        #         pass

        # Save assistant replies
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble})

        logger.info(f"✅ Generated {len(bubbles)} bubbles")
        return {"replies": bubbles, "voice_note": voice_note}

    except Exception as e:
        logger.error(f"💥 Error in generate_reply: {e}", exc_info=True)
        return {"replies": ["Sorry, I'm having trouble thinking right now..."], "voice_note": ""}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
