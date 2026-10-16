import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import db

logger = logging.getLogger("ask_washington")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
        logger.info("Database ready: vector extension enabled")
    except psycopg.Error as exc:
        # Start anyway so /health can report the problem.
        logger.warning("Database init failed: %s", exc)
    yield


app = FastAPI(title="Ask Washington", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> JSONResponse:
    database = db.check_db()
    ok = database["connected"] and database["vector_extension"]
    body = {"status": "ok" if ok else "degraded", "app": "ok", "database": database}
    return JSONResponse(body, status_code=200 if ok else 503)
