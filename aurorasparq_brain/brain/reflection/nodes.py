# brain/reflection/nodes.py
"""
Core reasoning nodes for Isabella's Reflection Engine.
PostgreSQL compatible version.
"""
import os
import json
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from aurorasparq_brain.models.relationship import EmotionalState
from brain.reflection.prompts import (
    ANALYZE_USER_PROMPT,
    UPDATE_EMOTIONS_PROMPT,
    UPDATE_RELATIONSHIP_PROMPT,
    GENERATE_INTERNAL_STATE_PROMPT
)

logger = logging.getLogger(__name__)

# xAI credentials
XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_API_BASE = os.getenv("XAI_API_BASE", "https://api.x.ai/v1/chat/completions")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.20")

if not XAI_API_KEY:
    raise ValueError("XAI_API_KEY is missing. Please add it to your .env file.")


def call_llm(prompt: str, temperature: float = 0.4, max_tokens: int = 1200) -> str:
    """Clean wrapper to call xAI Grok API"""
    try:
        response = requests.post(
            XAI_API_BASE,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return ""


def parse_json_safely(text: str) -> Optional[Dict[str, Any]]:
    """Robust JSON extractor"""
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        pass
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = text[start:end].replace("```json", "").replace("```", "").strip()
            return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Failed to parse JSON: {e}")
    return None


# ============================================================
# NODE 1: Analyze User
# ============================================================
def analyze_user_node(
    convo_id: str,
    tier: str,
    conversation_summary: str,
    user_model: str
) -> Dict[str, Any]:
    prompt = ANALYZE_USER_PROMPT.format(
        tier=tier,
        conversation_summary=conversation_summary or "No recent summary available.",
        user_model=user_model or "Limited information so far."
    )
    raw_output = call_llm(prompt, temperature=0.3, max_tokens=1000)
    parsed = parse_json_safely(raw_output)
    if not parsed:
        return {"overall_impression": "Unable to form a clear impression at this time."}
    return parsed


# ============================================================
# NODE 2: Update Emotions
# ============================================================
def update_emotions_node(
    convo_id: str,
    tier: str,
    current_emotional_state: EmotionalState,
    recent_observations: str
) -> Dict[str, Any]:
    prompt = UPDATE_EMOTIONS_PROMPT.format(
        tier=tier,
        affection=current_emotional_state.affection,
        trust=current_emotional_state.trust,
        respect=current_emotional_state.respect,
        attraction=current_emotional_state.attraction,
        disappointment=current_emotional_state.disappointment,
        emotional_safety=current_emotional_state.emotional_safety,
        sensual_openness=current_emotional_state.sensual_openness,
        recent_observations=recent_observations or "No new observations."
    )
    raw_output = call_llm(prompt, temperature=0.35, max_tokens=1600)
    parsed = parse_json_safely(raw_output)

    if not parsed or "emotional_updates" not in parsed:
        return {
            "reasoning": "Reflection did not produce valid emotional updates.",
            "emotional_updates": {}
        }

    updates = parsed.get("emotional_updates", {})
    if tier == "free" and "sensual_openness" in updates:
        updates["sensual_openness"] = min(updates.get("sensual_openness", 3), 5)

    return {
        "reasoning": parsed.get("reasoning", ""),
        "emotional_updates": updates,
        "explanation_for_each": parsed.get("explanation_for_each", {})
    }


# ============================================================
# NODE 3: Update Relationship Phase
# ============================================================
def update_relationship_node(
    convo_id: str,
    tier: str,
    current_phase: str,
    current_level: int,
    emotional_updates: Dict[str, Any]
) -> Dict[str, Any]:
    prompt = UPDATE_RELATIONSHIP_PROMPT.format(
        current_phase=current_phase,
        current_level=current_level,
        tier=tier
    )
    raw_output = call_llm(prompt, temperature=0.3, max_tokens=900)
    parsed = parse_json_safely(raw_output)

    if not parsed:
        return {
            "recommended_phase": current_phase,
            "relationship_level_change": 0,
            "reasoning": "Unable to determine phase evolution.",
            "new_milestones": []
        }
    return parsed


# ============================================================
# NODE 4: Generate Internal State
# ============================================================
def generate_internal_state_node(
    convo_id: str,
    emotional_state: EmotionalState,
    tier: str,
    reasoning: str = ""
) -> str:
    context = f"""Current emotional state:
- Affection: {emotional_state.affection}/10
- Trust: {emotional_state.trust}/10
- Respect: {emotional_state.respect}/10
- Emotional Safety: {emotional_state.emotional_safety}/10
- Sensual Openness: {emotional_state.sensual_openness}/10

Recent reflection reasoning: {reasoning[:400] if reasoning else "No specific reasoning."}"""

    prompt = GENERATE_INTERNAL_STATE_PROMPT + "\n\n" + context
    internal_narrative = call_llm(prompt, temperature=0.65, max_tokens=700)
    return internal_narrative.strip() if internal_narrative else "I'm still processing how I feel about this."


# ============================================================
# NODE 5: Save Reflection Log (PostgreSQL)
# ============================================================
def save_reflection_log(
    user_id: int,
    convo_id: str,
    tier: str,
    before_state: EmotionalState,
    after_state: EmotionalState,
    reasoning: str,
    emotional_changes: Dict[str, Any],
    new_milestones: list = None,
    phase_change: str = None,
    trigger_type: str = "message_count",
    internal_narrative: str = ""
):
    from db.schema import get_db_connection
    conn = get_db_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reflection_logs (
                user_id, convo_id, tier,
                before_emotional_state, after_emotional_state,
                reasoning, emotional_changes, new_milestones, phase_change,
                trigger_type, internal_narrative, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (
            user_id,
            convo_id,
            tier,
            json.dumps(before_state.model_dump()),
            json.dumps(after_state.model_dump()),
            reasoning,
            json.dumps(emotional_changes),
            json.dumps(new_milestones or []),
            phase_change,
            trigger_type,
            internal_narrative
        ))
        conn.commit()
        logger.info(f"✅ Reflection logged for convo_id={convo_id}")
    except Exception as e:
        logger.error(f"Failed to save reflection log: {e}")
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
