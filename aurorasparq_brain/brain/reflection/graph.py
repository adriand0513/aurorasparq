# brain/reflection/graph.py
"""
Reflection Engine Graph for Isabella.
PostgreSQL compatible version.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from brain.relationship.state import (
    load_relationship_state,
    save_relationship_state,
    create_new_relationship_state
)
from brain.reflection.nodes import (
    analyze_user_node,
    update_emotions_node,
    update_relationship_node,
    generate_internal_state_node,
    save_reflection_log
)
from aurorasparq_brain.models.relationship import EmotionalState, RelationshipPhase

logger = logging.getLogger(__name__)


def run_reflection(
    convo_id: str,
    user_id: int,
    tier: str = "free",
    recent_messages: str = "",
    trigger_type: str = "message_count",
    messages_since_last: int = 0
) -> Dict[str, Any]:
    logger.info(f"🧠 Starting reflection | convo_id={convo_id} | tier={tier}")

    # 1. Load or create state
    state = load_relationship_state(convo_id)
    if not state:
        state = create_new_relationship_state(user_id=user_id, convo_id=convo_id)

    before_state = state.emotional_state.model_copy(deep=True)

    # 2. Analyze user
    user_analysis = analyze_user_node(
        convo_id=convo_id,
        tier=tier,
        conversation_summary=recent_messages[:2000] if recent_messages else "",
        user_model=str(state.user_model.model_dump())
    )

    # 3. Update emotions
    emotion_result = update_emotions_node(
        convo_id=convo_id,
        tier=tier,
        current_emotional_state=state.emotional_state,
        recent_observations=recent_messages
    )

    updates = emotion_result.get("emotional_updates", {})
    if updates:
        current = state.emotional_state.model_dump()
        for key, value in updates.items():
            if key in current:
                current[key] = max(0, min(10, value))
        state.emotional_state = EmotionalState(**current)

    # 4. Generate internal narrative
    internal_narrative = generate_internal_state_node(
        convo_id=convo_id,
        emotional_state=state.emotional_state,
        tier=tier,
        reasoning=emotion_result.get("reasoning", "")
    )

    # 5. Update relationship phase/level
    relationship_result = update_relationship_node(
        convo_id=convo_id,
        tier=tier,
        current_phase=str(state.phase.value) if hasattr(state.phase, "value") else str(state.phase),
        current_level=state.relationship_level,
        emotional_updates=updates
    )

    if relationship_result.get("recommended_phase"):
        try:
            state.phase = RelationshipPhase(relationship_result["recommended_phase"])
        except:
            pass

    level_change = relationship_result.get("relationship_level_change", 0)

    # Auto-decrease logic
    current_emotional = state.emotional_state
    if level_change == 0:
        if (current_emotional.disappointment >= 6 and 
            current_emotional.trust <= 4 and 
            current_emotional.emotional_safety <= 4):
            level_change = -1
            logger.info("⬇️ Auto-decreasing relationship level")

    if level_change != 0:
        state.relationship_level = max(1, min(10, state.relationship_level + level_change))

    # 6. Save state
    state.last_interaction = datetime.now(timezone.utc)
    save_relationship_state(state)

    after_state = state.emotional_state.model_copy(deep=True)

    # 7. Log reflection
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


def should_reflect(message_count: int, last_reflection_count: int, tier: str) -> bool:
    diff = message_count - last_reflection_count
    return diff >= 8 if tier == "premium" else diff >= 12
