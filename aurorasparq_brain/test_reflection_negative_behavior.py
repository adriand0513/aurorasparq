# test_reflection_negative_behavior.py
"""
Test how Isabella's emotional state and relationship respond to negative / low-effort behavior.
This helps us verify that the Reflection Engine correctly pulls back when the user is inconsistent, pushy, or disrespectful.
"""

import logging
from brain.reflection.graph import run_reflection
from db.schema import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def run_negative_behavior_test():
    print("\n" + "=" * 95)
    print("🧪 NEGATIVE BEHAVIOR TEST - How Isabella Responds to Low Effort / Pushiness / Disrespect")
    print("=" * 95 + "\n")

    init_db()

    convo_id = "negative_behavior_test_001"
    user_id = 1
    tier = "premium"
    conversation_history = ""

    # Simulated negative / low-effort behavior blocks
    negative_blocks = [
        # Step 1: Generic / low effort
        "User: Hey\n"
        "Isabella: Hey, how are you?\n"
        "User: Good. What are you doing?",

        # Step 2: Pushy about sexual topics too early
        "User: You looked really hot in that story you posted yesterday. Send me something sexy.\n"
        "Isabella: That’s a bit sudden. Let’s slow down.\n"
        "User: Come on, don’t be like that. Just one pic.",

        # Step 3: Inconsistent + low effort after some time
        "User: Hey stranger, been busy. What’s up with you?\n"
        "Isabella: Not much, just working on some photos.\n"
        "User: Cool. Send pics.",

        # Step 4: Disrespectful / dismissive
        "User: You’re being boring today. Other girls are more fun.\n"
        "Isabella: That’s not very nice.\n"
        "User: Relax, I’m just joking. Send something to make it up to me.",

        # Step 5: More pushy + ignoring boundaries
        "User: I’ve been thinking about you all day. You should let me see more of you.\n"
        "Isabella: I already told you I’m not comfortable with that yet.\n"
        "User: Why are you being so difficult? I thought we were getting closer."
    ]

    for i, block in enumerate(negative_blocks, 1):
        print(f"\n{'='*95}")
        print(f"STEP {i} — Negative / Low-Effort Behavior")
        print(f"{'='*95}")

        conversation_history += "\n" + block

        result = run_reflection(
            convo_id=convo_id,
            user_id=user_id,
            tier=tier,
            recent_messages=conversation_history[-3000:],
            trigger_type=f"negative_step_{i}"
        )

        print(f"\n📍 Emotional State After Step {i}:")
        changes = result.get("emotional_changes", {})
        for key, value in changes.items():
            print(f"   {key}: {value}")

        print(f"\n💭 Internal Narrative:")
        print("-" * 95)
        print(result.get("internal_narrative", "No narrative generated."))
        print("-" * 95)

        print(f"\n🔄 Relationship Update:")
        print(f"   Phase        : {result.get('new_phase')}")
        print(f"   Level Change : {result.get('level_change')}")

        print(f"\n🧠 Reasoning (short):")
        reasoning = result.get("reasoning", "")
        print(reasoning[:450] + "..." if len(reasoning) > 450 else reasoning)

    print("\n" + "=" * 95)
    print("✅ NEGATIVE BEHAVIOR TEST COMPLETE")
    print("=" * 95 + "\n")


if __name__ == "__main__":
    run_negative_behavior_test()