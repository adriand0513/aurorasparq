# brain/relationship/state.py
"""
Relationship State Management for Isabella's Second Brain.
Handles loading, saving, and creating relationship/emotional state.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from aurorasparq_brain.models.relationship import (
    RelationshipState, 
    EmotionalState, 
    UserModel, 
    RelationshipPhase
)
from db.schema import (
    get_db_connection, 
    upsert_relationship_state, 
    get_relationship_state
)

logger = logging.getLogger(__name__)


def load_relationship_state(convo_id: str) -> Optional[RelationshipState]:
    """
    Load relationship state from database.
    Returns None if no state exists.
    """
    row = get_relationship_state(convo_id)
    if not row:
        return None

    try:
        # Parse JSON fields safely
        emotional_state = EmotionalState()
        if row.get("emotional_state"):
            if isinstance(row["emotional_state"], str):
                emotional_state = EmotionalState(**json.loads(row["emotional_state"]))
            elif isinstance(row["emotional_state"], dict):
                emotional_state = EmotionalState(**row["emotional_state"])

        user_model = UserModel(user_id=row.get("user_id"))
        if row.get("user_model"):
            if isinstance(row["user_model"], str):
                user_model = UserModel(**json.loads(row["user_model"]))
            elif isinstance(row["user_model"], dict):
                user_model = UserModel(**row["user_model"])

        last_interaction = row.get("last_interaction")
        if isinstance(last_interaction, str):
            try:
                last_interaction = datetime.fromisoformat(last_interaction.replace("Z", "+00:00"))
            except:
                last_interaction = datetime.utcnow()

        return RelationshipState(
            user_id=row.get("user_id"),
            convo_id=row.get("convo_id"),
            phase=RelationshipPhase(row.get("phase", "early_flirt")),
            relationship_level=row.get("relationship_level", 1),
            emotional_state=emotional_state,
            user_model=user_model,
            last_interaction=last_interaction or datetime.utcnow(),
            total_messages=row.get("total_messages", 0),
            key_milestones=row.get("key_milestones") or [],
            notes=row.get("notes")
        )
    except Exception as e:
        logger.error(f"Failed to load RelationshipState for {convo_id}: {e}")
        return None


def save_relationship_state(state: RelationshipState):
    """Save or update relationship state."""
    try:
        state_dict = {
            "user_id": state.user_id,
            "convo_id": state.convo_id,
            "phase": state.phase.value if hasattr(state.phase, "value") else str(state.phase),
            "relationship_level": state.relationship_level,
            "emotional_state": state.emotional_state.model_dump(),
            "user_model": state.user_model.model_dump(),
            "last_interaction": state.last_interaction,
            "total_messages": state.total_messages,
            "key_milestones": state.key_milestones,
            "notes": state.notes
        }

        success = upsert_relationship_state(state_dict)
        if success:
            logger.info(f"✅ RelationshipState saved for convo_id={state.convo_id}")
        else:
            logger.error(f"❌ Failed to save RelationshipState for {state.convo_id}")
    except Exception as e:
        logger.error(f"Error saving RelationshipState: {e}")


def create_new_relationship_state(user_id: int, convo_id: str) -> RelationshipState:
    """Create a fresh relationship state for a new conversation."""
    state = RelationshipState(
        user_id=user_id,
        convo_id=convo_id,
        phase=RelationshipPhase.EARLY_FLIRT,
        emotional_state=EmotionalState(),
        user_model=UserModel(user_id=user_id),
        relationship_level=1,
        total_messages=0,
        key_milestones=[],
        notes="New relationship started."
    )
    save_relationship_state(state)
    return state


def update_emotional_state(convo_id: str, **changes):
    """Update specific emotional values."""
    state = load_relationship_state(convo_id)
    if not state:
        logger.warning(f"No relationship state found for {convo_id}")
        return

    for key, value in changes.items():
        if hasattr(state.emotional_state, key):
            current_value = getattr(state.emotional_state, key)
            new_value = max(0, min(10, value))
            setattr(state.emotional_state, key, new_value)

    state.last_interaction = datetime.utcnow()
    save_relationship_state(state)
