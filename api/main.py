from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.utilities.lifespan import combine_lifespans

from api.mcp_server import create_revmem_mcp
from api.routes import router
from core import database
from data import seed


def create_app() -> FastAPI:
    @asynccontextmanager
    async def api_lifespan(app: FastAPI):
        conn = database.get_connection(os.getenv("REVMEM_DB", str(database.DB_PATH)))
        database.init_db(conn)
        seed.seed(conn)
        app.state.conn = conn
        yield
        conn.close()

    app_ref: dict[str, FastAPI] = {}
    mcp = create_revmem_mcp(lambda: app_ref["app"].state.conn)
    mcp_app = mcp.http_app(path="/")

    app = FastAPI(title="RevMem API", lifespan=combine_lifespans(api_lifespan, mcp_app.lifespan))
    app_ref["app"] = app
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.include_router(router)
    app.mount("/mcp", mcp_app)
    return app


app = create_app()
