import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import db, usage
from app.config import Settings, get_settings
from app.i18n import answer_language, api_message, normalize_lang, parse_origins, render_page
from app.llm import get_chat_model, get_translation_model
from app.rag import answer_question
from app.retrieval import ChunkRetriever, ensure_fulltext_index
from app.translation import QueryTranslation, QueryTranslator

logger = logging.getLogger("ask_washington")


def configure_logging() -> None:
    """Show the app's INFO logs (uvicorn configures only its own loggers)."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


configure_logging()


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
# Behind nginx, take the client IP from X-Forwarded-For, but only when the request comes
# from a trusted peer (the local proxy). The rightmost untrusted address wins, so a client
# cannot spoof its IP by sending its own X-Forwarded-For header.
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=[h.strip() for h in get_settings().forwarded_allow_ips.split(",") if h.strip()],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def content_security_policy(origins: list[str]) -> str:
    ancestors = " ".join(["'self'", *origins])
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        f"connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors {ancestors}"
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """CSP with frame-ancestors from EMBED_ALLOWED_ORIGINS (the app owns these headers)."""
    response = await call_next(request)
    if request.url.path.startswith(DOCS_PATHS):
        return response  # the interactive docs load assets from a CDN
    origins = parse_origins(get_settings().embed_allowed_origins)
    response.headers["Content-Security-Policy"] = content_security_policy(origins)
    if not origins:
        # Legacy browsers ignore frame-ancestors; X-Frame-Options cannot list origins, so it
        # is only sent when no other site may embed the page.
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


def request_lang(request: Request, body: object = None) -> str:
    """Language for API messages: the JSON body's "lang", else ?lang=, else English."""
    if isinstance(body, dict) and body.get("lang"):
        return normalize_lang(str(body["lang"]))
    return normalize_lang(request.query_params.get("lang"))


@app.exception_handler(RequestValidationError)
async def localized_validation_error(request: Request, exc: RequestValidationError):
    lang = request_lang(request, exc.body)
    return JSONResponse({"detail": api_message("validation", lang)}, status_code=422)


@app.exception_handler(RateLimitExceeded)
async def localized_rate_limit(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"detail": api_message("rate_limit", request_lang(request))}, status_code=429
    )


@app.get("/", include_in_schema=False)
def index(lang: str = "en", embed: str = "0") -> HTMLResponse:
    origins = parse_origins(get_settings().embed_allowed_origins)
    page = render_page(normalize_lang(lang), embed in ("1", "true", "yes"), origins)
    return HTMLResponse(page)


@app.get("/health")
def health() -> JSONResponse:
    database = db.check_db()
    ok = database["connected"] and database["vector_extension"]
    body = {"status": "ok" if ok else "degraded", "app": "ok", "database": database}
    return JSONResponse(body, status_code=200 if ok else 503)


# ------------------------------------------------------------------ /ask


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    # Interface language. The answer uses it unless the question is clearly in the other one.
    lang: str = "en"

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("question must have at least 3 non-blank characters")
        return value

    @field_validator("lang")
    @classmethod
    def known_lang(cls, value: str) -> str:
        return normalize_lang(value)


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
    lang: str
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
        max_per_doc=settings.retrieval_max_per_doc or None,
    )


def get_translator(settings: Settings = Depends(get_settings)):
    """Query translator for non-English questions, or None when QUERY_TRANSLATION=off."""
    if not settings.query_translation:
        return None
    try:
        return QueryTranslator(get_translation_model(settings), settings.translation_timeout_s)
    except Exception:  # never break /ask: search with the original question only
        logger.warning("query translation unavailable; searching with the original question")
        return None


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
    translator: Callable[[str], QueryTranslation] | None = Depends(get_translator),
) -> AskResponse:
    started = time.perf_counter()
    ip_hash = usage.hash_ip(settings, get_remote_address(request))
    # Language of the answer and of any error from here on.
    reply_lang = answer_language(body.question, body.lang)
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
        raise HTTPException(status_code=429, detail=api_message("budget", reply_lang))

    try:
        result = answer_question(
            body.question, llm, retriever, lang=body.lang, translator=translator
        )
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
        raise HTTPException(status_code=502, detail=api_message("unavailable", reply_lang)) from exc

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
        lang=result.lang,
        sources=[Source(**s) for s in result.sources],
        provider=settings.llm_provider,
        model=settings.llm_model,
        latency_ms=latency_ms,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )
