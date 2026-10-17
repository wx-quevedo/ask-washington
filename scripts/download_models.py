"""Download the local models into the Hugging Face cache (used at image build time).

Usage: python -m scripts.download_models [extra cross-encoder model names ...]

Always downloads EMBEDDING_MODEL. Rerankers are optional: pass their names to bake them
into the image (only needed for RETRIEVAL_MODE=rerank or rerank_light).
"""

import sys

from app.config import get_settings


def main() -> None:
    from sentence_transformers import CrossEncoder, SentenceTransformer

    embedding = get_settings().embedding_model
    SentenceTransformer(embedding)
    print(f"embedding model ready: {embedding}")
    for name in sys.argv[1:]:
        CrossEncoder(name)
        print(f"reranker ready: {name}")


if __name__ == "__main__":
    main()
