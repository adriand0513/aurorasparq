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
| Second Brain | `aurorasparq_brain/` | Long-term memory (facts + running conversation summary) and persona prompts |
| Front end | `static/` | Landing page, chat page, legal pages |

A chat turn: save the user message → build the prompt (persona + facts + recent messages + hard rules) → generate the reply (and, for paid users, sometimes a voice note instead) → send the response. Fact extraction and the conversation summary update run **after** the response is sent, so they never slow the reply down.

## Memory

Each reply is built from three layers:
1. **Recent messages:** the last 30 messages, word for word.
2. **Story so far:** everything older is folded, 20 messages at a time, into a running summary (up to ~900 words). It keeps names, events, plans, promises, inside jokes and what Isabella said about her own life.
3. **Key facts:** up to 8 facts pulled from every exchange, ranked by importance, with up to 40 in each prompt (facts about him first).

## AI disclosure and crisis protocol

Isabella never brings up being an AI in chat. If a user sincerely asks whether she's a real person, she doesn't claim to be human. The site itself (not Isabella) shows "Isabella is an AI companion, not a real person." at the start of every session and every 3 hours, and the terms say it plainly. If a message mentions suicide or self-harm, the reply switches to a supportive one and the site shows a 988 crisis notice. This is required by New York's AI companion law (GBL Art. 47) and California SB 243, which cover users in those states wherever the operator is based.

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
