# brain/reflection/graph.py
"""
Reflection Engine Graph for Isabella.
This file orchestrates the full reflection process.
PostgreSQL compatible + improved robustness.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from aurorasparq_brain.brain.relationship.state import (
    create_new_relationship_state,
    load_relationship_state,
    save_relationship_state,
)
from aurorasparq_brain.brain.reflection.nodes import (
    analyze_user_node,
    update_emotions_node,
    update_relationship_node,
    generate_internal_state_node,
    save_reflection_log
)
from aurorasparq_brain.models.relationship import EmotionalState, RelationshipPhase

logger = logging.getLogger(__name__)


def _clamp_score(value) -> int:
    """LLM output may be a string or float; keep it an int in 0..10."""
    return max(0, min(10, int(round(float(value)))))


def run_reflection(
    convo_id: str,
    user_id: int,
    tier: str = "free",
    recent_messages: str = "",
    trigger_type: str = "message_count",
    messages_since_last: int = 0
) -> Dict[str, Any]:
    """
    Main entry point for Isabella's Reflection Engine.
    Runs the full emotional + relationship reflection cycle.
    """
    logger.info(f"🧠 Starting reflection | convo_id={convo_id} | tier={tier}")

    # 1. Load or create relationship state
    state = load_relationship_state(convo_id)
    if not state:
        logger.info("No existing state found. Creating new relationship state.")
        state = create_new_relationship_state(user_id=user_id, convo_id=convo_id)

    before_state = state.emotional_state.model_copy(deep=True)

    # 2. Analyze the user
    user_analysis = analyze_user_node(
        convo_id=convo_id,
        tier=tier,
        conversation_summary=recent_messages[:2000] if recent_messages else "",
        user_model=str(state.user_model.model_dump()) if state.user_model else ""
    )

    # 3. Update emotions
    emotion_result = update_emotions_node(
        convo_id=convo_id,
        tier=tier,
        current_emotional_state=state.emotional_state,
        recent_observations=recent_messages
    )

    raw_updates = emotion_result.get("emotional_updates") or {}
    current = state.emotional_state.model_dump()
    updates = {}
    if isinstance(raw_updates, dict):
        for key, value in raw_updates.items():
            if key not in current:
                continue
            try:
                updates[key] = _clamp_score(value)
            except (TypeError, ValueError):
                logger.warning(f"Ignoring non-numeric emotion update {key}={value!r}")
    if updates:
        current.update(updates)
        state.emotional_state = EmotionalState(**current)

    # 4. Generate internal narrative
    internal_narrative = generate_internal_state_node(
        convo_id=convo_id,
        emotional_state=state.emotional_state,
        tier=tier,
        reasoning=emotion_result.get("reasoning", "")
    )

    # 5. Update relationship phase and level
    current_phase_str = str(state.phase.value) if hasattr(state.phase, "value") else str(state.phase)

    relationship_result = update_relationship_node(
        convo_id=convo_id,
        tier=tier,
        current_phase=current_phase_str,
        current_level=state.relationship_level,
        emotional_updates=updates
    )

    # Apply recommended phase if valid
    if relationship_result.get("recommended_phase"):
        try:
            state.phase = RelationshipPhase(relationship_result["recommended_phase"])
        except ValueError:
            logger.warning(f"Invalid phase returned: {relationship_result.get('recommended_phase')}")

    try:
        level_change = max(-1, min(1, int(relationship_result.get("relationship_level_change", 0) or 0)))
    except (TypeError, ValueError):
        level_change = 0

    # === Automatic Level Decrease Logic ===
    current_emotional = state.emotional_state
    if level_change == 0:
        if (current_emotional.disappointment >= 6 and
            current_emotional.trust <= 4 and
            current_emotional.emotional_safety <= 4):
            level_change = -1
            logger.info("⬇️ Auto-decreasing relationship level due to high disappointment")

    if level_change != 0:
        state.relationship_level = max(1, min(10, state.relationship_level + level_change))

    # 6. Save final state
    state.last_interaction = datetime.now(timezone.utc)
    save_relationship_state(state)

    after_state = state.emotional_state.model_copy(deep=True)

    # 7. Log the reflection
    save_reflection_log(
        user_id=user_id,
        convo_id=convo_id,
        tier=tier,
        before_state=before_state,
        after_state=after_state,
        reasoning=emotion_result.get("reasoning", ""),
        emotional_changes=updates,
        new_milestones=relationship_result.get("new_milestones", []),
        phase_change=str(state.phase.value) if hasattr(state.phase, "value") else str(state.phase),
        trigger_type=trigger_type,
        internal_narrative=internal_narrative
    )

    logger.info(f"✅ Reflection completed | convo_id={convo_id}")

    return {
        "convo_id": convo_id,
        "tier": tier,
        "emotional_changes": updates,
        "reasoning": emotion_result.get("reasoning", ""),
        "new_phase": str(state.phase.value) if hasattr(state.phase, "value") else str(state.phase),
        "level_change": level_change,
        "internal_narrative": internal_narrative,
        "user_analysis": user_analysis
    }
