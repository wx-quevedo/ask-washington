"""Embedding model, pgvector store and the table that tracks what has been ingested."""

import logging
from functools import lru_cache

import psycopg
from llama_index.core.schema import TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db import connect

EMBED_DIM = 384  # BAAI/bge-small-en-v1.5
# PGVectorStore prefixes the name with "data_", so the table is public.data_chunks.
VECTOR_TABLE = "chunks"
VECTOR_TABLE_SQL = "data_chunks"
TRACKING_TABLE = "ingested_documents"

# Recommended by BAAI for short retrieval queries with bge v1.5 models.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def quiet_logs() -> None:
    """Hide per-request HTTP logs and progress bars from the model download libraries."""
    from huggingface_hub.utils import disable_progress_bars
    from transformers.utils import logging as transformers_logging

    for name in ("httpx", "httpx2", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(name).setLevel(logging.ERROR)
    disable_progress_bars()
    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()


@lru_cache
def get_embed_model() -> HuggingFaceEmbedding:
    quiet_logs()
    return HuggingFaceEmbedding(
        model_name=get_settings().embedding_model,
        query_instruction=BGE_QUERY_INSTRUCTION,
        normalize=True,
    )


def get_vector_store() -> PGVectorStore:
    url = make_url(get_settings().database_url)
    return PGVectorStore.from_params(
        host=url.host,
        port=str(url.port or 5432),
        database=url.database,
        user=url.username,
        password=url.password,
        table_name=VECTOR_TABLE,
        embed_dim=EMBED_DIM,
        use_jsonb=True,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )


def ensure_tracking_table() -> None:
    with connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
                doc_id       text PRIMARY KEY,
                doc_type     text NOT NULL,
                title        text NOT NULL,
                content_hash text NOT NULL,
                chunk_count  integer NOT NULL,
                ingested_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )


def tracked_hashes(doc_types: tuple[str, ...]) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT doc_id, content_hash FROM {TRACKING_TABLE} WHERE doc_type = ANY(%s)",
            (list(doc_types),),
        ).fetchall()
    return dict(rows)


def delete_document(store: PGVectorStore, doc_id: str) -> None:
    """Remove a document's chunks and its tracking row."""
    store.delete(ref_doc_id=doc_id)
    with connect() as conn:
        conn.execute(f"DELETE FROM {TRACKING_TABLE} WHERE doc_id = %s", (doc_id,))


def add_document(store: PGVectorStore, nodes: list[TextNode]) -> None:
    """Embed and store the chunks of one document, then record its hash."""
    texts = [node.get_content(metadata_mode="embed") for node in nodes]
    embeddings = get_embed_model().get_text_embedding_batch(texts)
    for node, embedding in zip(nodes, embeddings, strict=True):
        node.embedding = embedding
    store.add(nodes)
    meta = nodes[0].metadata
    with connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {TRACKING_TABLE} (doc_id, doc_type, title, content_hash, chunk_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (doc_id) DO UPDATE SET
                doc_type = EXCLUDED.doc_type, title = EXCLUDED.title,
                content_hash = EXCLUDED.content_hash, chunk_count = EXCLUDED.chunk_count,
                ingested_at = now()
            """,
            (meta["doc_id"], meta["doc_type"], meta["title"], meta["content_hash"], len(nodes)),
        )


def reset(doc_types: tuple[str, ...] | None = None) -> None:
    """Drop everything, or only the chunks and tracking rows of some doc types."""
    with connect() as conn:
        if doc_types is None:
            conn.execute(f"DROP TABLE IF EXISTS {VECTOR_TABLE_SQL}")
            conn.execute(f"DROP TABLE IF EXISTS {TRACKING_TABLE}")
            return
        try:
            conn.execute(
                f"DELETE FROM {VECTOR_TABLE_SQL} WHERE metadata_->>'doc_type' = ANY(%s)",
                (list(doc_types),),
            )
        except psycopg.errors.UndefinedTable:
            conn.rollback()
        conn.execute(f"DELETE FROM {TRACKING_TABLE} WHERE doc_type = ANY(%s)", (list(doc_types),))


def counts_by_type() -> list[tuple[str, int, int]]:
    """(doc_type, documents, chunks) for the report."""
    with connect() as conn:
        return conn.execute(
            f"""
            SELECT doc_type, count(*), sum(chunk_count)::int
            FROM {TRACKING_TABLE} GROUP BY doc_type ORDER BY doc_type
            """
        ).fetchall()
