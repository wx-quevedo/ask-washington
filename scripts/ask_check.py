"""Send a fixed set of questions to a running /ask endpoint and save the results.

This calls the real LLM, so it spends a little money (a few tenths of a cent with Haiku).

Usage:
    uv run uvicorn app.main:app            # in another terminal
    uv run python -m scripts.ask_check [--url http://127.0.0.1:8000] [--out reports/x.json]
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

from app.config import get_settings
from app.usage import cost_usd

QUESTIONS = (
    "What XR experience does Washington have?",
    "What is his most cited paper?",
    "Production ML experience",
    "What is plan-vivo-kit?",
    "¿Qué hizo en rehabilitación con realidad virtual?",
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default="reports/P18-3_real_answers.json")
    args = parser.parse_args()

    settings = get_settings()
    results, total_cost = [], 0.0
    with httpx.Client(base_url=args.url, timeout=60) as client:
        for question in QUESTIONS:
            response = client.post("/ask", json={"question": question})
            body = response.json()
            if response.status_code != 200:
                print(f"{response.status_code} {question}: {body}")
                results.append({"question": question, "status": response.status_code, **body})
                continue
            usage = body["usage"]
            cost = float(cost_usd(settings, usage["input_tokens"], usage["output_tokens"]))
            total_cost += cost
            results.append({"question": question, "status": 200, "cost_usd": cost, **body})
            print(f"\nQ: {question}\n{body['answer']}")
            print(
                f"  {usage['input_tokens']} in / {usage['output_tokens']} out, "
                f"${cost:.6f}, {body['latency_ms']} ms, {len(body['sources'])} sources"
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"total_cost_usd": round(total_cost, 6), "results": results},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\ntotal estimated cost: ${total_cost:.6f} -> {out}")


if __name__ == "__main__":
    main()
