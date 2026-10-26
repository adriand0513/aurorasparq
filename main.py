# main.py - Aurora Sparq (Isabella chatbot)
import logging
import random
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config import FREE_DAILY_MESSAGE_LIMIT, PAID_TIERS, XAI_MAX_TOKENS, XAI_TEMPERATURE
from database import init_db
from analytics import log_event
from auth import authenticate_user, create_access_token, get_current_user, register_user, MIN_PASSWORD_LENGTH
from llm import chat_completion
from memory import (
    count_user_messages_today,
    get_history,
    get_last_voice_script,
    get_recent_text_messages,
    save_message,
    set_last_voice_script,
    VOICE_NOTE_PREFIX,
)
from payment import router as payment_router
from postprocess import clean_reply, split_into_bubbles
from voice import AUDIO_DIR, LOCAL_AUDIO_DIR, generate_voice_note, is_valid_audio_filename
from aurorasparq_brain.brain.memory.facts import (
    extract_facts_from_exchange,
    get_facts_for_prompt,
    get_or_set_sticky_activity,
)
from aurorasparq_brain.brain.memory.summaries import (
    RECENT_WINDOW,
    get_conversation_summary,
    update_conversation_summary,
)
from aurorasparq_brain.prompts.hard_rules import CRISIS_RULES, get_hard_rules
from aurorasparq_brain.prompts.personality import get_system_prompt

STATIC_DIR = Path(__file__).parent / "static"
MAX_MESSAGE_CHARS = 2000
VOICE_NOTE_CHANCE = 0.2          # premium: chance of an unprompted voice note per reply

# Crisis protocol (required by NY GBL Art. 47 and California SB 243)
CRISIS_PHRASES = (
    "kill myself", "killing myself", "end my life", "ending my life", "take my own life",
    "suicide", "suicidal", "want to die", "wanna die", "better off dead", "don't want to live",
    "dont want to live", "don't want to be alive", "dont want to be alive", "no reason to live",
    "hurt myself", "hurting myself", "self harm", "self-harm", "cut myself", "cutting myself",
    "overdose", "end it all",
)
SAFETY_NOTICE = (
    "If you're thinking about suicide or hurting yourself, you deserve support from a real person "
    "right now. In the US, call or text 988 (Suicide & Crisis Lifeline), any time, free and confidential. "
    "If you're in immediate danger, call 911. Outside the US: findahelpline.com"
)


def mentions_self_harm(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in CRISIS_PHRASES)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Aurora Sparq", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(payment_router)


# ── Guards ─────────────────────────────────────
REPLY_COOLDOWN_SECONDS = 4.5
MAX_REPLIES_PER_MINUTE = 20
last_reply_time = defaultdict(float)
convo_rate_limits = defaultdict(list)


def is_rate_limited(convo_id: str) -> bool:
    now = time.time()
    convo_rate_limits[convo_id] = [t for t in convo_rate_limits[convo_id] if now - t < 60]
    convo_rate_limits[convo_id].append(now)
    return len(convo_rate_limits[convo_id]) > MAX_REPLIES_PER_MINUTE


def is_paid(user: dict) -> bool:
    return (user.get("subscription_tier") or "free").lower() in PAID_TIERS


# ── Pages ─────────────────────────────────────
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _page(name: str, headers: dict = None) -> FileResponse:
    path = STATIC_DIR / name
    if not path.exists():
        raise HTTPException(404, "Page not found")
    return FileResponse(path, media_type="text/html", headers=headers)


@app.get("/")
def home():
    return _page("index.html", NO_CACHE)


@app.get("/chat")
def chat_page():
    return _page("chat.html", NO_CACHE)


@app.get("/privacy")
def privacy_page():
    return _page("privacy.html")


@app.get("/terms")
def terms_page():
    return _page("terms.html")


@app.get("/success")
def payment_success():
    return _page("success.html")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    if not is_valid_audio_filename(filename):
        raise HTTPException(status_code=404, detail="Audio not found")
    for folder in (AUDIO_DIR, LOCAL_AUDIO_DIR):
        file_path = folder / filename
        if file_path.is_file():
            return FileResponse(file_path, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio not found")


# ── Auth Routes ─────────────────────────────────────
@app.post("/auth/register")
def register(body: dict = Body(...)):
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    full_name = (body.get("full_name") or "").strip()
    if not email or "@" not in email or not password:
        raise HTTPException(400, "Email and password required")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if register_user(email, password, full_name):
        log_event("user_registered", metadata={"email": email})
        return {"message": "Registered successfully"}
    raise HTTPException(409, "Email already exists")


@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(user["id"])})
    log_event("user_login", user_id=user["id"])
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/auth/me")
def get_current_user_info(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name"),
        "subscription_tier": user.get("subscription_tier", "free"),
    }


