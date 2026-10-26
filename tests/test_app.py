import json
from unittest import mock

import pytest

from conftest import register_and_login


def set_tier(user_id, tier):
    import database
    with database.db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET subscription_tier = %s WHERE id = %s", (tier, user_id))


# ── Auth ──────────────────────────────────────────
def test_wrong_password_is_rejected(client):
    register_and_login(client)
    r = client.post("/auth/login", data={"username": "him@example.com", "password": "nope-nope"})
    assert r.status_code == 401


def test_duplicate_email_and_short_password(client):
    register_and_login(client)
    assert client.post("/auth/register", json={"email": "him@example.com", "password": "password123"}).status_code == 409
    assert client.post("/auth/register", json={"email": "new@example.com", "password": "short"}).status_code == 400


def test_new_accounts_are_free(client):
    headers, user = register_and_login(client)
    assert user["subscription_tier"] == "free"
    assert client.get("/auth/me", headers=headers).json()["subscription_tier"] == "free"


def test_database_down_never_grants_access(client):
    """Old code logged ANY password in as a premium user when the DB was unreachable."""
    import auth
    import database

    def down():
        raise database.DatabaseUnavailable("down")

    with mock.patch.object(database, "get_db_connection", down):
        r = client.post("/auth/login", data={"username": "anyone@example.com", "password": "whatever1"})
        assert r.status_code == 503


def test_token_for_deleted_user_is_rejected(client):
    import database
    headers, _ = register_and_login(client)
    with database.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM users")
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_garbage_token_is_rejected(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# ── Chat ──────────────────────────────────────────
def test_reply_saves_history_and_uses_persona(client, fake_llm):
    headers, _ = register_and_login(client)
    r = client.post("/api/reply", json={"message": "hi isabella"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["replies"] == ["hey you. how was your day?"]

    system_prompt = fake_llm.calls[0][0]["content"]
    assert "Isabella" in system_prompt and "HARD RULES" in system_prompt
    # The user's message is sent exactly once
    user_turns = [m for m in fake_llm.calls[0] if m["role"] == "user"]
    assert [m["content"] for m in user_turns] == ["hi isabella"]

    history = client.get("/api/history", headers=headers).json()["messages"]
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "hi isabella"),
        ("assistant", "hey you. how was your day?"),
    ]


def test_free_daily_limit(client, fake_llm):
    import main
    headers, _ = register_and_login(client)
    for i in range(5):
        main.last_reply_time.clear()
        assert client.post("/api/reply", json={"message": f"msg {i}"}, headers=headers).json()["replies"]
    main.last_reply_time.clear()
    r = client.post("/api/reply", json={"message": "one more"}, headers=headers).json()
    assert r["limit_reached"] is True
    assert client.get("/api/usage", headers=headers).json()["remaining"] == 0


@pytest.mark.parametrize("tier", ["premium", "ultimate"])
def test_paid_tiers_have_no_daily_limit(client, fake_llm, tier):
    import main
    headers, user = register_and_login(client)
    set_tier(user["id"], tier)
    with mock.patch.object(main.random, "random", return_value=0.99):  # no surprise voice notes
        for i in range(7):
            main.last_reply_time.clear()
            r = client.post("/api/reply", json={"message": f"msg {i}"}, headers=headers).json()
            assert "limit_reached" not in r and r["replies"]
    assert client.get("/api/usage", headers=headers).json()["remaining"] == "unlimited"


def test_empty_message_costs_nothing(client, fake_llm):
    headers, _ = register_and_login(client)
    assert client.post("/api/reply", json={"message": "   "}, headers=headers).json() == {"replies": []}
    assert fake_llm.calls == []


def test_llm_failure_gives_soft_reply(client, fake_llm):
    import main
    headers, _ = register_and_login(client)
    with mock.patch.object(main, "chat_completion", side_effect=RuntimeError("xai down")):
        r = client.post("/api/reply", json={"message": "hi"}, headers=headers).json()
    assert r["replies"] == ["Hey... give me a second to think about that."]


def test_voice_note_for_paid_user(client, fake_llm):
    import main
    headers, user = register_and_login(client)
    set_tier(user["id"], "premium")
    with mock.patch.object(main, "write_voice_script", return_value="mm I was just thinking about what you said earlier"), \
         mock.patch.object(main, "generate_voice_note", return_value="/audio/vn_1_1234.mp3"):
        r = client.post("/api/reply", json={"message": "send me a voice note"}, headers=headers).json()
    assert r["voice_notes"] == ["/audio/vn_1_1234.mp3"] and r["replies"] == []


def test_audio_route_rejects_odd_filenames(client):
    assert client.get("/audio/..%2Fconfig.py").status_code == 404
    assert client.get("/audio/notes.txt").status_code == 404
    assert client.get("/audio/vn_1_1234.mp3").status_code == 404  # valid name, file missing


def test_reflection_runs_after_reply_and_survives_bad_output(client, fake_llm):
    """Every 7th free message triggers reflection; junk model output must not crash it."""
    import database, main
    headers, user = register_and_login(client)
    set_tier(user["id"], "free")
    import config
    with mock.patch.object(config, "FREE_DAILY_MESSAGE_LIMIT", 100), \
         mock.patch.object(main, "FREE_DAILY_MESSAGE_LIMIT", 100):
        fake_llm.reply = json.dumps({"emotional_updates": {"trust": "7", "affection": 12, "bogus": 3},
                                     "relationship_level_change": "+1", "recommended_phase": "nonsense"})
        for i in range(7):
            main.last_reply_time.clear()
            client.post("/api/reply", json={"message": f"msg {i}"}, headers=headers)
    with database.db_cursor() as cur:
        cur.execute("SELECT emotional_state FROM relationship_states WHERE convo_id = %s", (f"user_{user['id']}",))
        state = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reflection_logs")
        logs = cur.fetchone()[0]
    assert logs == 1
    assert state["trust"] == 7 and state["affection"] == 10


# ── Facts ─────────────────────────────────────────
def test_fact_extraction_and_prompt(client, fake_llm):
    from aurorasparq_brain.brain.memory import facts
    fake_llm.reply = json.dumps([
        {"type": "user", "fact": "He lives in Dallas", "importance": "9"},
        {"type": "weird", "fact": "Likes coffee", "importance": 5},
        "not a dict",
    ])
    saved = facts.extract_facts_from_exchange("c1", "I live in Dallas", "ooh Dallas, nice")
    assert saved == ["[user] He lives in Dallas", "[preference] Likes coffee"]
    prompt = facts.get_facts_for_prompt("c1")
    assert prompt.startswith("About him:\n- He lives in Dallas")
