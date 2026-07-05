# test_relationship_state.py
"""
Quick test to verify the Relationship Model + Database layer works correctly.
Run this with: python test_relationship_state.py
"""
from datetime import datetime
from brain.relationship.state import (
    create_new_relationship_state,
    load_relationship_state,
    save_relationship_state,
    update_emotional_state
)
from models.relationship import EmotionalState

def main():
    print("=" * 60)
    print("TESTING ISABELLA'S RELATIONSHIP MODEL (Second Brain Foundation)")
    print("=" * 60)

    # === 1. Create a new relationship state ===
    print("\n[1] Creating new relationship state for user_id=1, convo_id='test_001'...")
    state = create_new_relationship_state(user_id=1, convo_id="test_001")
    print(f"    Created. Phase: {state.phase}, Level: {state.relationship_level}")
    print(f"    Initial emotional state: affection={state.emotional_state.affection}, trust={state.emotional_state.trust}")

    # === 2. Load it back from DB ===
    print("\n[2] Loading relationship state from database...")
    loaded_state = load_relationship_state("test_001")
    if loaded_state:
        print(f"    Loaded successfully. Last interaction: {loaded_state.last_interaction}")
    else:
        print("    FAILED to load state!")
        return

    # === 3. Update emotional state (simulate reflection) ===
    print("\n[3] Updating emotional state (simulating Isabella reflecting)...")
    update_emotional_state(
        convo_id="test_001",
        affection=7,
        trust=8,
        respect=8,
        attraction=6,
        disappointment=1
    )
    print("    Emotional state updated.")

    # === 4. Load again and verify changes ===
    print("\n[4] Reloading to verify changes persisted...")
    final_state = load_relationship_state("test_001")
    if final_state:
        print(f"    Final emotional state:")
        print(f"      - affection:     {final_state.emotional_state.affection}")
        print(f"      - trust:         {final_state.emotional_state.trust}")
        print(f"      - respect:       {final_state.emotional_state.respect}")
        print(f"      - attraction:    {final_state.emotional_state.attraction}")
        print(f"      - disappointment:{final_state.emotional_state.disappointment}")
        print(f"      - emotional_safety: {final_state.emotional_state.emotional_safety}")
        print(f"    Relationship level: {final_state.relationship_level}")
        print(f"    Phase: {final_state.phase}")
    else:
        print("    FAILED to reload final state!")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()