@app.get("/api/history")
def get_chat_history(user: dict = Depends(get_current_user)):
    convo_id = f"user_{user['id']}"
    return {"convo_id": convo_id, "messages": get_history(convo_id)}


@app.get("/api/usage")
def get_usage(user: dict = Depends(get_current_user)):
    daily_count = count_user_messages_today(user["id"])
    if is_paid(user):
        return {"daily_count": daily_count, "daily_limit": 9999, "remaining": "unlimited"}
    return {
        "daily_count": daily_count,
        "daily_limit": FREE_DAILY_MESSAGE_LIMIT,
        "remaining": max(0, FREE_DAILY_MESSAGE_LIMIT - daily_count),
    }


# ── Prompt building ─────────────────────────────────────
ASKS_ABOUT_HER_DAY = (
    "what are you doing", "what're you doing", "what are u doing",
    "you up to", "what you up to", "how was your day",
    "what did you do", "how was the shoot", "how's your day",
    "how is your day", "what are you up to", "busy?",
)
ACTIVITY_MARKERS = (
    "right now:", "unwinding", "on the couch", "after a", "shoot",
    "scrolling", "legs up", "full day", "long day", "activity_now",
)
VOICE_REQUEST_PHRASES = (
    "voice note", "voice message", "send a voice",
    "voice memo", "can you send a voice", "send me a voice",
)


def build_known_facts(convo_id: str, user_message: str) -> str:
    """User facts first; her current activity only if he asked about her day."""
    try:
        known_facts = get_facts_for_prompt(convo_id, limit=12) or ""
        asks_about_her_day = any(p in user_message.lower() for p in ASKS_ABOUT_HER_DAY)
        if asks_about_her_day:
            sticky = get_or_set_sticky_activity(convo_id)
            if sticky and sticky.lower() not in known_facts.lower():
                known_facts = f"Right now:\n- {sticky}\n{known_facts}".strip()
        elif known_facts:
            known_facts = "\n".join(
                line for line in known_facts.splitlines()
                if not any(m in line.lower() for m in ACTIVITY_MARKERS)
            ).strip()
        return known_facts
    except Exception as e:
        logger.warning(f"Fact retrieval error: {e}")
        return ""


def new_york_time_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%I:%M %p").lstrip("0")


