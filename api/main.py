from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core import database
from data import seed


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = database.get_connection(os.getenv("REVMEM_DB", str(database.DB_PATH)))
        database.init_db(conn)
        seed.seed(conn)
        app.state.conn = conn
        yield
        conn.close()

    app = FastAPI(title="RevMem API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
