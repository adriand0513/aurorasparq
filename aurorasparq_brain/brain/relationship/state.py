# brain/relationship/state.py
"""
Relationship State Management for Isabella's Second Brain.
Loads, saves and creates the per-conversation relationship/emotional state.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from aurorasparq_brain.models.relationship import (
    EmotionalState,
    RelationshipPhase,
    RelationshipState,
    UserModel,
)
from database import db_cursor

logger = logging.getLogger(__name__)


def _as_dict(value):
    """JSONB comes back as dict from psycopg2; tolerate JSON strings too."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def load_relationship_state(convo_id: str) -> Optional[RelationshipState]:
    """Return the stored state, or None if there is none (or it is unreadable)."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT user_id, convo_id, phase, relationship_level, emotional_state,
                   user_model, last_interaction, total_messages, key_milestones, notes
            FROM relationship_states WHERE convo_id = %s
            """,
            (convo_id,),
        )
        row = cur.fetchone()
    if not row:
        return None

    (user_id, convo, phase, level, emotional, user_model, last_interaction,
     total_messages, milestones, notes) = row
    try:
        emotional = _as_dict(emotional)
        user_model = _as_dict(user_model)
        return RelationshipState(
            user_id=user_id,
            convo_id=convo,
            phase=RelationshipPhase(phase or RelationshipPhase.EARLY_FLIRT.value),
            relationship_level=level or 1,
            emotional_state=EmotionalState(**emotional) if emotional else EmotionalState(),
            user_model=UserModel(**user_model) if user_model else UserModel(user_id=user_id),
            last_interaction=last_interaction or datetime.now(timezone.utc),
            total_messages=total_messages or 0,
            key_milestones=_as_dict(milestones) or [],
            notes=notes,
        )
    except Exception as e:
        logger.error(f"Failed to load RelationshipState for {convo_id}: {e}")
        return None


def save_relationship_state(state: RelationshipState) -> bool:
    """Insert or update the state for its convo_id."""
    phase = state.phase.value if hasattr(state.phase, "value") else str(state.phase)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO relationship_states
                    (user_id, convo_id, phase, relationship_level, emotional_state,
                     user_model, last_interaction, total_messages, key_milestones, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (convo_id) DO UPDATE SET
                    phase = EXCLUDED.phase,
                    relationship_level = EXCLUDED.relationship_level,
                    emotional_state = EXCLUDED.emotional_state,
                    user_model = EXCLUDED.user_model,
                    last_interaction = EXCLUDED.last_interaction,
                    total_messages = EXCLUDED.total_messages,
                    key_milestones = EXCLUDED.key_milestones,
                    notes = EXCLUDED.notes
                """,
                (
                    state.user_id,
                    state.convo_id,
                    phase,
                    state.relationship_level,
                    json.dumps(state.emotional_state.model_dump()),
                    state.user_model.model_dump_json(),
                    state.last_interaction,
                    state.total_messages,
                    json.dumps(state.key_milestones),
                    state.notes,
                ),
            )
        logger.info(f"✅ RelationshipState saved for convo_id={state.convo_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save RelationshipState for {state.convo_id}: {e}")
        return False


def create_new_relationship_state(user_id: int, convo_id: str) -> RelationshipState:
    """Create and store a fresh relationship state for a new conversation."""
    state = RelationshipState(
        user_id=user_id,
        convo_id=convo_id,
        user_model=UserModel(user_id=user_id),
        notes="New relationship started.",
    )
    save_relationship_state(state)
    return state
