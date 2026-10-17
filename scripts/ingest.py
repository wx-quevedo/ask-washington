"""Ingest the public sources in data/ into pgvector.

Usage:
    uv run python -m scripts.ingest                 # ingest new or changed documents
    uv run python -m scripts.ingest --only paper    # only one doc_type
    uv run python -m scripts.ingest --reset         # drop the index and ingest everything again

Idempotent: each document's content hash is stored in the ingested_documents table.
Unchanged documents are skipped, changed ones are replaced, and documents that no
longer exist in the sources are removed.
"""

import argparse
import sys
import time

from app import db, vector_store
from app.ingestion import DOC_TYPES, load_documents, split_document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete indexed data before ingesting")
    parser.add_argument("--only", choices=DOC_TYPES, help="process a single doc_type")
    return parser.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    doc_types = (args.only,) if args.only else DOC_TYPES
    started = time.perf_counter()

    db.init_db()
    if args.reset:
        vector_store.reset(doc_types if args.only else None)
        print(f"reset: {', '.join(doc_types) if args.only else 'all'}")
    vector_store.ensure_tracking_table()
    store = vector_store.get_vector_store()

    documents = load_documents(doc_types)
    known = vector_store.tracked_hashes(doc_types)
    added = updated = skipped = chunks = 0

    for doc in documents:
        doc_id, new_hash = doc.doc_id, doc.metadata["content_hash"]
        if known.get(doc_id) == new_hash:
            skipped += 1
            continue
        if doc_id in known:
            vector_store.delete_document(store, doc_id)
            updated += 1
        else:
            added += 1
        nodes = split_document(doc)
        vector_store.add_document(store, nodes)
        chunks += len(nodes)
        print(f"  {doc.metadata['doc_type']:<12} {doc_id:<34} {len(nodes):>3} chunks")

    current = {doc.doc_id for doc in documents}
    removed = [doc_id for doc_id in known if doc_id not in current]
    for doc_id in removed:
        vector_store.delete_document(store, doc_id)

    elapsed = time.perf_counter() - started
    print(
        f"documents: {len(documents)} | added {added} | updated {updated} | "
        f"unchanged {skipped} | removed {len(removed)} | new chunks {chunks} | {elapsed:.1f}s"
    )
    print("index totals (doc_type, documents, chunks):")
    for doc_type, n_docs, n_chunks in vector_store.counts_by_type():
        print(f"  {doc_type:<12} {n_docs:>3} docs {n_chunks:>4} chunks")


if __name__ == "__main__":
    main()
