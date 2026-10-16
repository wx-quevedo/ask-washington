import psycopg

from app.config import get_settings

CONNECT_TIMEOUT_SECONDS = 3


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS)


def init_db() -> None:
    """Enable the pgvector extension. Safe to run more than once."""
    with connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def vector_extension_version() -> str | None:
    """Return the installed pgvector version, or None if the extension is missing."""
    with connect() as conn:
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    return row[0] if row else None


def check_db() -> dict:
    """Report database connectivity and pgvector status for the health endpoint."""
    try:
        version = vector_extension_version()
    except psycopg.Error as exc:
        return {"connected": False, "vector_extension": False, "error": exc.__class__.__name__}
    return {"connected": True, "vector_extension": version is not None, "vector_version": version}
