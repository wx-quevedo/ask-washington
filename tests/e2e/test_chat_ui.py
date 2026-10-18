"""Browser tests of the chat interface, full page and widget.

POST /ask is answered by Playwright (route.fulfill), so these tests never call the LLM.
Run ad hoc: uv run --with playwright pytest tests/e2e -q
"""

import json

from tests.e2e.conftest import APP_URL, EN, ES, new_page, sync_api, wait_ready

ANSWER = {
    "answer": (
        "Washington builds VR training simulators in Unity [1].\n"
        "- He also ships ML inference services with `ONNX Runtime` [2].\n"
        "- He founded **Inmersoft** in 2018 [1][2]."
    ),
    "lang": "en",
    "sources": [
        {
            "n": 1,
            "title": "CV - XR + AI Engineer",
            "doc_type": "cv",
            "section": "Summary",
            "public_url": "https://www.linkedin.com/in/wxquevedo",
            "score": 0.61,
        },
        {
            "n": 2,
            "title": "GitHub repository plan-vivo-kit",
            "doc_type": "repo_readme",
            "section": "Overview",
            "public_url": "https://github.com/wx-quevedo/plan-vivo-kit",
            "score": 0.55,
        },
    ],
    "provider": "anthropic",
    "model": "claude-haiku-5-5",
    "latency_ms": 900,
    "usage": {"input_tokens": 1000, "output_tokens": 100},
}


class AskMock:
    """Answers POST /ask from the browser.

    With hold=True the request stays pending (typing indicator visible) until release().
    Handlers run on Playwright's thread, so holding means keeping the route, not blocking.
    """

    def __init__(self, page, status=200, body=None, hold=False):
        self.requests = []
        self.status = status
        self.body = body or ANSWER
        self.hold = hold
        self.pending = []
        page.context.route("**/ask?*", self._handle)

    def _fulfill(self, route):
        route.fulfill(
            status=self.status, content_type="application/json", body=json.dumps(self.body)
        )

    def _handle(self, route):
        self.requests.append(json.loads(route.request.post_data or "{}"))
        if self.hold:
            self.pending.append(route)
        else:
            self._fulfill(route)

    def release(self):
        self.hold = False
        while self.pending:
            self._fulfill(self.pending.pop(0))


def open_page(page, lang="en", viewport=None):
    if viewport:
        page.set_viewport_size(viewport)
    page.goto(f"{APP_URL}/?lang={lang}")
    wait_ready(page)
    return page


def test_initial_state(app_server, page):
    open_page(page)
    sync_api.expect(page.locator(".msg.assistant .bubble")).to_have_text(EN["greeting"])
    chips = page.locator(".chip")
    sync_api.expect(chips).to_have_count(4)
    for i in range(4):
        sync_api.expect(chips.nth(i)).to_have_text(EN[f"suggestion_{i + 1}"])
    sync_api.expect(page.locator("#send")).to_have_attribute("aria-label", EN["send_label"])
    sync_api.expect(page.locator(".disclaimer")).to_have_text(EN["disclaimer"])
    sync_api.expect(page.locator("#thread")).to_have_attribute("role", "log")
    sync_api.expect(page.locator("#question-count")).to_be_hidden()
    assert page.console_errors == []


