"""Download the local models at image build time, or verify that they load offline.

Usage:
    python -m scripts.download_models [cross-encoder model ...]   # download (build stage)
    python -m scripts.download_models --verify [cross-encoder ...]  # load offline (final stage)

It uses the same loaders as the app (app.vector_store.get_embed_model and
app.retrieval.get_reranker), so the files land exactly where the app looks for them at
runtime: HF_HOME for Hugging Face files and LLAMA_INDEX_CACHE_DIR for the folder that
LlamaIndex passes to sentence-transformers. The tiktoken encoding used by LlamaIndex is
cached too (TIKTOKEN_CACHE_DIR).
"""

import os
import sys


def main() -> None:
    args = sys.argv[1:]
    verify = "--verify" in args
    rerankers = [a for a in args if a != "--verify"]

    if verify and os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("--verify must run with HF_HUB_OFFLINE=1")
    for name in ("HF_HOME", "LLAMA_INDEX_CACHE_DIR", "TIKTOKEN_CACHE_DIR"):
        print(f"{name}={os.environ.get(name, '(not set)')}")

    from llama_index.core.utils import get_tokenizer

    from app.config import get_settings
    from app.retrieval import get_reranker
    from app.vector_store import get_embed_model

    get_tokenizer()("warm up the tiktoken cache")
    vector = get_embed_model().get_text_embedding("Ask Washington model check")
    if len(vector) != 384:
        raise SystemExit(f"unexpected embedding size {len(vector)}")
    print(f"embedding model ok: {get_settings().embedding_model} (dim {len(vector)})")

    for name in rerankers:
        score = get_reranker(name).predict([("query", "passage")])
        print(f"reranker ok: {name} (score {float(score[0]):.3f})")

    print("offline load verified" if verify else "models downloaded")


if __name__ == "__main__":
    main()
