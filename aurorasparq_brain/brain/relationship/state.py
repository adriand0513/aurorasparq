# brain/relationship/state.py
"""
Relationship state management for Isabella's Second Brain.
This version is designed to work with PostgreSQL + JSONB columns.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aurorasparq_brain.models.relationship import RelationshipState, EmotionalState, UserModel, RelationshipPhase
from db.schema import get_db_connection, upsert_relationship_state, get_relationship_state

logger = logging.getLogger(__name__)


def load_relationship_state(convo_id: str) -> Optional[RelationshipState]:
    """
    Load the full RelationshipState from the database.
    Fixed to handle both string and datetime for last_interaction.
    """
    row = get_relationship_state(convo_id)
    if not row:
        return None

    try:
        # Reconstruct Pydantic models from JSON stored in DB
        emotional_state = EmotionalState(**json.loads(row["emotional_state"])) if row["emotional_state"] else EmotionalState()
        user_model = UserModel(**json.loads(row["user_model"])) if row["user_model"] else UserModel(user_id=row["user_id"])

        # Handle last_interaction safely (can be str or datetime)
        last_interaction = row["last_interaction"]
        if isinstance(last_interaction, str):
            last_interaction = datetime.fromisoformat(last_interaction)
        elif last_interaction is None:
            last_interaction = datetime.now(timezone.utc)

        return RelationshipState(
            user_id=row["user_id"],
            convo_id=row["convo_id"],
            phase=RelationshipPhase(row["phase"]),
            relationship_level=row["relationship_level"],
            emotional_state=emotional_state,
            user_model=user_model,
            last_interaction=last_interaction,
            total_messages=row["total_messages"] or 0,
            key_milestones=json.loads(row["key_milestones"]) if row["key_milestones"] else [],
            notes=row["notes"] or ""
        )
    except Exception as e:
        logger.error(f"Failed to load RelationshipState for {convo_id}: {e}")
        return None


def save_relationship_state(state: RelationshipState):
    """
    Save or update the RelationshipState in PostgreSQL.
    Uses JSONB columns, so we pass dicts directly (psycopg2 handles conversion).
    """
    state_dict = {
        "user_id": state.user_id,
        "convo_id": state.convo_id,
        "phase": state.phase.value if hasattr(state.phase, "value") else state.phase,
        "relationship_level": state.relationship_level,
        "emotional_state": state.emotional_state.model_dump(),      # Pass dict directly
        "user_model": state.user_model.model_dump(),                # Pass dict directly
        "last_interaction": state.last_interaction.isoformat(),
        "total_messages": state.total_messages,
        "key_milestones": state.key_milestones,                     # Pass list/dict directly
        "notes": state.notes
    }

    upsert_relationship_state(state_dict)
    logger.info(f"✅ RelationshipState saved for convo_id={state.convo_id}")


def create_new_relationship_state(user_id: int, convo_id: str) -> RelationshipState:
    """
    Create a fresh RelationshipState when a new conversation starts.
    """
    state = RelationshipState(
        user_id=user_id,
        convo_id=convo_id,
        phase=RelationshipPhase.EARLY_FLIRT,
        emotional_state=EmotionalState(),
        user_model=UserModel(user_id=user_id),
        relationship_level=1,
        total_messages=0,
        key_milestones=[],
        notes="New relationship started. Isabella is still getting to know this person."
    )
    save_relationship_state(state)
    return state


def update_emotional_state(convo_id: str, **changes):
    """
    Helper to update specific emotional values (affection, trust, disappointment, etc.).
    Used heavily by the Reflection Engine.
    """
    state = load_relationship_state(convo_id)
    if not state:
        logger.warning(f"No relationship state found for {convo_id}")
        return

    for key, value in changes.items():
        if hasattr(state.emotional_state, key):
            # Clamp values between 0 and 10
            setattr(state.emotional_state, key, max(0, min(10, value)))

    state.last_interaction = datetime.now(timezone.utc)
    save_relationship_state(state)
    logger.info(f"Updated emotional state for {convo_id}: {changes}")
