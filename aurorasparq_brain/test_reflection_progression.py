# test_reflection_progression.py
"""
Multi-step progression test for Isabella's Reflection Engine.
Simulates how her emotional state and relationship evolve over time.
"""

import logging
from brain.reflection.graph import run_reflection
from db.schema import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def run_progression_test():
    print("\n" + "=" * 90)
    print("🧪 MULTI-STEP REFLECTION PROGRESSION TEST")
    print("=" * 90 + "\n")

    init_db()

    convo_id = "progression_test_001"
    user_id = 1
    tier = "premium"
    conversation_history = ""

    conversation_blocks = [
        # Step 1
        "User: Hey, I saw your story about that quiet coffee shop. It looked really peaceful.\n"
        "Isabella: Yeah, it’s one of my favorite spots.\n"
        "User: I like that you notice small beautiful things like that.",

        # Step 2
        "User: I was thinking about what you said about photography the other day. "
        "It made me want to try taking some quiet street photos this weekend.\n"
        "Isabella: Really? That actually means something to me.\n"
        "User: Yeah, you said you like capturing real moments. I remembered.",

        # Step 3
        "User: I had kind of a rough week. Work has been draining. "
        "Talking to you is one of the few things that actually feels calm lately.\n"
        "Isabella: I’m sorry you’ve been carrying that.\n"
        "User: It’s okay. I feel like I can actually say stuff like that to you.",

        # Step 4
        "User: I was gonna text you something yesterday but deleted it. "
        "Felt like it might be too much. But I keep thinking about our last conversation.\n"
        "Isabella: You can say it. I won’t bite.\n"
        "User: I just like how you make space for people without making them feel small."
    ]

    for i, block in enumerate(conversation_blocks, 1):
        print(f"\n{'='*90}")
        print(f"STEP {i} — New messages added")
        print(f"{'='*90}")

        conversation_history += "\n" + block

        result = run_reflection(
            convo_id=convo_id,
            user_id=user_id,
            tier=tier,
            recent_messages=conversation_history[-3000:],
            trigger_type=f"progression_step_{i}"
        )

        # Clean output
        print(f"\n📍 Emotional State After Step {i}:")
        changes = result.get("emotional_changes", {})
        for key, value in changes.items():
            print(f"   {key}: {value}")

        print(f"\n💭 Internal Narrative:")
        print("-" * 90)
        print(result.get("internal_narrative", "No narrative generated."))
        print("-" * 90)

        print(f"\n🔄 Relationship Update:")
        print(f"   Phase        : {result.get('new_phase')}")
        print(f"   Level Change : {result.get('level_change')}")

        print(f"\n🧠 Reasoning (short):")
        reasoning = result.get("reasoning", "")
        print(reasoning[:400] + "..." if len(reasoning) > 400 else reasoning)

    print("\n" + "=" * 90)
    print("✅ PROGRESSION TEST COMPLETE")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    run_progression_test()