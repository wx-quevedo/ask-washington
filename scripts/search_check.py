"""Run a few test queries against the index and show the top results.

Usage: uv run python -m scripts.search_check [--top-k 3] ["custom query" ...]
"""

import argparse
import sys

from llama_index.core import VectorStoreIndex

from app import vector_store

DEFAULT_QUERIES = (
    "What XR experience does Washington have?",
    "Which papers are about rehabilitation?",
    "What is plan-vivo-kit?",
    "Production ML experience",
    "Most cited paper",
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queries", nargs="*", help="queries to run (default: built-in set)")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    index = VectorStoreIndex.from_vector_store(
        vector_store.get_vector_store(), embed_model=vector_store.get_embed_model()
    )
    retriever = index.as_retriever(similarity_top_k=args.top_k)

    for query in args.queries or DEFAULT_QUERIES:
        print(f"\nQ: {query}")
        for rank, hit in enumerate(retriever.retrieve(query), start=1):
            meta = hit.node.metadata
            section = f" / {meta['section']}" if meta.get("section") else ""
            print(f"  {rank}. {hit.score:.3f}  [{meta['doc_type']}] {meta['title']}{section}")
            print(f"     {meta['public_url']}")


if __name__ == "__main__":
    main()
