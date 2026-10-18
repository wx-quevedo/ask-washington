"""Query translation: detection, fallback on error or timeout, fusion of both queries.

The LLM is simulated; nothing here calls the API.
"""

import logging
import time

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.retrievers import BaseRetriever

from app import retrieval
from app.retrieval import Hit, retrieve_many
from app.translation import QueryTranslation, QueryTranslator, needs_translation
from tests.test_ask import TEST_DAY, RecordingFakeLLM, cleanup, fake_llm

# ------------------------------------------------------------------ detection


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Cuántas gafas Meta Quest se sincronizaron en la sesión de Bagó?", "es"),
        ("Qué experiencia tiene en realidad virtual", "es"),
        ("How many Meta Quest headsets did he synchronize?", None),
        ("What is plan-vivo-kit?", None),
        ("Buscapez", None),  # ambiguous: searched as it is
        ("XR", None),
    ],
)
def test_needs_translation(question, expected):
    assert needs_translation(question) == expected


# ------------------------------------------------------------------ translator


def translator_llm(text="How many Meta Quest headsets were synchronized in the Bagó session?"):
    return GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content=text,
                    usage_metadata={"input_tokens": 60, "output_tokens": 15, "total_tokens": 75},
                )
            ]
        )
    )


def test_spanish_question_is_translated_and_both_queries_are_searched():
    question = "¿Cuántas gafas Meta Quest se sincronizaron en la sesión de Bagó?"
    result = QueryTranslator(translator_llm(), timeout_s=4)(question)

    assert result.lang == "es"
    assert (
        result.translated == "How many Meta Quest headsets were synchronized in the Bagó session?"
    )
    assert result.queries == [question, result.translated]
    assert (result.input_tokens, result.output_tokens) == (60, 15)
    assert result.error is None


