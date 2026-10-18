"""POST /ask tests with a simulated LLM and retriever: no API calls, no spend.

They need the database (usage_daily and qa_log). Test rows use a fixed day and the
TestClient address, and are deleted afterwards.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.retrievers import BaseRetriever

from app import usage
from app.config import get_settings
from app.db import connect
from app.llm import UnknownProviderError, get_chat_model
from app.main import app, get_llm, get_retriever, get_today, limiter
from app.ranking import answer_ranking, detect_intents

TEST_DAY = date(1999, 1, 1)


class FakeRetriever(BaseRetriever):
    def _get_relevant_documents(self, query, *, run_manager):
        return [
            Document(
                page_content="Washington built VR training simulators in Unity.",
                metadata={
                    "title": "CV - XR + AI Engineer",
                    "doc_type": "cv",
                    "section": "Summary",
                    "public_url": "https://www.linkedin.com/in/wxquevedo",
                    "node_id": "cv-xr-ai-engineer#001",
                    "score": 0.61,
                },
            ),
            Document(
                page_content="plan-vivo-kit keeps a living project plan.",
                metadata={
                    "title": "GitHub repository plan-vivo-kit",
                    "doc_type": "repo_readme",
                    "section": "Overview",
                    "public_url": "https://github.com/wx-quevedo/plan-vivo-kit",
                    "node_id": "repo-plan-vivo-kit#000",
                    "score": 0.55,
                },
            ),
        ]


class RecordingFakeLLM(GenericFakeChatModel):
    """Fake chat model that remembers the prompt it received."""

    last_prompt: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.last_prompt = "\n".join(str(m.content) for m in messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def fake_llm(text: str = "Washington builds VR training simulators [1].", n: int = 20):
    messages = iter(
        [
            AIMessage(
                content=text,
                usage_metadata={"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100},
            )
            for _ in range(n)
        ]
    )
    return RecordingFakeLLM(messages=messages)


def cleanup() -> None:
    ip_hash = usage.hash_ip(get_settings(), "testclient")
    with connect() as conn:
        conn.execute("DELETE FROM usage_daily WHERE day = %s", (TEST_DAY,))
        conn.execute("DELETE FROM qa_log WHERE ip_hash = %s", (ip_hash,))


@pytest.fixture
def llm():
    return fake_llm()


@pytest.fixture
def client(llm):
    settings = get_settings()
    saved = settings.model_dump()
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    app.dependency_overrides[get_today] = lambda: TEST_DAY
    limiter.reset()
    with TestClient(app) as test_client:
        cleanup()
        yield test_client
        cleanup()
    app.dependency_overrides.clear()
    for key, value in saved.items():
        setattr(settings, key, value)
    limiter.reset()


def test_answer_format_and_citations(client, llm):
    response = client.post("/ask", json={"question": "What XR experience does he have?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "lang", "sources", "provider", "model", "latency_ms", "usage"}
    assert body["lang"] == "en"
    assert body["answer"] == "Washington builds VR training simulators [1]."
    assert body["usage"] == {"input_tokens": 1000, "output_tokens": 100}
    assert body["provider"] == "anthropic"
    assert [s["n"] for s in body["sources"]] == [1, 2]
    first = body["sources"][0]
    assert first == {
        "n": 1,
        "title": "CV - XR + AI Engineer",
        "doc_type": "cv",
        "section": "Summary",
        "public_url": "https://www.linkedin.com/in/wxquevedo",
        "score": 0.61,
    }
    # The prompt numbers the sources the same way the response does.
    assert "[1] CV - XR + AI Engineer / Summary (cv)" in llm.last_prompt
    assert "[2] GitHub repository plan-vivo-kit / Overview (repo_readme)" in llm.last_prompt
    assert "<question>\nWhat XR experience does he have?\n</question>" in llm.last_prompt


def test_usage_and_log_are_recorded(client):
    client.post("/ask", json={"question": "What XR experience does he have?"})

    with connect() as conn:
        day = conn.execute(
            "SELECT requests, input_tokens, output_tokens, cost_usd"
            " FROM usage_daily WHERE day = %s",
            (TEST_DAY,),
        ).fetchone()
        log = conn.execute(
            "SELECT route, status, source_ids, ip_hash FROM qa_log WHERE ip_hash = %s",
            (usage.hash_ip(get_settings(), "testclient"),),
        ).fetchone()
    # 1000 * 0.10 / 1M + 100 * 0.50 / 1M = 0.00015 USD
    assert day[:3] == (1, 1000, 100) and float(day[3]) == pytest.approx(0.00015)
    assert log[0] == "rag" and log[1] == "ok"
    assert log[2] == ["cv-xr-ai-engineer#001", "repo-plan-vivo-kit#000"]
    assert len(log[3]) == 16 and "testclient" not in log[3]


@pytest.mark.parametrize("question", ["", "hi", "   ab   ", "x" * 501])
def test_rejects_question_length(client, question):
    response = client.post("/ask", json={"question": question})
    assert response.status_code == 422


def test_accepts_question_at_limits(client):
    assert client.post("/ask", json={"question": "abc"}).status_code == 200
    assert client.post("/ask", json={"question": "x" * 500}).status_code == 200


def test_rate_limit_per_ip(client):
    get_settings().rate_limit_per_minute = "2/minute"
    codes = [
        client.post("/ask", json={"question": "What is plan-vivo-kit?"}).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_daily_budget_returns_429(client, llm):
    get_settings().daily_budget_usd = 0.0002  # one fake answer costs 0.00015
    first = client.post("/ask", json={"question": "What is plan-vivo-kit?"})
    second = client.post("/ask", json={"question": "What is plan-vivo-kit?"})
    third = client.post("/ask", json={"question": "What is plan-vivo-kit?"})

    assert first.status_code == 200
    assert second.status_code == 200  # spent 0.00015 < 0.0002 before this call
    assert third.status_code == 429
    assert "daily usage budget" in third.json()["detail"]
    assert float(usage.spent_on(TEST_DAY)) == pytest.approx(0.0003)


def test_ranking_route_most_cited(client, llm):
    response = client.post("/ask", json={"question": "What is his most cited paper?"})

    assert response.status_code == 200
    body = response.json()
    top = body["sources"][0]
    assert top["title"] == "Unity3D-MatLab simulator in real time for robotics applications"
    assert top["doc_type"] == "paper"
    assert top["public_url"] == "https://doi.org/10.1007/978-3-319-40621-3_19"
    assert top["score"] is None
    assert "88 citations [1]" in llm.last_prompt


def test_ranking_facts_are_deterministic():
    result = answer_ranking("Which is the most cited paper?")
    assert result.intents == ["most_cited"]
    assert (
        result.facts[0]
        .splitlines()[1]
        .startswith("1. Unity3D-MatLab simulator in real time for robotics applications (2016")
    )
    assert "88 citations [1]" in result.facts[0]
    assert result.sources[0]["doc_id"] == "paper-p01"

    metrics = answer_ranking("What is his h-index?")
    assert "640 citations, h-index 14, i10-index 21" in metrics.facts[0]


@pytest.mark.parametrize(
    ("question", "intents"),
    [
        ("What is his most cited paper?", ["most_cited"]),
        ("¿Cuál es su artículo más citado?", ["most_cited"]),
        ("What is his latest paper?", ["latest"]),
        ("How many papers has he published?", ["count"]),
        ("¿Cuántas publicaciones tiene?", ["count"]),
        ("What is his h-index?", ["metrics"]),
        ("What XR experience does Washington have?", []),
        ("Production ML experience", []),
    ],
)
def test_detect_intents(question, intents):
    assert detect_intents(question) == intents


def test_unknown_provider_gives_clear_error():
    settings = get_settings().model_copy(update={"llm_provider": "ollama"})
    with pytest.raises(UnknownProviderError) as excinfo:
        get_chat_model(settings)
    message = str(excinfo.value)
    assert "Unknown LLM_PROVIDER 'ollama'" in message
    assert "Supported: anthropic" in message


def test_anthropic_provider_builds_without_calling_api():
    settings = get_settings().model_copy(
        update={"anthropic_api_key": "sk-test", "llm_model": "claude-haiku-5-5"}
    )
    model = get_chat_model(settings)
    assert model.model == "claude-haiku-5-5"
    assert model.max_tokens == 600
    assert model.temperature is None


def test_empty_temperature_means_not_sent():
    from app.config import Settings

    assert Settings(_env_file=None, llm_temperature="").llm_temperature is None
    assert Settings(_env_file=None, llm_temperature="0.3").llm_temperature == 0.3
