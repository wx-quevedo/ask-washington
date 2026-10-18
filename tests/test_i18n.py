"""Interface language, answer language, localized API messages and embedding headers.

The LLM is simulated (tests.test_ask), so nothing here calls the API.
"""

import json
import re
from html import escape

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import i18n
from app.config import get_settings
from app.main import app, get_llm, get_retriever, get_today, limiter
from tests.test_ask import TEST_DAY, FakeRetriever, RecordingFakeLLM, cleanup, fake_llm

EN = json.loads((i18n.I18N_DIR / "en.json").read_text(encoding="utf-8"))
ES = json.loads((i18n.I18N_DIR / "es.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ texts


def test_language_files_have_the_same_keys_and_no_emojis():
    assert EN.keys() == ES.keys()
    emoji = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
    for value in [*EN.values(), *ES.values()]:
        assert value.strip() and not emoji.search(value)


def test_template_has_no_hardcoded_visible_text():
    template = (i18n.I18N_DIR.parent / "index.html").read_text(encoding="utf-8")
    body = re.split(r"<body[^>]*>", template, maxsplit=1)[1]
    text = re.sub(r"<[^>]+>", " ", body)  # drop tags (and their attributes)
    text = re.sub(r"\{\{\s*[a-z0-9_]+\s*\}\}", " ", text)  # drop placeholders
    assert text.split() == []
    placeholders = set(re.findall(r"\{\{\s*([a-z0-9_]+)\s*\}\}", template))
    assert placeholders - {"embed_class", "embed_origins"} <= EN.keys()


def test_javascript_has_no_visible_english_strings():
    script = (i18n.I18N_DIR.parent / "app.js").read_text(encoding="utf-8")
    for value in EN.values():
        if len(value) > 12:  # skip short tokens such as "CV" or "LinkedIn"
            assert value not in script


@pytest.mark.parametrize(
    ("url", "lang", "texts"),
    [("/", "en", EN), ("/?lang=en", "en", EN), ("/?lang=es", "es", ES), ("/?lang=fr", "en", EN)],
)
def test_page_language(url, lang, texts):
    with TestClient(app) as client:
        html = client.get(url).text
    assert f'<html lang="{lang}">' in html
    assert escape(texts["subtitle"]) in html
    assert escape(texts["suggestion_1"]) in html
    assert f'placeholder="{escape(texts["placeholder"])}"' in html
    other = ES if texts is EN else EN
    assert escape(other["subtitle"]) not in html


def test_widget_mode():
    with TestClient(app) as client:
        normal = client.get("/?lang=es").text
        widget = client.get("/?lang=es&embed=1").text
    assert '<body class="">' in normal
    assert '<body class="embed">' in widget
    assert ES["question_label"] in widget


# ---------------------------------------------------------------- headers


@pytest.fixture
def origins():
    settings = get_settings()
    saved = settings.embed_allowed_origins
    yield settings
    settings.embed_allowed_origins = saved


def test_frame_ancestors_without_allowed_origins(origins):
    origins.embed_allowed_origins = ""
    with TestClient(app) as client:
        response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert csp.endswith("frame-ancestors 'self'")
    assert "default-src 'self'" in csp
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert '<meta name="ask-washington-embed-origins" content="">' in response.text


def test_frame_ancestors_with_allowed_origins(origins):
    origins.embed_allowed_origins = (
        "https://portfolio.example, http://localhost:5173/, "
        "javascript:alert(1), https://bad.example/path"
    )
    with TestClient(app) as client:
        response = client.get("/?embed=1")
        api = client.get("/health")
    csp = response.headers["content-security-policy"]
    assert csp.endswith("frame-ancestors 'self' https://portfolio.example http://localhost:5173")
    assert "javascript" not in csp and "bad.example" not in csp
    assert "x-frame-options" not in response.headers
    assert (
        '<meta name="ask-washington-embed-origins" '
        'content="https://portfolio.example http://localhost:5173">'
    ) in response.text
    assert api.headers["content-security-policy"] == csp


def test_parse_origins():
    assert i18n.parse_origins("") == []
    assert i18n.parse_origins(" https://a.example ,https://a.example/,http://b.test:8080") == [
        "https://a.example",
        "http://b.test:8080",
    ]
    assert i18n.parse_origins("a.example, ftp://x.example, https://x.example/p") == []


# --------------------------------------------------------- answer language


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is plan-vivo-kit?", "en"),
        ("What did he build at Stanford University?", "en"),
        ("¿Qué hizo en rehabilitación con realidad virtual?", "es"),
        ("Qué experiencia tiene en realidad virtual", "es"),
        ("Buscapez", None),
        ("XR", None),
        ("Production ML experience", None),
    ],
)
def test_detect_language(question, expected):
    assert i18n.detect_language(question) == expected


@pytest.fixture
def client_and_llm():
    llm = fake_llm()
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    app.dependency_overrides[get_today] = lambda: TEST_DAY
    limiter.reset()
    with TestClient(app) as client:
        cleanup()
        yield client, llm
        cleanup()
    app.dependency_overrides.clear()
    limiter.reset()


