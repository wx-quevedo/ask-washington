"""End-to-end check of the embed postMessage protocol in a real browser.

Needs Playwright, which is not a project dependency. Run it ad hoc with:

    uv run --with playwright python -m playwright install chromium   # once
    uv run --with playwright pytest tests/e2e -q

Without Playwright the whole module is skipped.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_HOST, APP_PORT = "127.0.0.1", 8101
APP_URL = f"http://{APP_HOST}:{APP_PORT}"
ALLOWED_PORT, OTHER_PORT = 8102, 8103
ALLOWED_ORIGIN = f"http://localhost:{ALLOWED_PORT}"
IFRAME_SRC = f"{APP_URL}/?embed=1&lang=en"

I18N = REPO_ROOT / "app" / "static" / "i18n"
EN = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
ES = json.loads((I18N / "es.json").read_text(encoding="utf-8"))

PARENT_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Parent</title></head>
<body>
  <iframe id="widget" src="{src}" width="420" height="600"></iframe>
  <script>
    window.received = [];
    window.addEventListener("message", function (event) {{
      window.received.push({{ origin: event.origin, data: event.data }});
    }});
    window.sendLang = function (lang) {{
      document.getElementById("widget").contentWindow.postMessage(
        {{ type: "ask-washington:lang", lang: lang }}, "*");
    }};
  </script>
</body>
</html>
"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


def _wait_for(url: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - keep polling until the deadline
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not answer within {timeout}s: {last_error}")


@pytest.fixture(scope="module")
def app_server():
    env = dict(os.environ, EMBED_ALLOWED_ORIGINS=ALLOWED_ORIGIN, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            APP_HOST,
            "--port",
            str(APP_PORT),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(APP_URL + "/")
        yield APP_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


@pytest.fixture(scope="module")
def parent_servers(tmp_path_factory):
    root = tmp_path_factory.mktemp("parents")
    (root / "parent.html").write_text(PARENT_HTML.format(src=IFRAME_SRC), encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(root))
    servers = []
    try:
        for host, port in (("localhost", ALLOWED_PORT), ("127.0.0.1", OTHER_PORT)):
            bind = "127.0.0.1" if host == "localhost" else host
            server = ThreadingHTTPServer((bind, port), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        yield {
            "allowed": f"http://localhost:{ALLOWED_PORT}/parent.html",
            "other": f"http://127.0.0.1:{OTHER_PORT}/parent.html",
        }
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def _new_page(browser, **context_options):
    context = browser.new_context(**context_options)
    return context, context.new_page()


@pytest.fixture
def page(browser):
    context, page = _new_page(browser)
    try:
        yield page
    finally:
        context.close()


@pytest.fixture
def page_without_csp(browser):
    """A page that ignores CSP, so a disallowed origin can still load the widget.

    The real browser never frames the widget for a disallowed origin (frame-ancestors);
    removing the CSP header from the app's responses isolates the second defence:
    app.js ignoring messages from that origin.
    """
    context, page = _new_page(browser)

    def strip_csp(route):
        response = route.fetch()
        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-security-policy", "x-frame-options")
        }
        route.fulfill(response=response, headers=headers)

    context.route(APP_URL + "/**", strip_csp)
    try:
        yield page
    finally:
        context.close()


def _open_parent(page, url):
    page.goto(url)
    frame = page.frame_locator("#widget")
    # Wait until the widget script has loaded its texts (the counter is filled by app.js).
    sync_api.expect(frame.locator("#question-count")).not_to_be_empty(timeout=15000)
    return frame


def _height_messages(page):
    return page.evaluate(
        """() => window.received.filter(m => m.data && m.data.type === "ask-washington:height")"""
    )


def test_allowed_parent_switches_language_and_gets_height(app_server, parent_servers, page):
    frame = _open_parent(page, parent_servers["allowed"])
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(EN["question_label"])

    page.evaluate("window.sendLang('es')")

    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "es", timeout=5000)
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(ES["question_label"])

    page.wait_for_function(
        """() => window.received.some(m => m.data && m.data.type === "ask-washington:height")""",
        timeout=5000,
    )
    heights = _height_messages(page)
    assert heights, "no ask-washington:height message received"
    assert all(m["origin"] == APP_URL for m in heights)
    assert any(
        isinstance(m["data"]["height"], int | float) and m["data"]["height"] > 0 for m in heights
    )


def test_other_parent_cannot_frame_the_widget(app_server, parent_servers, page):
    page.goto(parent_servers["other"])
    page.wait_for_timeout(1500)
    widget = page.frame_locator("#widget")
    # frame-ancestors blocks the document, so the widget's form never appears.
    assert widget.locator("#ask-form").count() == 0
    assert _height_messages(page) == []


def test_other_parent_messages_are_ignored(app_server, parent_servers, page_without_csp):
    page = page_without_csp
    frame = _open_parent(page, parent_servers["other"])

    page.evaluate("window.sendLang('es')")
    page.wait_for_timeout(1500)

    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "en")
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(EN["question_label"])
    assert _height_messages(page) == []
