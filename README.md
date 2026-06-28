# RevMem — Person B: Core Engine + API

SQLite-backed memory engine and FastAPI tool server for the RevMem agent, exposed to the hosted agent via ngrok.

## Run (local + ngrok)

1. `uv run python -m data.seed`
2. `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`
3. `ngrok http 8000 --domain=<your-reserved>.ngrok.app`
4. Set `REVMEM_BASE_URL` to the ngrok URL for the agent and the UI.

DB persists at `db/revmem.db`. Delete it to reset; `data.seed` reloads policy + CRM.