def test_chip_sends_question_and_renders_answer_with_sources(app_server, page):
    mock = AskMock(page, hold=True)
    open_page(page)

    page.locator(".chip").first.click()

    user = page.locator(".msg.user .bubble")
    sync_api.expect(user).to_have_text(EN["suggestion_1"])
    # Typing indicator while the answer is pending, with text for screen readers.
    typing = page.locator(".msg.typing")
    sync_api.expect(typing).to_be_visible()
    sync_api.expect(typing.locator(".sr-only")).to_have_text(EN["typing"])
    sync_api.expect(page.locator(".chip")).to_have_count(0)  # chips go after the first question
    sync_api.expect(page.locator("#send")).to_be_disabled()

    mock.release()
    answer = page.locator(".msg.assistant").last
    sync_api.expect(typing).to_have_count(0)
    sync_api.expect(answer.locator(".bubble li")).to_have_count(2)
    cites = answer.locator("a.cite")
    sync_api.expect(cites).to_have_count(4)
    # Only the adjacent pair [1][2] gets a separator, not citations with text between them.
    sync_api.expect(answer.locator(".cite-sep")).to_have_count(1)
    sync_api.expect(cites.first).to_have_attribute("href", "#m1-source-1")
    sync_api.expect(answer.locator(".bubble code")).to_have_text("ONNX Runtime")
    sources = answer.locator(".sources li")
    sync_api.expect(sources).to_have_count(2)
    sync_api.expect(sources.first.locator("a")).to_have_attribute(
        "href", "https://www.linkedin.com/in/wxquevedo"
    )
    sync_api.expect(answer.locator(".sources-title")).to_have_text(EN["sources_label"])
    sync_api.expect(page.locator("#send")).to_be_enabled()

    assert mock.requests == [{"question": EN["suggestion_1"], "lang": "en"}]

    # User bubble on the right, assistant bubble on the left.
    thread = page.locator(".thread-inner").bounding_box()  # the centered content column
    user_box = user.bounding_box()
    answer_box = answer.locator(".bubble").bounding_box()
    assert user_box["x"] + user_box["width"] > thread["x"] + thread["width"] * 0.8
    assert answer_box["x"] < thread["x"] + thread["width"] * 0.2
    assert page.console_errors == []


def test_enter_sends_and_shift_enter_adds_a_line(app_server, page):
    mock = AskMock(page)
    open_page(page)
    box = page.locator("#question")

    box.click()
    box.type("What did he build")
    box.press("Shift+Enter")
    box.type("at Stanford?")
    assert box.input_value() == "What did he build\nat Stanford?"
    assert mock.requests == []

    box.press("Enter")
    sync_api.expect(page.locator(".msg.user .bubble")).to_have_text(
        "What did he build\nat Stanford?"
    )
    sync_api.expect(box).to_have_value("")
    sync_api.expect(page.locator(".msg.assistant .sources")).to_have_count(1)
    assert mock.requests[0]["question"] == "What did he build\nat Stanford?"

    # A second question keeps the thread and gives its sources their own anchors.
    box.type("And his papers?")
    box.press("Enter")
    sync_api.expect(page.locator(".msg.user")).to_have_count(2)
    sync_api.expect(page.locator(".msg.assistant .sources")).to_have_count(2)
    sync_api.expect(page.locator("#m2-source-1")).to_have_count(1)
    assert page.console_errors == []


def test_composer_grows_to_four_lines_and_counter_near_limit(app_server, page):
    open_page(page)
    box = page.locator("#question")
    one_line = box.bounding_box()["height"]

    box.fill("line\n" * 2)
    box.dispatch_event("input")
    assert box.bounding_box()["height"] > one_line

    box.fill("line\n" * 12)
    box.dispatch_event("input")
    grown = box.bounding_box()["height"]
    assert grown <= one_line * 4 + 20  # capped near four lines, then it scrolls
    assert box.evaluate("el => getComputedStyle(el).overflowY") == "auto"

    box.fill("x" * 100)
    box.dispatch_event("input")
    sync_api.expect(page.locator("#question-count")).to_be_hidden()
    box.fill("x" * 450)
    box.dispatch_event("input")
    sync_api.expect(page.locator("#question-count")).to_have_text("450 / 500")


def test_short_question_and_api_errors_show_as_assistant_bubbles(app_server, page):
    AskMock(page, status=429, body={"detail": "Demasiadas preguntas. Espera un minuto."})
    open_page(page, lang="es")
    box = page.locator("#question")

    box.fill("hi")
    box.press("Enter")
    error = page.locator(".msg.assistant.error .bubble")
    sync_api.expect(error).to_have_text(ES["error_length"])

    box.fill("¿Qué es plan-vivo-kit?")
    box.press("Enter")
    sync_api.expect(error.last).to_have_text("Demasiadas preguntas. Espera un minuto.")


