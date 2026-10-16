"""Enable the pgvector extension in the configured database.

Usage: uv run python -m scripts.init_db
"""

from app import db


def main() -> None:
    db.init_db()
    print(f"vector extension version: {db.vector_extension_version()}")


if __name__ == "__main__":
    main()
