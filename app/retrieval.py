"""Retrieval over the data_chunks table: vector, hybrid (vector + full text, fused with RRF)
and hybrid followed by a local cross-encoder reranker.

Modes (RETRIEVAL_MODE):
- vector: pgvector cosine similarity only (P18.2 behaviour).
- hybrid: vector and Postgres full-text candidates fused with Reciprocal Rank Fusion.
- rerank: hybrid candidates re-scored by a cross-encoder (RERANKER_MODEL), keeping the best top_k.
- rerank_light: the same with a small cross-encoder (ms-marco-MiniLM-L-6-v2), faster on CPU.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.db import connect

RETRIEVAL_MODES = ("vector", "hybrid", "rerank", "rerank_light")
LIGHT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RRF_K = 60
# At most this many chunks of one document in the hybrid top_k, so a long README cannot
# push out the only chunk of another document that has the answer (U9).
MAX_CHUNKS_PER_DOC = 3

# Title and section are searchable too, so "plan-vivo-kit" matches the repo chunks.
FTS_DOCUMENT = (
    "to_tsvector('english', coalesce(metadata_->>'title', '') || ' ' || "
    "coalesce(metadata_->>'section', '') || ' ' || text)"
)


@dataclass
class Hit:
    node_id: str
    text: str
    metadata: dict
    score: float

    @property
    def doc_id(self) -> str:
        return self.metadata.get("doc_id") or self.node_id.split("#", 1)[0]


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score(id) = sum over rankings of 1 / (k + rank), rank from 1.

    Ties keep the order in which ids first appear, so the result is deterministic.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    order = {item: i for i, item in enumerate(dict.fromkeys(i for r in rankings for i in r))}
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))


# ------------------------------------------------------------------ searches


@lru_cache
def _vector_index():
    from llama_index.core import VectorStoreIndex

    from app import vector_store

    return VectorStoreIndex.from_vector_store(
        vector_store.get_vector_store(), embed_model=vector_store.get_embed_model()
    )


def vector_search(query: str, k: int) -> list[Hit]:
    hits = _vector_index().as_retriever(similarity_top_k=k).retrieve(query)
    return [
        Hit(
            node_id=hit.node.node_id,
            text=hit.node.get_content(),
            metadata=dict(hit.node.metadata),
            score=float(hit.score or 0.0),
        )
        for hit in hits
    ]


def ensure_fulltext_index() -> None:
    with connect() as conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS data_chunks_fts_idx "
            f"ON data_chunks USING gin ({FTS_DOCUMENT})"
        )


def fulltext_search(query: str, k: int) -> list[Hit]:
    """Postgres full-text search. Query terms are OR-ed: any matching term counts,
    and ts_rank_cd rewards chunks that match more of them, closer together."""
    sql = f"""
        WITH q AS (
            SELECT replace(plainto_tsquery('english', %(query)s)::text, '&', '|') AS terms
        )
        SELECT node_id, text, metadata_, ts_rank_cd({FTS_DOCUMENT}, q.terms::tsquery) AS rank
        FROM data_chunks, q
        WHERE q.terms <> '' AND {FTS_DOCUMENT} @@ q.terms::tsquery
        ORDER BY rank DESC, node_id
        LIMIT %(k)s
    """
    with connect() as conn:
        rows = conn.execute(sql, {"query": query, "k": k}).fetchall()
    return [Hit(node_id=r[0], text=r[1], metadata=r[2], score=float(r[3])) for r in rows]


def cap_per_document(hits: list[Hit], k: int, max_per_doc: int | None) -> list[Hit]:
    """Keep the order, skip chunks of documents that already have max_per_doc, stop at k."""
    if not max_per_doc:
        return hits[:k]
    kept, per_doc = [], {}
    for hit in hits:
        if per_doc.get(hit.doc_id, 0) >= max_per_doc:
            continue
        per_doc[hit.doc_id] = per_doc.get(hit.doc_id, 0) + 1
        kept.append(hit)
        if len(kept) == k:
            break
    return kept


def hybrid_search(query: str, k: int, candidates: int, max_per_doc: int | None = None) -> list[Hit]:
    vector_hits = vector_search(query, candidates)
    text_hits = fulltext_search(query, candidates)
    by_id = {h.node_id: h for h in text_hits} | {h.node_id: h for h in vector_hits}
    fused = rrf_fuse([[h.node_id for h in vector_hits], [h.node_id for h in text_hits]])
    hits = [
        Hit(node_id=i, text=by_id[i].text, metadata=by_id[i].metadata, score=score)
        for i, score in fused
    ]
    return cap_per_document(hits, k, max_per_doc)


@lru_cache
def get_reranker(model_name: str):
    from sentence_transformers import CrossEncoder

    from app.vector_store import quiet_logs

    quiet_logs()
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
    return CrossEncoder(model_name, max_length=512)


def rerank(query: str, hits: list[Hit], k: int, model_name: str) -> list[Hit]:
    if not hits:
        return []
    passages = [
        f"{h.metadata.get('title', '')} / {h.metadata.get('section', '')}\n{h.text}" for h in hits
    ]
    scores = get_reranker(model_name).predict([(query, p) for p in passages])
    ranked = sorted(zip(hits, scores, strict=True), key=lambda hs: -float(hs[1]))
    return [
        Hit(node_id=h.node_id, text=h.text, metadata=h.metadata, score=float(s))
        for h, s in ranked[:k]
    ]


def retrieve(
    query: str,
    *,
    mode: str = "vector",
    top_k: int = 6,
    candidates: int = 20,
    reranker_model: str = "BAAI/bge-reranker-base",
    max_per_doc: int | None = MAX_CHUNKS_PER_DOC,
) -> list[Hit]:
    if mode == "vector":
        return vector_search(query, top_k)
    if mode == "hybrid":
        return hybrid_search(query, top_k, candidates, max_per_doc)
    if mode == "rerank":
        return rerank(query, hybrid_search(query, candidates, candidates), top_k, reranker_model)
    if mode == "rerank_light":
        return rerank(query, hybrid_search(query, candidates, candidates), top_k, LIGHT_RERANKER)
    raise ValueError(f"Unknown RETRIEVAL_MODE '{mode}'. Supported: {', '.join(RETRIEVAL_MODES)}.")


def retrieve_many(
    queries: list[str],
    *,
    mode: str = "vector",
    top_k: int = 6,
    candidates: int = 20,
    reranker_model: str = "BAAI/bge-reranker-base",
    max_per_doc: int | None = MAX_CHUNKS_PER_DOC,
) -> list[Hit]:
    """Search with several phrasings of the same question (for example the original
    Spanish question and its English translation) and fuse the rankings with RRF.

    The per-document cap and the reranker apply after the fusion; the reranker uses the
    last query (the English translation when there is one).
    """
    queries = [q for i, q in enumerate(queries) if q and q not in queries[:i]]
    if len(queries) <= 1:
        return retrieve(
            queries[0] if queries else "",
            mode=mode,
            top_k=top_k,
            candidates=candidates,
            reranker_model=reranker_model,
            max_per_doc=max_per_doc,
        )
    if mode not in RETRIEVAL_MODES:
        raise ValueError(
            f"Unknown RETRIEVAL_MODE '{mode}'. Supported: {', '.join(RETRIEVAL_MODES)}."
        )
    rankings = []
    for query in queries:
        if mode == "vector":
            rankings.append(vector_search(query, candidates))
        else:
            rankings.append(hybrid_search(query, candidates, candidates))
    by_id: dict[str, Hit] = {}
    for hits in rankings:
        for hit in hits:
            by_id.setdefault(hit.node_id, hit)
    fused = rrf_fuse([[h.node_id for h in hits] for hits in rankings])
    merged = [
        Hit(node_id=i, text=by_id[i].text, metadata=by_id[i].metadata, score=score)
        for i, score in fused
    ]
    if mode == "vector":
        return merged[:top_k]
    if mode == "hybrid":
        return cap_per_document(merged, top_k, max_per_doc)
    model = LIGHT_RERANKER if mode == "rerank_light" else reranker_model
    return rerank(queries[-1], merged[:candidates], top_k, model)


class ChunkRetriever(BaseRetriever):
    """LangChain retriever over data_chunks with a configurable retrieval mode."""

    mode: str = "vector"
    top_k: int = 6
    candidates: int = 20
    reranker_model: str = "BAAI/bge-reranker-base"
    max_per_doc: int | None = MAX_CHUNKS_PER_DOC

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        hits = retrieve(
            query,
            mode=self.mode,
            top_k=self.top_k,
            candidates=self.candidates,
            reranker_model=self.reranker_model,
            max_per_doc=self.max_per_doc,
        )
        return self._documents(hits)

    def retrieve_many(self, queries: list[str]) -> list[Document]:
        hits = retrieve_many(
            queries,
            mode=self.mode,
            top_k=self.top_k,
            candidates=self.candidates,
            reranker_model=self.reranker_model,
            max_per_doc=self.max_per_doc,
        )
        return self._documents(hits)

    @staticmethod
    def _documents(hits: list[Hit]) -> list[Document]:
        return [
            Document(
                page_content=h.text,
                metadata={**h.metadata, "node_id": h.node_id, "score": h.score},
            )
            for h in hits
        ]
