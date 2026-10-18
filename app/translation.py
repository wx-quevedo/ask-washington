"""Translate non-English questions to English before retrieval.

The sources are in English and the embedding model (bge-small-en) is English-only, so a
Spanish question retrieves poorly. The question is translated with one short LLM call and
both phrasings are searched (see retrieval.retrieve_many). The answer still uses the
user's language: the answer prompt receives the original question.

The translation never breaks /ask: on any error or after the timeout the original
question is used alone and a warning is logged.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.i18n import detect_language

logger = logging.getLogger("ask_washington.translation")

SYSTEM = (
    "You translate search queries into English for a document search engine about the "
    "professional experience of Washington X. Quevedo. Questions refer to him in the third "
    'person, so translate possessives and pronouns such as "su" as "his" or "he". '
    "Reply with the English translation of the query only: no quotes, no explanations, "
    "no answer to the question. Keep names, product names, acronyms and numbers unchanged."
)
MAX_QUERY_CHARS = 500

# One worker is enough: the call is short and the timeout bounds how long it can block.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="query-translation")


@dataclass
class QueryTranslation:
    original: str
    lang: str | None = None  # detected language when it is clearly not English
    translated: str | None = None  # English query, None when not translated
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    @property
    def queries(self) -> list[str]:
        """Queries to search with: the original, plus the translation when it differs."""
        if self.translated and self.translated.strip().lower() != self.original.strip().lower():
            return [self.original, self.translated]
        return [self.original]


def needs_translation(question: str) -> str | None:
    """The detected language when the question is clearly not English, else None.

    Cheap heuristic (app.i18n.detect_language), no LLM call. Ambiguous questions such as a
    single name or acronym are searched as they are.
    """
    lang = detect_language(question)
    return lang if lang and lang != "en" else None


def _clean(text: str) -> str:
    text = " ".join(text.strip().split())
    return text.strip("\"'“”«»").strip()[:MAX_QUERY_CHARS]


def _text(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


class QueryTranslator:
    """Callable that returns a QueryTranslation for a question."""

    def __init__(self, llm: BaseChatModel, timeout_s: float = 4.0):
        self.llm = llm
        self.timeout_s = timeout_s

    def __call__(self, question: str) -> QueryTranslation:
        result = QueryTranslation(original=question, lang=needs_translation(question))
        if result.lang is None:  # English or ambiguous: nothing extra
            logger.info(
                "query translation skipped: lang=%s", detect_language(question) or "ambiguous"
            )
            return result
        messages = [SystemMessage(content=SYSTEM), HumanMessage(content=question)]
        started = time.perf_counter()
        future = _EXECUTOR.submit(self.llm.invoke, messages)
        try:
            message = future.result(timeout=self.timeout_s)
            translated = _clean(_text(message))
            if not translated:
                raise ValueError("empty translation")
            usage = getattr(message, "usage_metadata", None) or {}
            result.translated = translated
            result.input_tokens = int(usage.get("input_tokens", 0))
            result.output_tokens = int(usage.get("output_tokens", 0))
        except FutureTimeout:
            future.cancel()
            result.error = f"timeout after {self.timeout_s:.1f} s"
        except Exception as exc:  # any provider error: fall back to the original question
            result.error = exc.__class__.__name__
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        if result.error:
            logger.warning(
                "query translation failed (%s, %d ms); using the original question",
                result.error,
                result.latency_ms,
            )
        else:
            logger.info(
                "query translation: lang=%s latency_ms=%d translated=%r",
                result.lang,
                result.latency_ms,
                result.translated[:200],
            )
        return result