def test_english_question_makes_no_call():
    class Exploding(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise AssertionError("English questions must not be translated")

    result = QueryTranslator(Exploding(messages=iter([])), timeout_s=4)("What is plan-vivo-kit?")
    assert result.translated is None and result.queries == ["What is plan-vivo-kit?"]
    assert result.latency_ms == 0


def test_translation_error_falls_back_to_the_original(caplog):
    class Failing(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise ConnectionError("network down")

    question = "¿Qué hizo en Sansar?"
    with caplog.at_level(logging.WARNING, logger="ask_washington.translation"):
        result = QueryTranslator(Failing(messages=iter([])), timeout_s=4)(question)

    assert result.translated is None
    assert result.queries == [question]
    assert result.error == "ConnectionError"
    assert "using the original question" in caplog.text


def test_translation_timeout_falls_back_quickly(caplog):
    class Slow(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            time.sleep(2)
            return super()._generate(*args, **kwargs)

    question = "¿Qué precisión tiene Gazetrack?"
    started = time.perf_counter()
    with caplog.at_level(logging.WARNING, logger="ask_washington.translation"):
        result = QueryTranslator(Slow(messages=iter([AIMessage(content="x")])), timeout_s=0.2)(
            question
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 1.5  # does not wait for the slow call
    assert result.queries == [question]
    assert result.error.startswith("timeout")
    assert "timeout" in caplog.text


def test_empty_or_quoted_output_is_cleaned_or_rejected():
    quoted = QueryTranslator(translator_llm('  "What did he build at Stanford?"  '))(
        "¿Qué construyó en Stanford?"
    )
    assert quoted.translated == "What did he build at Stanford?"
    empty = QueryTranslator(translator_llm("   "))("¿Qué construyó en Stanford?")
    assert empty.translated is None and empty.error == "ValueError"


# ------------------------------------------------------------------ fusion


def _hit(node_id):
    return Hit(node_id=node_id, text=node_id, metadata={"doc_id": node_id.split("#")[0]}, score=0.0)


def test_retrieve_many_fuses_both_queries_with_rrf_and_caps_per_document(monkeypatch):
    rankings = {
        "original": ["paper-a#0", "cv#1", "readme#1", "readme#2"],
        "translated": ["cv#1", "cv#2", "readme#3", "readme#4", "readme#5"],
    }
    calls = []

    def fake_hybrid(query, k, candidates, max_per_doc=None):
        calls.append(query)
        return [_hit(i) for i in rankings[query]]

    monkeypatch.setattr(retrieval, "hybrid_search", fake_hybrid)
    hits = retrieve_many(["original", "translated"], mode="hybrid", top_k=5, max_per_doc=3)
    ids = [h.node_id for h in hits]

    assert calls == ["original", "translated"]
    assert ids[0] == "cv#1"  # found by both queries: first after the fusion
    assert set(ids) <= set(rankings["original"]) | set(rankings["translated"])
    assert sum(1 for i in ids if i.startswith("readme")) <= 3  # cap after the fusion
    assert len(ids) == 5


def test_retrieve_many_with_one_query_is_the_normal_search(monkeypatch):
    seen = {}

    def fake_retrieve(query, **kwargs):
        seen["query"] = query
        return [_hit("cv#1")]

    monkeypatch.setattr(retrieval, "retrieve", fake_retrieve)
    assert [h.node_id for h in retrieve_many(["same", "same"], mode="hybrid")] == ["cv#1"]
    assert seen["query"] == "same"


# ------------------------------------------------------------------ /ask


class TwoQueryRetriever(BaseRetriever):
    """Records which queries were used; returns one fixed source."""

    used: list = []

    def _get_relevant_documents(self, query, *, run_manager):
        type(self).used = [query]
        return [self._doc()]

    def retrieve_many(self, queries):
        type(self).used = list(queries)
        return [self._doc()]

    @staticmethod
    def _doc():
        return Document(
            page_content="Delivered a group VR session on 30 synchronized Meta Quest headsets.",
            metadata={
                "title": "CV - XR + AI Engineer",
                "doc_type": "cv",
                "section": "Experience",
                "public_url": "https://www.linkedin.com/in/wxquevedo",
                "node_id": "cv-xr-ai-engineer#003",
                "score": 0.6,
            },
        )


def test_ask_searches_with_the_translation_and_answers_in_spanish():
    from app.main import app, get_llm, get_retriever, get_today, get_translator, limiter

    llm = fake_llm("Sincronizó 30 visores Meta Quest [1].")
    translator = QueryTranslator(translator_llm(), timeout_s=4)
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: TwoQueryRetriever()
    app.dependency_overrides[get_translator] = lambda: translator
    app.dependency_overrides[get_today] = lambda: TEST_DAY
    limiter.reset()
    question = "¿Cuántas gafas Meta Quest se sincronizaron en la sesión de Bagó?"
    try:
        with TestClient(app) as client:
            cleanup()
            response = client.post("/ask", json={"question": question, "lang": "es"})
            cleanup()
    finally:
        app.dependency_overrides.clear()
        limiter.reset()

    assert response.status_code == 200
    body = response.json()
    assert TwoQueryRetriever.used == [
        question,
        "How many Meta Quest headsets were synchronized in the Bagó session?",
    ]
    # The answer prompt keeps the original question and asks for Spanish.
    assert question in llm.last_prompt
    assert "Write the whole answer in Spanish." in llm.last_prompt
    assert body["lang"] == "es"
    # Translation tokens are part of the cost of the answer (fake: 1000+60 in, 100+15 out).
    assert body["usage"] == {"input_tokens": 1060, "output_tokens": 115}


def test_ask_still_answers_when_translation_fails():
    from app.main import app, get_llm, get_retriever, get_today, get_translator, limiter

    class Failing(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise TimeoutError("slow provider")

    llm = RecordingFakeLLM(
        messages=iter(
            [
                AIMessage(
                    content="Respuesta [1].",
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                )
            ]
        )
    )
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: TwoQueryRetriever()
    app.dependency_overrides[get_translator] = lambda: QueryTranslator(
        Failing(messages=iter([])), 4
    )
    app.dependency_overrides[get_today] = lambda: TEST_DAY
    limiter.reset()
    question = "¿Qué hizo en Sansar como desarrollador?"
    try:
        with TestClient(app) as client:
            cleanup()
            response = client.post("/ask", json={"question": question, "lang": "es"})
            cleanup()
    finally:
        app.dependency_overrides.clear()
        limiter.reset()

    assert response.status_code == 200
    assert TwoQueryRetriever.used == [question]  # original question only


def test_translation_flag_off_gives_no_translator():
    from app.config import get_settings
    from app.main import get_translator

    settings = get_settings().model_copy(update={"query_translation": False})
    assert get_translator(settings) is None


def test_query_translation_reads_on_off():
    from app.config import Settings

    assert Settings(_env_file=None, query_translation="off").query_translation is False
    assert Settings(_env_file=None, query_translation="on").query_translation is True
    assert Settings(_env_file=None).query_translation is True


def test_query_translation_dataclass_ignores_identical_translation():
    same = QueryTranslation(original="Unity", lang="es", translated="unity")
    assert same.queries == ["Unity"]
