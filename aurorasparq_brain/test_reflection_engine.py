# test_reflection_engine.py
"""
Clean test script for Isabella's Reflection Engine (Second Brain).
"""

import logging
from brain.reflection.graph import run_reflection
from db.schema import init_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def test_reflection_engine():
    print("\n" + "=" * 80)
    print("🧪 TESTING ISABELLA'S REFLECTION ENGINE (Second Brain)")
    print("=" * 80 + "\n")

    # Initialize database
    init_db()

    convo_id = "reflection_test_001"
    user_id = 1
    tier = "premium"

    print(f"Running reflection for convo_id: {convo_id}")
    print(f"Tier: {tier}")
    print("-" * 80)

    result = run_reflection(
        convo_id=convo_id,
        user_id=user_id,
        tier=tier,
        recent_messages="He remembered my photography comments and said it inspired him to try street photography himself. He also said he enjoys talking to me and that I'm not like everyone else.",
        trigger_type="manual_test"
    )

    print("\n" + "=" * 80)
    print("📊 REFLECTION RESULTS")
    print("=" * 80)

    print("\n🔹 Emotional Changes:")
    for key, value in result.get("emotional_changes", {}).items():
        print(f"   {key}: {value}")

    print("\n🔹 Reasoning:")
    print(result.get("reasoning", "No reasoning provided."))

    print("\n💭 Internal Narrative:")
    print("-" * 80)
    print(result.get("internal_narrative", "No internal narrative generated."))
    print("-" * 80)

    print("\n🔄 Relationship Update:")
    print(f"   New Phase     : {result.get('new_phase')}")
    print(f"   Level Change  : {result.get('level_change')}")

    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    test_reflection_engine()