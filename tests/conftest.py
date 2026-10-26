"""
Test setup: a real throwaway PostgreSQL database, every outside API mocked.
Set TEST_DATABASE_URL to an empty test database. NEVER point it at production.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.exit("Set TEST_DATABASE_URL to a throwaway PostgreSQL database to run the tests.", returncode=1)

os.environ.update(
    DATABASE_URL=TEST_DB,
    XAI_API_KEY="test-xai-key",
    JWT_SECRET="test-secret-" + "x" * 32,
    STRIPE_SECRET_KEY="sk_test_dummy",
    STRIPE_WEBHOOK_SECRET="whsec_dummy",
    AUDIO_DIR=str(ROOT / "tests" / ".audio"),
)
os.environ.pop("ELEVENLABS_API_KEY", None)
os.environ.pop("ELEVENLABS_VOICE_ID", None)

TABLES = "users, chat_history, analytics_events, key_facts, relationship_states, reflection_logs"


@pytest.fixture()
def fake_llm(monkeypatch):
    """Replace the xAI call. Returns a list of prompts the app sent."""
    import llm

    calls = []

    class FakeLLM:
        reply = "hey you. how was your day?"

        def __call__(self, messages, temperature=0.7, max_tokens=1024, timeout=60):
            calls.append(messages)
            return self.reply

    fake = FakeLLM()
    fake.calls = calls
    monkeypatch.setattr(llm, "chat_completion", fake)
    import main
    monkeypatch.setattr(main, "chat_completion", fake)
    return fake


@pytest.fixture()
def client(fake_llm):
    from fastapi.testclient import TestClient

    import database
    import main

    database.init_db()
    with database.db_cursor(commit=True) as cur:
        cur.execute(f"TRUNCATE {TABLES} RESTART IDENTITY")
    main.last_reply_time.clear()
    main.convo_rate_limits.clear()
    with TestClient(main.app) as c:
        yield c


def register_and_login(client, email="him@example.com", password="password123"):
    assert client.post("/auth/register", json={"email": email, "password": password, "full_name": "Sam"}).status_code == 200
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()["user"]
