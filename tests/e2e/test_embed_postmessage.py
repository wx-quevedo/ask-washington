"""End-to-end check of the embed protocol in a real browser.

The app runs with the portfolio's origins in EMBED_ALLOWED_ORIGINS. A minimal parent page
at http://localhost:4321 (the portfolio's dev origin) must be able to show the widget and
switch its language; other origins must not.

Needs Playwright, which is not a project dependency. Run it ad hoc with:

    uv run --with playwright python -m playwright install chromium   # once
    uv run --with playwright pytest tests/e2e -q

Without Playwright the whole directory is skipped (see conftest.py).
"""

import urllib.request

import pytest

from tests.e2e.conftest import APP_URL, EN, ES, PORTFOLIO_ORIGINS, new_page, sync_api, wait_ready


@pytest.fixture
def page_without_csp(browser):
    """A page that ignores CSP, so a disallowed origin can still load the widget.

    The real browser never frames the widget for a disallowed origin (frame-ancestors);
    removing the CSP header from the app's responses isolates the second defence:
    app.js ignoring messages from that origin.
    """
    context, page = new_page(browser)

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
    wait_ready(frame)
    return frame


def _height_messages(page):
    return page.evaluate(
        """() => window.received.filter(m => m.data && m.data.type === "ask-washington:height")"""
    )


def test_widget_lists_the_portfolio_origins(app_server):
    with urllib.request.urlopen(f"{APP_URL}/?embed=1&lang=en", timeout=5) as response:
        csp = response.headers["Content-Security-Policy"]
        html = response.read().decode("utf-8")
    assert csp.endswith("frame-ancestors 'self' " + " ".join(PORTFOLIO_ORIGINS))
    assert response.headers.get("X-Frame-Options") is None
    assert f'content="{" ".join(PORTFOLIO_ORIGINS)}"' in html


def test_dev_origin_shows_widget_and_switches_language(app_server, parent_servers, page):
    frame = _open_parent(page, parent_servers["dev"])
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(EN["question_label"])
    sync_api.expect(frame.locator(".disclaimer")).to_have_text(EN["disclaimer"])

    page.evaluate("window.sendLang('es')")
    sync_api.expect(frame.locator("html")).to_have_attribute("lang", "es", timeout=5000)
    sync_api.expect(frame.locator("label[for=question]")).to_have_text(ES["question_label"])
    sync_api.expect(frame.locator(".disclaimer")).to_have_text(ES["disclaimer"])
    sync_api.expect(frame.locator(".chip").first).to_have_text(ES["suggestion_1"])

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