@pytest.mark.parametrize(
    ("payload", "answer_lang", "page_lang"),
    [
        ({"question": "What is plan-vivo-kit?"}, "English", "English"),  # lang defaults to en
        ({"question": "What is plan-vivo-kit?", "lang": "en"}, "English", "English"),
        ({"question": "¿Qué es plan-vivo-kit?", "lang": "es"}, "Spanish", "Spanish"),
        ({"question": "¿Qué es plan-vivo-kit?", "lang": "en"}, "Spanish", "English"),
        ({"question": "What is plan-vivo-kit?", "lang": "es"}, "English", "Spanish"),
        ({"question": "Buscapez", "lang": "es"}, "Spanish", "Spanish"),  # ambiguous
        ({"question": "Buscapez", "lang": "en"}, "English", "English"),
        ({"question": "Buscapez", "lang": "de"}, "English", "English"),  # unknown -> en
    ],
)
def test_language_instruction_sent_to_the_model(client_and_llm, payload, answer_lang, page_lang):
    client, llm = client_and_llm
    response = client.post("/ask", json=payload)

    assert response.status_code == 200
    assert response.json()["lang"] == {"English": "en", "Spanish": "es"}[answer_lang]
    assert f"Write the whole answer in {answer_lang}." in llm.last_prompt
    assert f"The page is shown in {page_lang}" in llm.last_prompt


def test_ranking_route_follows_the_language(client_and_llm):
    client, llm = client_and_llm
    response = client.post("/ask", json={"question": "¿Cuál es su artículo más citado?"})

    assert response.status_code == 200
    body = response.json()
    assert body["lang"] == "es"
    assert body["sources"][0]["doc_type"] == "paper"
    assert "Write the whole answer in Spanish." in llm.last_prompt
    assert "88 citations [1]" in llm.last_prompt


# ------------------------------------------------------ localized errors


def test_validation_error_in_requested_language(client_and_llm):
    client, _ = client_and_llm
    es = client.post("/ask", json={"question": "hi", "lang": "es"})
    en = client.post("/ask", json={"question": "hi"})
    query = client.post("/ask?lang=es", json={"question": "x" * 501})
    assert es.status_code == en.status_code == query.status_code == 422
    assert es.json()["detail"] == i18n.api_message("validation", "es")
    assert en.json()["detail"] == i18n.api_message("validation", "en")
    assert query.json()["detail"] == i18n.api_message("validation", "es")


def test_rate_limit_message_in_requested_language(client_and_llm):
    client, _ = client_and_llm
    settings = get_settings()
    saved = settings.rate_limit_per_minute
    settings.rate_limit_per_minute = "1/minute"
    try:
        client.post("/ask?lang=es", json={"question": "¿Qué es plan-vivo-kit?", "lang": "es"})
        limited = client.post(
            "/ask?lang=es", json={"question": "¿Qué es plan-vivo-kit?", "lang": "es"}
        )
    finally:
        settings.rate_limit_per_minute = saved
    assert limited.status_code == 429
    assert limited.json()["detail"] == i18n.api_message("rate_limit", "es")


def test_budget_message_in_answer_language(client_and_llm):
    client, _ = client_and_llm
    settings = get_settings()
    saved = settings.daily_budget_usd
    settings.daily_budget_usd = 0.0
    try:
        es = client.post("/ask", json={"question": "Buscapez", "lang": "es"})
        en_question = client.post("/ask", json={"question": "What is Buscapez?", "lang": "es"})
    finally:
        settings.daily_budget_usd = saved
    assert es.status_code == en_question.status_code == 429
    assert es.json()["detail"] == i18n.api_message("budget", "es")
    assert en_question.json()["detail"] == i18n.api_message("budget", "en")


class FailingLLM(RecordingFakeLLM):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("provider down")


def test_unavailable_message_in_answer_language(client_and_llm):
    client, _ = client_and_llm
    app.dependency_overrides[get_llm] = lambda: FailingLLM(messages=iter([AIMessage(content="")]))
    response = client.post("/ask", json={"question": "¿Qué es Buscapez?", "lang": "en"})
    assert response.status_code == 502
    assert response.json()["detail"] == i18n.api_message("unavailable", "es")


# ------------------------------------------------------- portfolio embedding

PORTFOLIO_ORIGINS = [
    "https://washingtonquevedo.com",
    "https://www.washingtonquevedo.com",
    "http://localhost:4321",
]


def test_portfolio_origins_are_allowed_and_others_are_not(origins):
    origins.embed_allowed_origins = ",".join(PORTFOLIO_ORIGINS)
    with TestClient(app) as client:
        response = client.get("/?embed=1&lang=es")
    csp = response.headers["content-security-policy"]
    ancestors = csp.split("frame-ancestors ", 1)[1].split()
    assert ancestors == ["'self'", *PORTFOLIO_ORIGINS]
    for other in (
        "http://washingtonquevedo.com",  # http, not https
        "https://washingtonquevedo.com.evil.example",
        "https://evil.example",
        "http://localhost:4322",
        "http://127.0.0.1:4321",
        "*",
    ):
        assert other not in ancestors
    assert "x-frame-options" not in response.headers
    assert f'content="{" ".join(PORTFOLIO_ORIGINS)}"' in response.text


@pytest.mark.parametrize(("lang", "texts"), [("en", EN), ("es", ES)])
def test_widget_has_a_discreet_disclaimer(lang, texts):
    with TestClient(app) as client:
        widget = client.get(f"/?embed=1&lang={lang}").text
    assert f'<p class="disclaimer" data-i18n="disclaimer">{texts["disclaimer"]}</p>' in widget
