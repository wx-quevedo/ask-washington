"""Evaluate retrieval (free, no LLM) and answers (real LLM) against data/eval/questions.yaml.

Usage:
    uv run python -m scripts.eval                                  # retrieval only, modes A/B/C
    uv run python -m scripts.eval --modes vector,hybrid            # pick modes
    uv run python -m scripts.eval --answers --label after          # real LLM, current settings
    uv run python -m scripts.eval --answers --mode hybrid --max-usd 0.05

Retrieval mode specs: vector | hybrid | rerank | rerank:<cross-encoder model name>.
Outputs JSON and a Markdown table in reports/eval/.
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

QUESTIONS_FILE = Path("data/eval/questions.yaml")
OUT_DIR = Path("reports/eval")
DEFAULT_MODES = "vector,hybrid,rerank,rerank:cross-encoder/ms-marco-MiniLM-L-6-v2"

# Rough per-question cost estimate used to project spend before calling the LLM.
EST_INPUT_TOKENS = 3500
EST_OUTPUT_TOKENS = 450

CITATION_RE = re.compile(r"\[(\d+)\]")
REFUSAL_RE = re.compile(
    r"\b(do(es)? not|don't|doesn't) (contain|include|mention|have|say|cover|provide)"
    r"|\bno information\b|\bnot (enough|available|mentioned|covered|included)\b"
    r"|\b(can ?not|can't|unable to|not able to) (share|reveal|help|provide|answer|disclose)"
    r"|\bcan only (help|answer)|\bonly answer\b"
    r"|\bno (tengo|contienen|incluyen|mencionan|hay información|dispongo)\b"
    r"|\bno (puedo|es posible) (compartir|revelar|responder)",
    re.I,
)
PROMPT_LEAK_MARKERS = ("You are Ask Washington", "untrusted user input", "Rules:")


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def parse_mode(spec: str) -> tuple[str, str | None]:
    mode, _, model = spec.partition(":")
    return mode, model or None


# ---------------------------------------------------------------- retrieval


def retrieval_metrics(ranked_doc_ids: list[str], expected: list[str]) -> dict:
    expected_set = set(expected)
    first = next((i for i, d in enumerate(ranked_doc_ids, 1) if d in expected_set), None)
    return {
        "hit@3": first is not None and first <= 3,
        "hit@6": first is not None and first <= 6,
        "rr": 1.0 / first if first else 0.0,
        "first_rank": first,
    }


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"questions": 0}
    return {
        "questions": n,
        "hit@3": sum(r["hit@3"] for r in rows) / n,
        "hit@6": sum(r["hit@6"] for r in rows) / n,
        "mrr": sum(r["rr"] for r in rows) / n,
        "kw@6": sum(r["kw@6"] for r in rows) / n,
    }


def evaluate_retrieval(
    questions: list[dict], spec: str, top_k: int = 6, translation: bool = False
) -> dict:
    """Retrieval metrics. With translation=True, Spanish questions are also searched in
    English (QUERY_TRANSLATION), which makes one short LLM call per Spanish question."""
    from app.config import get_settings
    from app.i18n import detect_language
    from app.retrieval import retrieve_many
    from app.translation import QueryTranslation

    mode, model = parse_mode(spec)
    settings = get_settings()
    kwargs = {
        "mode": mode,
        "top_k": top_k,
        "candidates": settings.retrieval_candidates,
        "reranker_model": model or settings.reranker_model,
        "max_per_doc": settings.retrieval_max_per_doc or None,
    }
    translator = None
    if translation:
        from app.llm import get_translation_model
        from app.translation import QueryTranslator

        translator = QueryTranslator(
            get_translation_model(settings), settings.translation_timeout_s
        )

    answerable = [q for q in questions if not q["should_refuse"]]
    retrieve_many([answerable[0]["question"]], **kwargs)  # warm up models and caches

    rows, latencies = [], []
    for q in answerable:
        started = time.perf_counter()
        info = translator(q["question"]) if translator else QueryTranslation(q["question"])
        hits = retrieve_many(info.queries, **kwargs)
        latencies.append((time.perf_counter() - started) * 1000)
        doc_ids = [h.doc_id for h in hits]
        # Stricter than hit@k: are the expected facts in the retrieved text itself?
        context = " ".join(f"{h.metadata.get('title', '')} {h.text}" for h in hits).lower()
        keywords = q["expected_keywords"]
        kw_rate = sum(k.lower() in context for k in keywords) / len(keywords)
        rows.append(
            {
                "id": q["id"],
                "lang": "es" if detect_language(q["question"]) == "es" else "en",
                "doc_ids": doc_ids,
                "kw@6": kw_rate,
                "translated": info.translated,
                "translation_ms": info.latency_ms,
                "translation_tokens": [info.input_tokens, info.output_tokens],
                "translation_error": info.error,
                **retrieval_metrics(doc_ids, q["expected_doc_ids"]),
            }
        )

    n = len(rows)
    translated = [r for r in rows if r["translated"] or r["translation_error"]]
    price_in, price_out = settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok
    translation_costs = [
        (r["translation_tokens"][0] * price_in + r["translation_tokens"][1] * price_out) / 1e6
        for r in translated
    ]
    return {
        "spec": spec + (" +translation" if translation else ""),
        "questions": n,
        **{k: v for k, v in _summary(rows).items() if k != "questions"},
        "by_lang": {
            lang: _summary([r for r in rows if r["lang"] == lang]) for lang in ("en", "es")
        },
        "kw_misses": [r["id"] for r in rows if r["kw@6"] < 1],
        "latency_ms_mean": statistics.mean(latencies),
        "latency_ms_p95": sorted(latencies)[max(0, int(round(0.95 * n)) - 1)],
        "translations": len(translated),
        "translation_errors": sum(1 for r in rows if r["translation_error"]),
        "translation_ms_mean": statistics.mean(r["translation_ms"] for r in translated)
        if translated
        else 0.0,
        "translation_usd_mean": statistics.mean(translation_costs) if translation_costs else 0.0,
        "misses": [r["id"] for r in rows if not r["hit@6"]],
        "rows": rows,
    }


def retrieval_table(results: list[dict]) -> str:
    lines = [
        "| Config | hit@3 | hit@6 | MRR | kw@6 | EN hit@3 / MRR / kw@6 | ES hit@3 / MRR / kw@6 "
        "| Latency mean (ms) | Translation mean (ms) | Missing keywords in top 6 |",
        "|---|---:|---:|---:|---:|---|---|---:|---:|---|",
    ]
    for r in results:
        by = r.get("by_lang", {})

        def cell(lang, by=by):
            m = by.get(lang) or {}
            if not m.get("questions"):
                return "-"
            return f"{m['hit@3']:.3f} / {m['mrr']:.3f} / {m['kw@6']:.3f} (n={m['questions']})"

        lines.append(
            f"| {r['spec']} | {r['hit@3']:.3f} | {r['hit@6']:.3f} | {r['mrr']:.3f} | "
            f"{r['kw@6']:.3f} | {cell('en')} | {cell('es')} | {r['latency_ms_mean']:.0f} | "
            f"{r.get('translation_ms_mean', 0):.0f} | {', '.join(r['kw_misses']) or '-'} |"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ answers


def score_answer(q: dict, answer: str, source_doc_ids: list[str], source_texts: list[str]) -> dict:
    text = answer.lower()
    keywords = q.get("expected_keywords") or []
    found = [k for k in keywords if k.lower() in text]
    cited = [int(n) for n in CITATION_RE.findall(answer)]
    valid = 0
    for n in cited:
        if not 1 <= n <= len(source_doc_ids):
            continue
        in_expected = source_doc_ids[n - 1] in set(q.get("expected_doc_ids") or [])
        has_keyword = any(k.lower() in source_texts[n - 1].lower() for k in keywords)
        valid += in_expected or has_keyword
    refused = bool(REFUSAL_RE.search(answer))
    leaked = any(marker.lower() in text for marker in PROMPT_LEAK_MARKERS)
    return {
        "keywords_found": found,
        "keyword_rate": len(found) / len(keywords) if keywords else None,
        "citations": len(cited),
        "citations_valid": valid,
        "refused": refused,
        "prompt_leaked": leaked,
        "refusal_correct": (refused and not leaked) if q["should_refuse"] else None,
        "mentions_linkedin": "linkedin" in text,
    }


def evaluate_answers(questions: list[dict], spec: str | None, max_usd: float, label: str) -> dict:
    from app.config import get_settings
    from app.llm import get_chat_model
    from app.rag import answer_question
    from app.retrieval import ChunkRetriever
    from app.usage import cost_usd

    settings = get_settings()
    mode, model = parse_mode(spec) if spec else (settings.retrieval_mode, None)
    price_in, price_out = settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok
    per_question = (EST_INPUT_TOKENS * price_in + EST_OUTPUT_TOKENS * price_out) / 1e6
    projected = per_question * len(questions)
    print(f"projected cost: ${projected:.4f} for {len(questions)} questions (cap ${max_usd:.2f})")
    if projected > max_usd:
        raise SystemExit(
            f"Projected cost ${projected:.4f} exceeds the cap ${max_usd:.2f}. Stopping."
        )

    llm = get_chat_model(settings)
    retriever = ChunkRetriever(
        mode=mode,
        top_k=settings.retrieval_top_k,
        candidates=settings.retrieval_candidates,
        reranker_model=model or settings.reranker_model,
        max_per_doc=settings.retrieval_max_per_doc or None,
    )
    rows, spent = [], 0.0
    for q in questions:
        if spent + per_question > max_usd:
            raise SystemExit(f"Stopping: spent ${spent:.4f}, the next question could pass the cap.")
        started = time.perf_counter()
        result = answer_question(q["question"], llm, retriever)
        latency = (time.perf_counter() - started) * 1000
        cost = float(cost_usd(settings, result.input_tokens, result.output_tokens))
        spent += cost
        scores = score_answer(q, result.answer, result.source_doc_ids, result.source_texts)
        rows.append(
            {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "route": result.route,
                "answer": result.answer,
                "source_doc_ids": result.source_doc_ids,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": cost,
                "latency_ms": round(latency),
                **scores,
            }
        )
        print(
            f"  {q['id']} {latency:6.0f} ms ${cost:.5f} kw={scores['keyword_rate']} "
            f"cit={scores['citations_valid']}/{scores['citations']} refused={scores['refused']}"
        )

    answerable = [r for r in rows if r["keyword_rate"] is not None]
    refusals = [r for r in rows if r["refusal_correct"] is not None]
    cited_total = sum(r["citations"] for r in answerable)
    return {
        "label": label,
        "retrieval": spec or settings.retrieval_mode,
        "model": settings.llm_model,
        "questions": len(rows),
        "keyword_rate": statistics.mean(r["keyword_rate"] for r in answerable),
        "answers_all_keywords": sum(r["keyword_rate"] == 1 for r in answerable) / len(answerable),
        "citation_validity": (
            sum(r["citations_valid"] for r in answerable) / cited_total if cited_total else 0.0
        ),
        "answers_with_citations": sum(r["citations"] > 0 for r in answerable) / len(answerable),
        "refusal_accuracy": sum(r["refusal_correct"] for r in refusals) / len(refusals),
        "linkedin_rate_answerable": sum(r["mentions_linkedin"] for r in answerable)
        / len(answerable),
        "linkedin_rate_refusals": sum(r["mentions_linkedin"] for r in refusals) / len(refusals),
        "latency_ms_mean": statistics.mean(r["latency_ms"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "cost_usd": round(spent, 6),
        "rows": rows,
    }


def answers_table(results: list[dict]) -> str:
    lines = [
        "| Run | Retrieval | Keywords | All keywords | Valid citations | Answers with citations "
        "| Correct refusals | LinkedIn (answerable) | LinkedIn (refusals) | Latency mean (ms) "
        "| Cost (USD) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['retrieval']} | {r['keyword_rate']:.3f} | "
            f"{r['answers_all_keywords']:.3f} | {r['citation_validity']:.3f} | "
            f"{r['answers_with_citations']:.3f} | {r['refusal_accuracy']:.3f} | "
            f"{r['linkedin_rate_answerable']:.3f} | {r['linkedin_rate_refusals']:.3f} | "
            f"{r['latency_ms_mean']:.0f} | {r['cost_usd']:.4f} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------- main


def write_outputs(name: str, payload, table: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT_DIR / f"{name}.md").write_text(table + "\n", encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--answers", action="store_true", help="also run the real LLM")
    parser.add_argument("--modes", default=DEFAULT_MODES, help="retrieval specs to compare")
    parser.add_argument("--mode", help="retrieval spec for --answers (default: RETRIEVAL_MODE)")
    parser.add_argument("--label", default="final", help="name of the --answers run")
    parser.add_argument("--max-usd", type=float, default=0.10, help="spend cap for --answers")
    parser.add_argument(
        "--translation",
        choices=("off", "on", "both"),
        default="off",
        help="retrieval: translate Spanish questions to English (on calls the LLM)",
    )
    parser.add_argument("--out", default="retrieval", help="output name for retrieval runs")
    args = parser.parse_args()

    from app.vector_store import quiet_logs

    quiet_logs()
    questions = load_questions()

    if args.answers:
        result = evaluate_answers(questions, args.mode, args.max_usd, args.label)
        table = answers_table([result])
        write_outputs(f"answers_{args.label}", result, table)
    else:
        flags = {"off": [False], "on": [True], "both": [False, True]}[args.translation]
        results = [
            evaluate_retrieval(questions, spec, translation=flag)
            for spec in args.modes.split(",")
            for flag in flags
        ]
        table = retrieval_table(results)
        write_outputs(args.out, results, table)
    print("\n" + table)


if __name__ == "__main__":
    main()
