"""The web page at / and the client IP seen behind the reverse proxy."""

import pytest
from fastapi.testclient import TestClient

from app import usage
from app.config import get_settings
from app.db import connect
from app.main import app, get_llm, get_retriever, get_today, limiter
from tests.test_ask import TEST_DAY, FakeRetriever, fake_llm

PROXY = ("127.0.0.1", 50000)  # nginx on the same host (trusted by default)
OUTSIDER = ("198.51.100.9", 50001)  # any other peer (documentation range)
REAL_CLIENT = "203.0.113.7"


def test_index_serves_the_page():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        styles = client.get("/static/styles.css")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    html = page.text
    assert "<title>Ask Washington</title>" in html
    assert 'for="question"' in html and 'id="question"' in html
    assert html.count('class="suggestion"') == 4
    assert "Answers are generated from public sources and may contain errors." in html
    for link in (
        "https://www.linkedin.com/in/wxquevedo",
        "https://github.com/wx-quevedo",
        "https://scholar.google.com/citations?user=zPNPhwkAAAAJ",
    ):
        assert link in html
    assert "<script>" not in html  # no inline script, so a strict CSP can be used
    assert script.status_code == 200 and 'fetch("/ask"' in script.text
    assert styles.status_code == 200


def logged_ip_hashes() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT ip_hash FROM qa_log WHERE question = 'proxy ip test'"
        ).fetchall()
    return [r[0] for r in rows]


@pytest.fixture
def overrides():
    app.dependency_overrides[get_llm] = lambda: fake_llm()
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    app.dependency_overrides[get_today] = lambda: TEST_DAY
    limiter.reset()

    def cleanup():
        with connect() as conn:
            conn.execute("DELETE FROM qa_log WHERE question = 'proxy ip test'")
            conn.execute("DELETE FROM usage_daily WHERE day = %s", (TEST_DAY,))

    cleanup()
    yield
    cleanup()
    app.dependency_overrides.clear()
    limiter.reset()


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "expected_ip"),
    [
        (PROXY, REAL_CLIENT, REAL_CLIENT),  # nginx adds the real client
        (PROXY, f"10.9.9.9, {REAL_CLIENT}", REAL_CLIENT),  # rightmost untrusted entry wins
        (OUTSIDER, REAL_CLIENT, OUTSIDER[0]),  # header ignored from untrusted peers
        (PROXY, None, PROXY[0]),  # no header: the peer itself
    ],
)
def test_client_ip_behind_proxy(overrides, peer, forwarded_for, expected_ip):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    with TestClient(app, client=peer) as client:
        response = client.post("/ask", json={"question": "proxy ip test"}, headers=headers)

    assert response.status_code == 200
    assert logged_ip_hashes() == [usage.hash_ip(get_settings(), expected_ip)]


def test_rate_limit_counts_the_real_client_not_the_proxy(overrides):
    settings = get_settings()
    saved = settings.rate_limit_per_minute
    settings.rate_limit_per_minute = "1/minute"
    try:
        with TestClient(app, client=PROXY) as client:
            first = client.post(
                "/ask",
                json={"question": "proxy ip test"},
                headers={"X-Forwarded-For": "203.0.113.1"},
            )
            other = client.post(
                "/ask",
                json={"question": "proxy ip test"},
                headers={"X-Forwarded-For": "203.0.113.2"},
            )
            again = client.post(
                "/ask",
                json={"question": "proxy ip test"},
                headers={"X-Forwarded-For": "203.0.113.1"},
            )
    finally:
        settings.rate_limit_per_minute = saved

    # Two different clients behind the same proxy each get their own limit.
    assert [first.status_code, other.status_code, again.status_code] == [200, 200, 429]
