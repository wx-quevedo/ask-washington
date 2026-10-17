"""Daily spend counter and question log, stored in Postgres."""

import hashlib
from datetime import date
from decimal import Decimal

from app.config import Settings
from app.db import connect


def ensure_tables() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_daily (
                day           date PRIMARY KEY,
                requests      integer NOT NULL DEFAULT 0,
                input_tokens  bigint  NOT NULL DEFAULT 0,
                output_tokens bigint  NOT NULL DEFAULT 0,
                cost_usd      numeric(12, 6) NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_log (
                id            bigserial PRIMARY KEY,
                created_at    timestamptz NOT NULL DEFAULT now(),
                question      text NOT NULL,
                source_ids    text[] NOT NULL DEFAULT '{}',
                input_tokens  integer NOT NULL DEFAULT 0,
                output_tokens integer NOT NULL DEFAULT 0,
                cost_usd      numeric(12, 6) NOT NULL DEFAULT 0,
                latency_ms    integer NOT NULL,
                route         text NOT NULL,
                provider      text NOT NULL,
                model         text NOT NULL,
                status        text NOT NULL,
                ip_hash       text NOT NULL
            )
            """
        )


def cost_usd(settings: Settings, input_tokens: int, output_tokens: int) -> Decimal:
    cost = (
        Decimal(input_tokens) * Decimal(str(settings.llm_price_input_per_mtok))
        + Decimal(output_tokens) * Decimal(str(settings.llm_price_output_per_mtok))
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


def spent_on(day: date) -> Decimal:
    with connect() as conn:
        row = conn.execute("SELECT cost_usd FROM usage_daily WHERE day = %s", (day,)).fetchone()
    return Decimal(row[0]) if row else Decimal(0)


def record_usage(day: date, input_tokens: int, output_tokens: int, cost: Decimal) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO usage_daily (day, requests, input_tokens, output_tokens, cost_usd)
            VALUES (%s, 1, %s, %s, %s)
            ON CONFLICT (day) DO UPDATE SET
                requests = usage_daily.requests + 1,
                input_tokens = usage_daily.input_tokens + EXCLUDED.input_tokens,
                output_tokens = usage_daily.output_tokens + EXCLUDED.output_tokens,
                cost_usd = usage_daily.cost_usd + EXCLUDED.cost_usd
            """,
            (day, input_tokens, output_tokens, cost),
        )


def hash_ip(settings: Settings, ip: str) -> str:
    return hashlib.sha256(f"{settings.ip_hash_salt}:{ip}".encode()).hexdigest()[:16]


def log_question(
    *,
    question: str,
    source_ids: list[str],
    input_tokens: int,
    output_tokens: int,
    cost: Decimal,
    latency_ms: int,
    route: str,
    provider: str,
    model: str,
    status: str,
    ip_hash: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO qa_log (question, source_ids, input_tokens, output_tokens, cost_usd,
                                latency_ms, route, provider, model, status, ip_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                question,
                source_ids,
                input_tokens,
                output_tokens,
                cost,
                latency_ms,
                route,
                provider,
                model,
                status,
                ip_hash,
            ),
        )
