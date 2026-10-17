# syntax=docker/dockerfile:1

# ---- build: dependencies (CPU-only torch) and models ----
FROM docker.io/library/python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

# Every model cache lives under /app/models, in both stages, so the files downloaded here
# are the ones the app reads at runtime. LlamaIndex passes its own cache folder to
# sentence-transformers (by default a per-user directory), so it must be pinned too.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/app/models/huggingface \
    LLAMA_INDEX_CACHE_DIR=/app/models/llama_index \
    TIKTOKEN_CACHE_DIR=/app/models/tiktoken

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY data/papers.yaml ./data/papers.yaml

# Bake the embedding model (and optional rerankers) into the image with the app's own loaders.
ARG RERANKER_MODELS=""
RUN .venv/bin/python -m scripts.download_models ${RERANKER_MODELS}

# ---- runtime ----
FROM docker.io/library/python:3.12-slim

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/models/huggingface \
    LLAMA_INDEX_CACHE_DIR=/app/models/llama_index \
    TIKTOKEN_CACHE_DIR=/app/models/tiktoken \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    FORWARDED_ALLOW_IPS=127.0.0.1

USER app

# Fail the build if the models cannot be loaded offline by the runtime user.
ARG RERANKER_MODELS=""
RUN python -m scripts.download_models --verify ${RERANKER_MODELS}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --proxy-headers: trust X-Forwarded-For only from FORWARDED_ALLOW_IPS (the local proxy).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
