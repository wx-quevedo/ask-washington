"""End-to-end check of the embed protocol in a real browser.

The app runs with the portfolio's origins in EMBED_ALLOWED_ORIGINS. A minimal parent page
is served at http://localhost:4321 (the portfolio's dev origin) and must be able to show
the widget and switch its language; other origins must not.

Needs Playwright, which is not a project dependency. Run it ad hoc with:

    uv run --with playwright python -m playwright install chromium   # once
    uv run --with playwright pytest tests/e2e -q

Without Playwright the whole module is skipped. The parent page binds 127.0.0.1:4321 and
Chromium maps "localhost" to 127.0.0.1, so a dev server already listening on [::1]:4321
(for example `astro preview`) is not disturbed.
"""

import json
import os
import socket
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
IFRAME_SRC = f"{APP_URL}/?embed=1&lang=en"

PORTFOLIO_ORIGINS = (
    "https://washingtonquevedo.com",
    "https://www.washingtonquevedo.com",
    "http://localhost:4321",
)
DEV_PORT = 4321  # allowed: http://localhost:4321
SAME_HOST_OTHER_PORT = 8102  # not allowed: http://localhost:8102
OTHER_HOST_PORT = 8103  # not allowed: http://127.0.0.1:8103

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


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(scope="module")
def app_server():
    env = dict(
        os.environ,
        EMBED_ALLOWED_ORIGINS=",".join(PORTFOLIO_ORIGINS),
        PYTHONUNBUFFERED="1",
    )
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
    ports = (DEV_PORT, SAME_HOST_OTHER_PORT, OTHER_HOST_PORT)
    busy = [p for p in ports if not _port_free(p)]
    if busy:
        pytest.skip(f"127.0.0.1 ports already in use: {busy}")
    # The parent page lives in a temporary directory, outside the repository.
    root = tmp_path_factory.mktemp("parents")
    (root / "parent.html").write_text(PARENT_HTML.format(src=IFRAME_SRC), encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(root))
    servers = []
    try:
        for port in ports:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        yield {
            "dev": f"http://localhost:{DEV_PORT}/parent.html",
            "same_host_other_port": f"http://localhost:{SAME_HOST_OTHER_PORT}/parent.html",
            "other_host": f"http://127.0.0.1:{OTHER_HOST_PORT}/parent.html",
        }
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        # "localhost" -> 127.0.0.1, so http://localhost:4321 reaches the test page.
        browser = pw.chromium.launch(args=["--host-resolver-rules=MAP localhost 127.0.0.1"])
        try:
            yield browser
        finally:
            browser.close()


def _new_page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.console_errors = []
    page.on("console", lambda msg: msg.type == "error" and page.console_errors.append(msg.text))
    return context, page


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


def test_widget_lists_the_portfolio_origins(app_server):
    with urllib.request.urlopen(IFRAME_SRC, timeout=5) as response:
        csp = response.headers["Content-Security-Policy"]
        html = response.read().decode("utf-8")
    assert csp.endswith("frame-ancestors 'self' " + " ".join(PORTFOLIO_ORIGINS))
    assert response.headers.get("X-Frame-Options") is None
    assert f'content="{" ".join(PORTFOLIO_ORIGINS)}"' in html


def test_dev_origin_shows_widget_and_switches_language(app_server, parent_servers, page):
    frame = _open_parent(page, parent_servers["dev"])
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(EN["question_label"])
    sync_api.expect(frame.locator(".embed-disclaimer")).to_have_text(EN["disclaimer"])

    page.evaluate("window.sendLang('es')")
    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "es", timeout=5000)
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(ES["question_label"])
    sync_api.expect(frame.locator(".embed-disclaimer")).to_have_text(ES["disclaimer"])

    page.evaluate("window.sendLang('en')")
    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "en", timeout=5000)

    page.wait_for_function(
        """() => window.received.some(m => m.data && m.data.type === "ask-washington:height")""",
        timeout=5000,
    )
    heights = _height_messages(page)
    assert all(m["origin"] == APP_URL for m in heights)
    assert any(m["data"]["height"] > 0 for m in heights)
    # The height goes only to the real parent origin: no "target origin does not match"
    # errors for the other allowed origins.
    assert page.console_errors == []


@pytest.mark.parametrize("parent", ["same_host_other_port", "other_host"])
def test_other_origins_cannot_frame_the_widget(app_server, parent_servers, page, parent):
    page.goto(parent_servers[parent])
    page.wait_for_timeout(1500)
    widget = page.frame_locator("#widget")
    # frame-ancestors blocks the document, so the widget's form never appears.
    assert widget.locator("#ask-form").count() == 0
    assert _height_messages(page) == []


@pytest.mark.parametrize("parent", ["same_host_other_port", "other_host"])
def test_other_origins_messages_are_ignored(app_server, parent_servers, page_without_csp, parent):
    page = page_without_csp
    frame = _open_parent(page, parent_servers[parent])

    page.evaluate("window.sendLang('es')")
    page.wait_for_timeout(1500)

    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "en")
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(EN["question_label"])
    assert _height_messages(page) == []
