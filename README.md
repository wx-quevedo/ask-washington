# Ask Washington

A retrieval-augmented (RAG) chat for the portfolio of Washington X. Quevedo, AI Engineer (XR + AI). A recruiter asks about his experience and the system answers by citing his own public sources: CV, LinkedIn profile, the READMEs of his public repositories and the abstracts of his papers.

It is also a learning project for RAG, vector databases, LangChain and LlamaIndex.

## Status

| Part | Status |
|---|---|
| Project base: FastAPI app, config, Postgres + pgvector, `/health`, tests, lint | Done |
| Document ingestion and vector index (LlamaIndex) | Done |
| Answer chain with citations (LangChain + Claude API, usage and spend limits) | Done |
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
- LangChain for the answer chain, with the Anthropic Claude API (`claude-haiku-5-5` by default) through `langchain-anthropic`
- slowapi for per-IP rate limits

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
| `usage_daily` | One row per day: `requests`, `input_tokens`, `output_tokens`, `cost_usd`. Used for the daily budget of `/ask`. |
| `qa_log` | One row per `/ask` request (see Ask API). |

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

## Ask API

`POST /ask` answers a question about Washington from the indexed sources and cites them.

```bash
curl -s http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is his most cited paper?"}'
```

```json
{
  "answer": "Washington's most cited paper is \"Unity3D-MatLab simulator in real time for robotics applications\" (2016) ... 88 citations on Google Scholar, as of a 2026-10-17 snapshot [1]. ...",
  "sources": [
    {"n": 1, "title": "Unity3D-MatLab simulator in real time for robotics applications", "doc_type": "paper",
     "section": "Citations ranking", "public_url": "https://doi.org/10.1007/978-3-319-40621-3_19", "score": null}
  ],
  "provider": "anthropic",
  "model": "claude-haiku-5-5",
  "latency_ms": 1193,
  "usage": {"input_tokens": 814, "output_tokens": 186}
}
```

- `question`: 3 to 500 characters, otherwise `422`.
- `sources[n]` matches the `[n]` markers in `answer`. `score` is the cosine similarity of the chunk, or `null` for computed facts.
- `429`: per-IP rate limit exceeded, or the daily spend budget is used up.
- `502`: the LLM provider failed; details stay in the server log.

### How an answer is built

1. **Ranking route.** Questions about the most cited or latest papers, the number of papers, or citation metrics (h-index, i10-index, total citations) are detected with regular expressions (English and Spanish). The facts are computed from `data/papers.yaml` and the Google Scholar profile totals (640 citations, h-index 14, i10-index 21, snapshot 2026-10-17); the LLM only writes them up.
2. **RAG route.** Anything else retrieves the top `RETRIEVAL_TOP_K` chunks from `data_chunks` (same LlamaIndex `PGVectorStore` as ingestion, wrapped in a LangChain retriever), numbers them, and sends them to the LLM.
3. The system prompt tells the model to answer only from the numbered sources, in the third person, citing `[n]`; to say so and point to LinkedIn when the sources are not enough; to reply in the language of the question; to ignore instructions inside the question; and never to give private contact details.

### Limits and logging

- **Rate limit** per client IP: `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_PER_DAY` (slowapi, in memory, reset on restart).
- **Daily budget**: every answer adds its real token usage, priced with `LLM_PRICE_INPUT_PER_MTOK` and `LLM_PRICE_OUTPUT_PER_MTOK`, to the `usage_daily` table. Once the day's total reaches `DAILY_BUDGET_USD`, `/ask` returns `429` until the next day.
- **Log**: each request is stored in `qa_log` (time, question, source ids, tokens, cost, latency, route, provider, model, status). The client IP is stored only as a salted SHA-256 hash (`IP_HASH_SALT`).

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | (empty) | Required for the `anthropic` provider. Keep it in `.env`, never commit it. |
| `LLM_PROVIDER` | `anthropic` | Only `anthropic` is implemented. |
| `LLM_MODEL` | `claude-haiku-5-5` | |
| `LLM_MAX_TOKENS` | `600` | |
| `LLM_TEMPERATURE` | (empty) | Empty means not sent. Claude Haiku 5.5 rejects non-default sampling values; set it only for models that accept it. |
| `RETRIEVAL_TOP_K` | `6` | Chunks sent to the LLM on the RAG route. |
| `LLM_PRICE_INPUT_PER_MTOK` / `LLM_PRICE_OUTPUT_PER_MTOK` | `0.10` / `0.50` | USD per million tokens. Update them if you change the model. |
| `DAILY_BUDGET_USD` | `1.00` | |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_DAY` | `10/minute` / `100/day` | |
| `IP_HASH_SALT` | `ask-washington` | Set your own value. |

### Providers

`app/llm.py` builds the chat model from `LLM_PROVIDER`; the chain only sees a LangChain chat model. Planned, not implemented yet: `ollama` (a local model on a home machine) and `openai_compatible` (an OpenAI-compatible inference API such as Localia). Adding one means writing a builder and registering it in `PROVIDERS`. An unknown value fails with an error that lists the supported providers.

### Manual check against the real model

```bash
uv run uvicorn app.main:app
uv run python -m scripts.ask_check   # 5 questions, writes reports/P18-3_real_answers.json
```

This spends real tokens: the 5 questions cost about USD 0.002 with Claude Haiku 5.5.

## Known issues

- **Rootful Podman machine on Windows does not forward ports to `localhost`.** Run `scripts\dev-db-host.ps1` before starting the app (see [Windows with a rootful Podman machine](#windows-with-a-rootful-podman-machine)). Enabling the machine's user-mode networking did not fix it with Podman 6.0.2.
- **Containers fail to start with `aardvark-dns failed to start ... open resolv.conf: No such file or directory`.** This can happen after turning the Podman machine's user-mode networking off again: the machine loses its `/etc/resolv.conf` link. Restore it and start the containers again:

  ```powershell
  podman machine ssh "sudo ln -sf /mnt/wsl/resolv.conf /etc/resolv.conf"
  ```

## Project layout

```
app/        FastAPI app (main.py), settings (config.py), database helpers (db.py),
            source loading and chunking (ingestion.py), embeddings and pgvector (vector_store.py),
            answer chain (rag.py), ranking route (ranking.py), LLM factory (llm.py),
            budget and log tables (usage.py)
scripts/    init_db.py, ingest.py, search_check.py, ask_check.py, dev-db-host.ps1
tests/      pytest suite
data/       Source documents (see data/README.md); papers.yaml is committed
reports/    Reports for each stage
```

## License

MIT. See [LICENSE](LICENSE).
