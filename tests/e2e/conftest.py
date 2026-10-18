"""Shared fixtures for the browser tests (Playwright, ad hoc: see the test modules).

- app_server: the app on 127.0.0.1:8101 with the portfolio's EMBED_ALLOWED_ORIGINS.
- parent_servers: minimal parent pages (in a temp dir, outside the repository) on
  http://localhost:4321 (allowed), http://localhost:8102 and http://127.0.0.1:8103 (not).
- browser: Chromium with "localhost" mapped to 127.0.0.1, so a dev server already on
  [::1]:4321 (for example `astro preview`) is not disturbed.
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

# The portfolio gives the widget a fixed-size panel (about 400 px wide).
PARENT_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Parent</title>
<style>body {{ margin: 0; }} iframe {{ border: 0; display: block; }}</style></head>
<body>
  <iframe id="widget" src="{src}" width="400" height="600" title="Ask Washington"></iframe>
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


@pytest.fixture(scope="session")
def app_server():
    if not _port_free(APP_PORT):
        pytest.skip(f"127.0.0.1:{APP_PORT} already in use")
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


@pytest.fixture(scope="session")
def parent_servers(tmp_path_factory):
    ports = (DEV_PORT, SAME_HOST_OTHER_PORT, OTHER_HOST_PORT)
    busy = [p for p in ports if not _port_free(p)]
    if busy:
        pytest.skip(f"127.0.0.1 ports already in use: {busy}")
    root = tmp_path_factory.mktemp("parents")
    for lang in ("en", "es"):
        src = f"{APP_URL}/?embed=1&lang={lang}"
        (root / f"parent-{lang}.html").write_text(PARENT_HTML.format(src=src), encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(root))
    servers = []
    try:
        for port in ports:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        yield {
            "dev": f"http://localhost:{DEV_PORT}/parent-en.html",
            "dev_es": f"http://localhost:{DEV_PORT}/parent-es.html",
            "same_host_other_port": f"http://localhost:{SAME_HOST_OTHER_PORT}/parent-en.html",
            "other_host": f"http://127.0.0.1:{OTHER_HOST_PORT}/parent-en.html",
        }
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--host-resolver-rules=MAP localhost 127.0.0.1"])
        try:
            yield browser
        finally:
            browser.close()


def new_page(browser, **context_options):
    """A page that collects console errors in page.console_errors."""
    context = browser.new_context(**context_options)
    page = context.new_page()
    page.console_errors = []
    page.on("console", lambda msg: msg.type == "error" and page.console_errors.append(msg.text))
    page.on("pageerror", lambda exc: page.console_errors.append(str(exc)))
    return context, page


@pytest.fixture
def page(browser):
    context, page = new_page(browser)
    try:
        yield page
    finally:
        context.close()


def wait_ready(locator_root):
    """Wait until app.js has loaded its texts (it sets <html data-ready="1">)."""
    sync_api.expect(locator_root.locator("html")).to_have_attribute(
        "data-ready", "1", timeout=15000
    )
