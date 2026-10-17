# Ask Washington

A retrieval-augmented (RAG) chat for the portfolio of Washington X. Quevedo, AI Engineer (XR + AI). A recruiter asks about his experience and the system answers by citing his own public sources: CV, LinkedIn profile, the READMEs of his public repositories and the abstracts of his papers.

It is also a learning project for RAG, vector databases, LangChain and LlamaIndex.

## Status

| Part | Status |
|---|---|
| Project base: FastAPI app, config, Postgres + pgvector, `/health`, tests, lint | Done |
| Document ingestion and vector index (LlamaIndex) | Done |
| Answer chain with citations (LangChain + Claude API, usage and spend limits) | Planned |
| Evaluation set (about 30 questions) | Planned |
| Chat interface and deployment to a VPS | Planned |

## Stack

- Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- FastAPI + Uvicorn
- PostgreSQL 16 with [pgvector](https://github.com/pgvector/pgvector) (`pgvector/pgvector:pg16` image)
- pydantic-settings for configuration
- pytest and ruff
- LlamaIndex for loading, chunking and the pgvector store (`PGVectorStore`)
- Local embeddings with `BAAI/bge-small-en-v1.5` (384 dimensions, runs on CPU)
- Planned: LangChain (answer chain), Anthropic Claude API for answers

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

## Ingestion

Only public sources are indexed. They live in `data/` and are not fetched at run time:

| doc_type | Source | Local path | `public_url` |
|---|---|---|---|
| `cv` | The two English CVs (AI Engineer, XR + AI Engineer) | `data/sources/cv/*.pdf` | LinkedIn profile (the CVs have no public URL) |
| `linkedin` | Published sections of the LinkedIn profile | `data/sources/linkedin/LINKEDIN_EN.md` | LinkedIn profile |
| `repo_readme` | READMEs of 6 public repositories | `data/sources/repos/<repo>.md` | GitHub repository |
| `paper` | 25 most cited papers: title, venue, year, citations, abstract | `data/papers.yaml` | DOI |

`data/sources/` is not committed. `data/papers.yaml` is committed: it is `data/papers_seed.yaml` enriched with DOI, URL and abstract from the publisher pages.

Before indexing, email addresses and phone numbers are removed, and from the LinkedIn working file only the published sections (headline, about, experience, skills, education and awards) are kept.

### Commands

```bash
# Repository READMEs (needs the GitHub CLI; or download them from raw.githubusercontent.com)
for r in plan-vivo-kit localia-genai-platform forex-trading-system agent-office-visualizer focus riemann-hypothesis; do
  gh api repos/wx-quevedo/$r/readme -H "Accept: application/vnd.github.raw" > data/sources/repos/$r.md
done

uv run python -m scripts.ingest                 # ingest new or changed documents
uv run python -m scripts.ingest --only paper    # one doc_type: cv, linkedin, repo_readme or paper
uv run python -m scripts.ingest --reset         # drop the index and rebuild it
uv run python -m scripts.search_check           # 5 test queries, top 3 with score, document and URL
uv run python -m scripts.search_check "Unity experience" --top-k 5
```

The first run downloads the embedding model (about 130 MB) to the Hugging Face cache.

### How it works

- **Loading**: LlamaIndex `PDFReader` for the CVs, plain Markdown for LinkedIn and the READMEs, one document per paper.
- **Chunking**: `MarkdownNodeParser` splits by heading, then `SentenceSplitter` makes chunks of about 500 tokens with 60 tokens of overlap. Each paper is a single chunk.
- **Embeddings**: `BAAI/bge-small-en-v1.5`, normalized; queries get the BGE retrieval instruction. Only `title`, `section` and `doc_type` are embedded together with the text.
- **Idempotent**: every document has a SHA-256 hash of its text, metadata and chunking settings. Unchanged documents are skipped, changed ones are replaced, and documents removed from the sources are deleted from the index.

### Tables

| Table | Contents |
|---|---|
| `data_chunks` | Created by LlamaIndex `PGVectorStore` (table name `chunks`, prefixed with `data_`). Columns: `id` (bigserial), `node_id` (for example `repo-focus#003`), `text`, `metadata_` (jsonb), `embedding` (`vector(384)`, HNSW index with cosine distance). |
| `ingested_documents` | One row per source document: `doc_id`, `doc_type`, `title`, `content_hash`, `chunk_count`, `ingested_at`. Used to skip unchanged documents. |

Metadata stored with every chunk in `metadata_`:

| Key | Example |
|---|---|
| `doc_id` | `paper-p01`, `repo-focus`, `cv-ai-engineer`, `linkedin-profile` |
| `doc_type` | `cv`, `linkedin`, `repo_readme`, `paper` |
| `title` | `Unity3D-MatLab simulator in real time for robotics applications` |
| `section` | `Experience > Stanford University — Software & AI Consultant (Buscapez project)` |
| `public_url` | `https://doi.org/10.1007/978-3-319-40621-3_19` |
| `year` | `2016` (papers only; papers also carry `citations` and `doi`) |
| `chunk_index`, `content_hash` | position in the document and hash of the source document |

## Known issues

- **Rootful Podman machine on Windows does not forward ports to `localhost`.** Run `scripts\dev-db-host.ps1` before starting the app (see [Windows with a rootful Podman machine](#windows-with-a-rootful-podman-machine)). Enabling the machine's user-mode networking did not fix it with Podman 6.0.2.
- **Containers fail to start with `aardvark-dns failed to start ... open resolv.conf: No such file or directory`.** This can happen after turning the Podman machine's user-mode networking off again: the machine loses its `/etc/resolv.conf` link. Restore it and start the containers again:

  ```powershell
  podman machine ssh "sudo ln -sf /mnt/wsl/resolv.conf /etc/resolv.conf"
  ```

## Project layout

```
app/        FastAPI app (main.py), settings (config.py), database helpers (db.py),
            source loading and chunking (ingestion.py), embeddings and pgvector (vector_store.py)
scripts/    init_db.py, ingest.py, search_check.py, dev-db-host.ps1
tests/      pytest suite
data/       Source documents (see data/README.md); papers.yaml is committed
reports/    Reports for each stage
```

## License

MIT. See [LICENSE](LICENSE).
