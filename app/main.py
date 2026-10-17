import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import db, usage
from app.config import Settings, get_settings
from app.llm import get_chat_model
from app.rag import answer_question
from app.retrieval import ChunkRetriever, ensure_fulltext_index

logger = logging.getLogger("ask_washington")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
        usage.ensure_tables()
        ensure_fulltext_index()
        logger.info("Database ready: vector extension and usage tables")
    except psycopg.Error as exc:
        # Start anyway so /health can report the problem.
        logger.warning("Database init failed: %s", exc)
    yield


limiter = Limiter(key_func=get_remote_address)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Ask Washington", version="0.5.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Behind nginx, take the client IP from X-Forwarded-For, but only when the request comes
# from a trusted peer (the local proxy). The rightmost untrusted address wins, so a client
# cannot spoof its IP by sending its own X-Forwarded-For header.
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=[h.strip() for h in get_settings().forwarded_allow_ips.split(",") if h.strip()],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health")
def health() -> JSONResponse:
    database = db.check_db()
    ok = database["connected"] and database["vector_extension"]
    body = {"status": "ok" if ok else "degraded", "app": "ok", "database": database}
    return JSONResponse(body, status_code=200 if ok else 503)


# ------------------------------------------------------------------ /ask


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("question must have at least 3 non-blank characters")
        return value


class Source(BaseModel):
    n: int
    title: str
    doc_type: str
    section: str
    public_url: str
    score: float | None


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    provider: str
    model: str
    latency_ms: int
    usage: Usage


def get_llm(settings: Settings = Depends(get_settings)) -> BaseChatModel:
    return get_chat_model(settings)


def get_retriever(settings: Settings = Depends(get_settings)) -> BaseRetriever:
    return ChunkRetriever(
        mode=settings.retrieval_mode,
        top_k=settings.retrieval_top_k,
        candidates=settings.retrieval_candidates,
        reranker_model=settings.reranker_model,
    )


def get_today() -> date:
    return date.today()


def minute_limit() -> str:
    return get_settings().rate_limit_per_minute


def day_limit() -> str:
    return get_settings().rate_limit_per_day


@app.post("/ask", response_model=AskResponse)
@limiter.limit(minute_limit)
@limiter.limit(day_limit)
def ask(
    request: Request,
    body: AskRequest,
    settings: Settings = Depends(get_settings),
    today: date = Depends(get_today),
    llm: BaseChatModel = Depends(get_llm),
    retriever: BaseRetriever = Depends(get_retriever),
) -> AskResponse:
    started = time.perf_counter()
    ip_hash = usage.hash_ip(settings, get_remote_address(request))
    log = {
        "question": body.question,
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "ip_hash": ip_hash,
    }

    if usage.spent_on(today) >= settings.daily_budget_usd:
        usage.log_question(
            **log,
            source_ids=[],
            input_tokens=0,
            output_tokens=0,
            cost=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            route="none",
            status="budget_exceeded",
        )
        raise HTTPException(
            status_code=429,
            detail=(
                "Ask Washington has reached its daily usage budget. Please try again tomorrow, "
                "or see https://www.linkedin.com/in/wxquevedo in the meantime."
            ),
        )

    try:
        result = answer_question(body.question, llm, retriever)
    except Exception as exc:  # provider or database failure: do not leak details
        logger.exception("answer failed")
        usage.log_question(
            **log,
            source_ids=[],
            input_tokens=0,
            output_tokens=0,
            cost=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            route="error",
            status=f"error:{exc.__class__.__name__}",
        )
        raise HTTPException(status_code=502, detail="The answer service is unavailable.") from exc

    cost = usage.cost_usd(settings, result.input_tokens, result.output_tokens)
    usage.record_usage(today, result.input_tokens, result.output_tokens, cost)
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage.log_question(
        **log,
        source_ids=result.source_ids,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost=cost,
        latency_ms=latency_ms,
        route=result.route,
        status="ok",
    )
    return AskResponse(
        answer=result.answer,
        sources=[Source(**s) for s in result.sources],
        provider=settings.llm_provider,
        model=settings.llm_model,
        latency_ms=latency_ms,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )
