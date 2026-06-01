# Trezo Agents

Python 3.11 service that hosts the eight Trezo agents (see `TREZO_AGENT_SPEC.md`).

## Phase 0 Scope

Skeleton only — base `Agent` class, FastAPI shell, `/health` endpoint. Agent
implementations land in Phase 5.

## Run

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env             # fill in keys
uvicorn app.main:app --reload --port 8001
```

Health check: <http://localhost:8001/health>
