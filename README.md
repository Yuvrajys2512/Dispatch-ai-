# Dispatch AI

**AI-powered emergency call triage for India's 112 infrastructure.**
_The first responder before the first responder._

- Product spec: [`Documents/dispatch-ai.md`](Documents/dispatch-ai.md)
- Build plan & phase checklist: [`project-checklist.md`](project-checklist.md)

The system is built **simulator-first**: every external provider (telephony,
ASR, TTS, LLM) sits behind an adapter interface with a mock implementation, so
the whole product runs and demos with **zero external credentials**. Real
providers (Exotel / Sarvam / LLM) swap in at Phase 7 via `PROVIDER_MODE=real`.

## Ports

This machine also runs a `jobhunt-ai` project on 8000/5432/6379, so Dispatch AI
uses its own ports to coexist:

| Service | Host port |
|---|---|
| Backend (FastAPI) | **8001** |
| PostgreSQL | **5433** |
| Redis | **6380** |
| Frontend (Vite) | 5173 |

## Prerequisites

Python 3.12+ (tested on 3.14), Node 20+, Docker Desktop.

## Run it (local dev)

**1. Infra (Postgres + Redis):**
```bash
docker compose up -d
```

**2. Backend:**
```bash
cd backend
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt  # macOS/Linux
cp .env.example .env
./.venv/Scripts/python -m uvicorn app.main:app --reload --port 8001
```
Health check: http://localhost:8001/health · API docs: http://localhost:8001/docs

**Database migrations + seed (Phase 1, needs infra up):**
```bash
cd backend
./.venv/Scripts/python -m alembic upgrade head   # create the schema
./.venv/Scripts/python -m app.db.seed            # live Postgres+Redis round-trip demo
./.venv/Scripts/python -m app.db.seed seed       # insert sample callers/calls for the dashboard
```

**3. Frontend:**
```bash
cd frontend
npm install
npm run dev
```
Control Room: http://localhost:5173 (header shows live backend status)

## Tests

```bash
cd backend && ./.venv/Scripts/python -m pytest    # backend (infra-free: async SQLite + fakeredis)
cd frontend && npm run build                       # typecheck + build
```

The backend test suite needs **no Docker** — the data-layer tests run against an
in-memory async SQLite database and a fake Redis, so `pytest` is green offline.
The identical repository/store code runs against real Postgres + Redis via the
seed/demo script above.

## Project status

See [`project-checklist.md`](project-checklist.md). **Phase 0 (Foundation) is
complete** — infra, FastAPI skeleton, and the dashboard shell run end-to-end.