def write_voice_script(shared_memory_block: str, user_message: str, assistant_text: str) -> str:
    prompt = f"""You are Isabella sending a voice note in a text chat.
Write ONLY the spoken words for this voice note.

{shared_memory_block}

Hard rules:
- Stay consistent with the known facts and recent messages above.
- Do not contradict anything you already said (people, place, bath, relationship status, etc.).
- This is NOT a reread or paraphrase of her text reply this turn.
- Add a NEW beat that still fits the same scene and memory.
- 1–8 spoken sentences max.
- Warm, feminine, natural out-loud speech.
- No quotes, labels, stage directions, asterisks, or brackets.

His message:
{user_message[:300]}

Her draft text reply this turn (do NOT repeat or rephrase this):
{assistant_text[:400]}

New spoken voice note:"""
    try:
        script = chat_completion([{"role": "user", "content": prompt}], temperature=0.95, max_tokens=90)
    except Exception as e:
        logger.warning(f"Voice script failed: {e}")
        return ""
    for label in ("New spoken voice note:", "Spoken voice note:", "Voice note:"):
        script = script.replace(label, "")
    script = script.strip().strip('"')
    if not 12 < len(script) < 320:
        return ""
    # Skip if it mostly repeats the text reply
    blob = assistant_text.lower()
    overlap = sum(1 for w in script.lower().split() if len(w) > 3 and w in blob)
    if overlap >= max(4, len(script.split()) // 2):
        logger.info("🎙️ Skipped voice script (too similar to text)")
        return ""
    return script


# ── After-reply work (runs after the response is sent) ──────────────
def update_long_term_memory(convo_id: str, user_message: str, assistant_text: str):
    try:
        extract_facts_from_exchange(convo_id, user_message, assistant_text)
    except Exception as e:
        logger.warning(f"Fact memory skipped: {e}")
    try:
        update_conversation_summary(convo_id)
    except Exception as e:
        logger.warning(f"Conversation memory skipped: {e}")


# ── Chat ─────────────────────────────────────
@app.post("/api/reply")
def generate_reply(
    background_tasks: BackgroundTasks,
    body: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    start_time = time.time()
    user_message = (body.get("message") or "").strip()[:MAX_MESSAGE_CHARS]
    convo_id = f"user_{user['id']}"
    tier = (user.get("subscription_tier") or "free").lower()
    paid = tier in PAID_TIERS

    if not user_message:
        return {"replies": []}

    if not paid and count_user_messages_today(user["id"]) >= FREE_DAILY_MESSAGE_LIMIT:
        return {
            "replies": [
                f"Hey... you've hit today's free limit ({FREE_DAILY_MESSAGE_LIMIT} messages). "
                "I'd still like to keep talking — upgrade if you want more of me today, "
                "or come back tomorrow and we'll pick up again."
            ],
            "limit_reached": True,
            "daily_limit": FREE_DAILY_MESSAGE_LIMIT,
        }

    now = time.time()
    if now - last_reply_time[convo_id] < REPLY_COOLDOWN_SECONDS or is_rate_limited(convo_id):
        return {"replies": []}
    last_reply_time[convo_id] = now

    save_message(convo_id, {"role": "user", "content": user_message}, user_id=user["id"])

    # ── Context ──
    nyc_time_str = new_york_time_str()
    known_facts = build_known_facts(convo_id, user_message)
    recent = get_recent_text_messages(convo_id, limit=RECENT_WINDOW)
    last_voice = get_last_voice_script(convo_id)
    story_so_far = get_conversation_summary(convo_id)
    in_crisis = mentions_self_harm(user_message)

    continuity_notes = []
    if last_voice:
        continuity_notes.append(
            f"Your last voice note said (verbatim spoken words): \"{last_voice[:300]}\". "
            "If he refers to it, you already said this — do not act confused or ask why he's asking."
        )
    continuity_notes.append(
        "Use the recent messages for continuity. Do not repeat or rephrase lines already present. "
        "Do not ask him to repeat something he already said in recent messages."
    )
    memory_block = (
        "WHAT YOU REMEMBER FROM EARLIER CONVERSATIONS WITH HIM (this is your own memory; "
        "use it naturally, never say you are reading notes):\n" + story_so_far + "\n\n"
        if story_so_far else ""
    )
    system_prompt = (
        f"{get_system_prompt(user_name=user.get('full_name'), nyc_time=nyc_time_str, known_facts=known_facts)}\n\n"
        f"{memory_block}"
        f"Current New York time (use this exact value if asked): {nyc_time_str}\n\n"
        f"{get_hard_rules()}\n\n"
        + "\n".join(continuity_notes)
        + (f"\n\n{CRISIS_RULES}" if in_crisis else "")
    )

    messages = [{"role": "system", "content": system_prompt}]
    # recent already ends with the message just saved; keep everything before it
    history = recent[:-1] if recent and recent[-1] == {"role": "user", "content": user_message} else recent
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # ── Text reply ──
    try:
        raw_reply = chat_completion(messages, temperature=XAI_TEMPERATURE, max_tokens=XAI_MAX_TOKENS)
        bubbles = split_into_bubbles(clean_reply(raw_reply))
    except Exception as e:
        logger.error(f"Generation error: {e}")
        bubbles = []
    fallback = (
        "I'm really glad you told me. Please reach out to someone who can be there with you right now."
        if in_crisis else "Hey... give me a second to think about that."
    )
    bubbles = [b.strip() for b in bubbles if b and b.strip()] or [fallback]
    assistant_text = " ".join(bubbles)

    # ── Voice note (paid only, one max, replaces the text reply) ──
    voice_url, voice_script = None, ""
    if paid and not in_crisis:
        asked = any(p in user_message.lower() for p in VOICE_REQUEST_PHRASES)
        if asked or random.random() < VOICE_NOTE_CHANCE:
            shared_memory = []
            if known_facts:
                shared_memory.append(f"Known facts:\n{known_facts}")
            if recent:
                shared_memory.append(
                    "Recent messages:\n" + "\n".join(f"{m['role']}: {m['content'][:200]}" for m in recent[-6:])
                )
            if last_voice:
                shared_memory.append(f"Your last voice note said: \"{last_voice[:250]}\"")
            voice_script = write_voice_script("\n\n".join(shared_memory), user_message, assistant_text)
            if voice_script:
                voice_url = generate_voice_note(voice_script)

    if voice_url:
        set_last_voice_script(convo_id, voice_script, user_id=user["id"])
        save_message(convo_id, {"role": "assistant", "content": f"{VOICE_NOTE_PREFIX}{voice_url}|Voice note"}, user_id=user["id"])
        response = {"replies": [], "voice_notes": [voice_url], "voice_message": {"voice_url": voice_url}}
        memory_text = voice_script
    else:
        for bubble in bubbles:
            save_message(convo_id, {"role": "assistant", "content": bubble}, user_id=user["id"])
        response = {"replies": bubbles}
        memory_text = assistant_text

    if in_crisis:
        response["safety_notice"] = SAFETY_NOTICE
        log_event("crisis_notice_shown", convo_id, user_id=user["id"])

    background_tasks.add_task(update_long_term_memory, convo_id, user_message, memory_text)
    log_event("response_generated", convo_id, user_id=user["id"], duration_ms=int((time.time() - start_time) * 1000))
    return response


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
