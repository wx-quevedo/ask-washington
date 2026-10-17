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

#### Windows with a rootful Podman machine

A rootful Podman machine on WSL may not forward published ports to `localhost` on Windows: the container is healthy but `localhost:5432` times out. In that case, before starting the app, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-db-host.ps1
```

It reads the current IP of the Podman machine and rewrites only the `DATABASE_URL` line in `.env`, then prints the resulting URL with the password masked. The machine IP changes when the machine restarts, so run it again after every `podman machine start`.

With Docker, or on Linux, keep `localhost` in `DATABASE_URL` and skip this step.

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

## Known issues

- **Rootful Podman machine on Windows does not forward ports to `localhost`.** Run `scripts\dev-db-host.ps1` before starting the app (see [Windows with a rootful Podman machine](#windows-with-a-rootful-podman-machine)). Enabling the machine's user-mode networking did not fix it with Podman 6.0.2.
- **Containers fail to start with `aardvark-dns failed to start ... open resolv.conf: No such file or directory`.** This can happen after turning the Podman machine's user-mode networking off again: the machine loses its `/etc/resolv.conf` link. Restore it and start the containers again:

  ```powershell
  podman machine ssh "sudo ln -sf /mnt/wsl/resolv.conf /etc/resolv.conf"
  ```

## Project layout

```
app/        FastAPI app (main.py), settings (config.py), database helpers (db.py)
scripts/    Command-line utilities (init_db.py, dev-db-host.ps1)
tests/      pytest suite
data/       Local source documents, not committed (see data/README.md)
```

## License

MIT. See [LICENSE](LICENSE).
