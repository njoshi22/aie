api: sh -c 'export REVMEM_STUB_MODE="${REVMEM_STUB_MODE:-0}"; uv run uvicorn api.main:app --host 127.0.0.1 --port "${REVMEM_PORT:-8000}"'
ngrok: sh -c 'ngrok http --url="$REVMEM_NGROK_URL" "${REVMEM_PORT:-8000}" --log=stdout'
agent: sh -c 'until curl -sf "$REVMEM_NGROK_URL/openapi.json" -H "ngrok-skip-browser-warning: 1" >/dev/null 2>&1; do sleep 1; done; export REVMEM_BASE_URL="$REVMEM_NGROK_URL"; export REVMEM_TOOL_TRANSPORT="${REVMEM_TOOL_TRANSPORT:-mcp}"; export REVMEM_STUB_MODE=0; uv run python -m cli.run --live ${REVMEM_AGENT_ARGS:-}'