def test_mobile_width_has_no_horizontal_scroll(app_server, browser):
    context, page = new_page(browser, viewport={"width": 360, "height": 740}, is_mobile=True)
    try:
        AskMock(page)
        open_page(page)
        page.locator(".chip").nth(2).click()
        sync_api.expect(page.locator(".msg.assistant .sources")).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        composer = page.locator(".composer").bounding_box()
        assert abs(composer["y"] + composer["height"] - 740) <= 1  # pinned to the bottom
        assert page.console_errors == []
    finally:
        context.close()


def test_widget_in_portfolio_panel_fills_height_and_scrolls_only_the_thread(
    app_server, parent_servers, page
):
    mock = AskMock(page, body={**ANSWER, "lang": "es"})
    page.goto(parent_servers["dev_es"])
    frame = page.frame_locator("#widget")
    wait_ready(frame)

    sync_api.expect(frame.locator(".subtitle")).to_be_hidden()
    sync_api.expect(frame.locator(".profiles")).to_be_hidden()
    sync_api.expect(frame.locator(".chip").first).to_have_text(ES["suggestion_1"])

    box = frame.locator("#question")
    for i in range(4):
        box.fill(f"¿Pregunta número {i + 1} sobre su experiencia?")
        box.press("Enter")
        sync_api.expect(frame.locator(".msg.assistant .sources")).to_have_count(i + 1)

    assert all(r["lang"] == "es" for r in mock.requests)
    # Smooth scrolling: wait until the thread has reached the last message.
    frame.locator("#thread").evaluate(
        """t => new Promise(resolve => {
            const check = () => (t.scrollHeight - t.scrollTop - t.clientHeight <= 4)
                ? resolve() : requestAnimationFrame(check);
            check();
        })"""
    )
    sizes = frame.locator("body").evaluate(
        """() => {
            const t = document.getElementById("thread");
            const c = document.querySelector(".composer").getBoundingClientRect();
            return {
                docScroll: document.documentElement.scrollHeight,
                viewport: window.innerHeight,
                threadScroll: t.scrollHeight, threadClient: t.clientHeight,
                atEnd: t.scrollHeight - t.scrollTop - t.clientHeight,
                composerBottom: c.bottom,
            };
        }"""
    )
    assert sizes["docScroll"] <= sizes["viewport"]  # the page itself does not scroll
    assert sizes["threadScroll"] > sizes["threadClient"]  # the thread does
    assert sizes["atEnd"] <= 4  # scrolled to the last message
    assert abs(sizes["composerBottom"] - sizes["viewport"]) <= 1  # composer pinned at the bottom
    assert page.console_errors == []


def test_long_answer_is_shown_from_its_start(app_server, page):
    long_text = "\n".join(f"- Point {i} about his work [1]." for i in range(40))
    AskMock(page, body={**ANSWER, "answer": long_text})
    open_page(page, viewport={"width": 1280, "height": 700})
    page.locator(".chip").first.click()
    answer = page.locator(".msg.assistant").last
    sync_api.expect(answer.locator(".sources li")).to_have_count(2)
    page.locator("#thread").evaluate(
        """t => new Promise(r => { let last = -1, same = 0; const c = () => {
            same = t.scrollTop === last ? same + 1 : 0; last = t.scrollTop;
            same > 10 ? r() : requestAnimationFrame(c); }; c(); })"""
    )
    thread_top = page.locator("#thread").bounding_box()["y"]
    answer_top = answer.bounding_box()["y"]
    assert abs(answer_top - thread_top) <= 16  # the answer starts at the top of the thread
    sync_api.expect(page.locator(".cite").nth(1)).to_be_visible()
    assert page.console_errors == []
