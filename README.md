# Aurora Sparq

FastAPI backend and web chat for Isabella, an AI companion character with a long-term "Second Brain" memory.

## How it fits together

| Part | File(s) | What it does |
|---|---|---|
| App + routes | `main.py` | Pages, auth routes, `/api/reply` chat endpoint |
| Settings | `config.py`, `.env.example` | All settings come from environment variables |
| Database | `database.py` | The only PostgreSQL connection point; creates every table at startup |
| LLM | `llm.py` | The only place that calls the xAI API |
| Accounts | `auth.py` | Register, login, JWT, subscription tier (always read from the DB) |
| Payments | `payment.py` | Stripe checkout + webhook (upgrades, cancellations) |
| Voice | `voice.py` | ElevenLabs voice notes, saved to the Render disk |
| Chat history | `memory.py` | Short-term memory (recent messages) |
| Second Brain | `aurorasparq_brain/` | Fact memory, relationship state, reflection engine, persona prompts |
| Front end | `static/` | Landing page, chat page, legal pages |

A chat turn: save the user message → build the prompt (persona + facts + recent messages + hard rules) → generate the reply (and, for paid users, sometimes a voice note instead) → send the response. Fact extraction and the reflection engine run **after** the response is sent, so they never slow the reply down.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL, XAI_API_KEY, JWT_SECRET
uvicorn main:app --reload
```

PostgreSQL is required (there is no SQLite mode). Tables are created automatically on startup.

## Tests

```bash
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/aurora_test pytest
```

Tests use a real throwaway PostgreSQL database and mock all outside APIs (xAI, ElevenLabs, Stripe), so they cost nothing to run. **Never point `TEST_DATABASE_URL` at production**: the tests wipe the tables.

## Deploy (Render)

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add a persistent disk mounted at `/var/data` for voice notes
- Set the environment variables from `.env.example`
- In Stripe, point the webhook at `/payments/webhook` and send `checkout.session.completed`, `customer.subscription.updated` and `customer.subscription.deleted`
