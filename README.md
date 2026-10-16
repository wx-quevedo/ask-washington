# Ask Washington

A retrieval-augmented (RAG) chat for the portfolio of Washington X. Quevedo, AI Engineer (XR + AI). A recruiter asks about his experience and the system answers by citing his own sources: CV, `PROFILE.md`, the READMEs of his public repositories and summaries of his papers.

It is also a learning project for RAG, vector databases, LangChain and LlamaIndex.

## Status

| Part | Status |
|---|---|
| Project base: FastAPI app, config, Postgres + pgvector, `/health`, tests, lint | Done |
| Document ingestion and vector index (LlamaIndex) | Planned |
| Answer chain with citations (LangChain + Claude API, usage and spend limits) | Planned |
| Evaluation set (about 30 questions) | Planned |
| Chat interface and deployment to a VPS | Planned |

## Stack

- Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- FastAPI + Uvicorn
- PostgreSQL 16 with [pgvector](https://github.com/pgvector/pgvector) (`pgvector/pgvector:pg16` image)
- pydantic-settings for configuration
- pytest and ruff
- Planned: LlamaIndex (ingestion and index), LangChain (answer chain), local embeddings with `BAAI/bge-small-en-v1.5`, Anthropic Claude API for answers

## Run locally

Requirements: Python 3.12, uv, git, and either Docker (with Compose) or Podman (with `podman compose`).

### 1. Clone and configure

```bash
git clone <repo-url> ask-washington
cd ask-washington
cp .env.example .env
uv sync
```

`.env` holds development-only credentials. If port 5432 is taken on your machine, change both `POSTGRES_PORT` and the port in `DATABASE_URL`.

### 2. Start the database

With Docker:

```bash
docker compose up -d
docker compose ps
```

With Podman:

```bash
podman compose up -d
podman compose ps
```

Wait until the `db` service reports healthy.

Podman on Windows: if the container is healthy but `localhost:5432` times out, the Podman machine is not forwarding ports to the Windows host. Either enable user-mode networking (`podman machine stop`, `podman machine set --user-mode-networking=true`, `podman machine start`) or point `DATABASE_URL` at the machine IP shown by `podman machine ssh "ip -4 addr show eth0"`.

### 3. Enable pgvector

The app runs `CREATE EXTENSION IF NOT EXISTS vector` on startup. You can also run it on its own:

```bash
uv run python -m scripts.init_db
```

### 4. Run the app

```bash
uv run uvicorn app.main:app --reload
```

Then check the health endpoint:

```bash
curl http://127.0.0.1:8000/health
```

It returns `200` with `"status": "ok"` when the database is reachable and the `vector` extension is installed, and `503` with `"status": "degraded"` otherwise.

### 5. Tests and lint

The tests need the database running.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### Stop the database

```bash
docker compose down     # or: podman compose down
```

Data lives in the named volume `ask_washington_pgdata`. Add `-v` to `down` to delete it.

## Project layout

```
app/        FastAPI app (main.py), settings (config.py), database helpers (db.py)
scripts/    Command-line utilities (init_db.py)
tests/      pytest suite
data/       Local source documents, not committed (see data/README.md)
```

## License

MIT. See [LICENSE](LICENSE).
