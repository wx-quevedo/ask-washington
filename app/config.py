from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://askw:askw_dev@localhost:5432/ask_washington"
    anthropic_api_key: str = ""
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Answer generation
    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-5-5"
    llm_max_tokens: int = 600
    # None means "do not send": Claude Haiku 5.5 rejects non-default sampling values.
    llm_temperature: float | None = None
    retrieval_top_k: int = 6
    # vector | hybrid | rerank | rerank_light (see app/retrieval.py)
    retrieval_mode: str = "hybrid"
    retrieval_candidates: int = 20
    reranker_model: str = "BAAI/bge-reranker-base"

    # Prices in USD per million tokens, used for the daily budget.
    llm_price_input_per_mtok: float = 0.10
    llm_price_output_per_mtok: float = 0.50
    daily_budget_usd: float = 1.00

    # Per-IP rate limits (slowapi syntax).
    rate_limit_per_minute: str = "10/minute"
    rate_limit_per_day: str = "100/day"
    # Salt for the IP hash stored in qa_log.
    ip_hash_salt: str = "ask-washington"
    # Peers allowed to set X-Forwarded-For (comma-separated IPs or CIDRs). Only the local
    # reverse proxy belongs here; in Docker that is the bridge gateway of the app network.
    forwarded_allow_ips: str = "127.0.0.1"
    # Origins allowed to embed the page in an iframe and to send it postMessage events
    # (comma-separated, e.g. "https://portfolio.example"). Empty: same origin only.
    embed_allowed_origins: str = ""

    @field_validator("llm_temperature", mode="before")
    @classmethod
    def empty_temperature_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
