# models/relationship.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

class RelationshipPhase(str, Enum):
    EARLY_FLIRT = "early_flirt"
    BUILDING_CONNECTION = "building_connection"
    EMOTIONAL_INVESTMENT = "emotional_investment"
    DEEPENING_TRUST = "deepening_trust"
    ESTABLISHED = "established"

class EmotionalState(BaseModel):
    """Isabella's current emotional stance toward the user"""
    affection: int = Field(default=5, ge=0, le=10, description="How much she genuinely likes him")
    trust: int = Field(default=4, ge=0, le=10, description="How much she trusts him")
    respect: int = Field(default=6, ge=0, le=10, description="How much she respects him")
    attraction: int = Field(default=4, ge=0, le=10, description="Physical/emotional attraction level")
    disappointment: int = Field(default=0, ge=0, le=10, description="Current disappointment level")
    emotional_safety: int = Field(default=5, ge=0, le=10, description="How safe she feels being vulnerable")
    
    # NEW: Sensual/Sexual openness (controlled and earned)
    sensual_openness: int = Field(
        default=3, 
        ge=0, 
        le=10, 
        description="How open she feels to sensual/sexual energy with this person. Only rises with high trust + emotional safety. Much harder to increase in Free tier."
    )

class UserModel(BaseModel):
    """What Isabella knows and believes about this specific user"""
    user_id: int
    personality_traits: List[str] = Field(default_factory=list)
    values: List[str] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    insecurities: List[str] = Field(default_factory=list)
    communication_style: Optional[str] = None
    attachment_style: Optional[str] = None
    interests: List[str] = Field(default_factory=list)
    last_major_update: Optional[datetime] = None

class RelationshipState(BaseModel):
    """The full internal model of the relationship"""
    user_id: int
    convo_id: str
    phase: RelationshipPhase = RelationshipPhase.EARLY_FLIRT
    emotional_state: EmotionalState = Field(default_factory=EmotionalState)
    user_model: UserModel
    relationship_level: int = Field(default=1, ge=1, le=10)
    last_interaction: datetime = Field(default_factory=datetime.utcnow)
    total_messages: int = 0
    key_milestones: List[str] = Field(default_factory=list)  # e.g. "First time he made her laugh", "He respected a boundary"
    notes: Optional[str] = None

    class Config:
        use_enum_values = True