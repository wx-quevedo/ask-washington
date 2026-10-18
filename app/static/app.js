"use strict";

(function () {
  const LANGS = ["en", "es"];
  const form = document.getElementById("ask-form");
  const input = document.getElementById("question");
  const button = document.getElementById("ask-button");
  const count = document.getElementById("question-count");
  const result = document.getElementById("result");
  const status = document.getElementById("status");
  const answerBlock = document.getElementById("answer-block");
  const answerEl = document.getElementById("answer");
  const sourcesEl = document.getElementById("sources");
  const metaEl = document.getElementById("meta");

  const params = new URLSearchParams(window.location.search);
  const isEmbed = document.body.classList.contains("embed");
  // Origins allowed to embed this page and to talk to it (set by the server).
  const originsMeta = document.querySelector('meta[name="ask-washington-embed-origins"]');
  const allowedOrigins = (originsMeta ? originsMeta.content : "").split(/\s+/).filter(Boolean);

  let lang = LANGS.includes(document.documentElement.lang) ? document.documentElement.lang : "en";
  let t = {};
  let lastAnswer = null;

  function format(template, values) {
    return String(template).replace(/\{(\w+)\}/g, (_, key) => (key in values ? values[key] : ""));
  }

  async function loadTexts(code) {
    const response = await fetch("/static/i18n/" + code + ".json", { cache: "force-cache" });
    if (!response.ok) throw new Error("texts not found");
    return response.json();
  }

  function applyTexts() {
    document.documentElement.lang = t.html_lang || lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.getAttribute("data-i18n");
      if (key in t) node.textContent = t[key];
    });
    document.querySelectorAll("[data-i18n-attr]").forEach((node) => {
      node.getAttribute("data-i18n-attr").split(";").forEach((pair) => {
        const [attr, key] = pair.split(":");
        if (attr && key in t) node.setAttribute(attr, t[key]);
      });
    });
    updateCount();
    if (lastAnswer) renderResult(lastAnswer);
  }

  async function setLanguage(code) {
    if (!LANGS.includes(code)) return;
    try {
      t = await loadTexts(code);
      lang = code;
      applyTexts();
    } catch (e) {
      // Keep the current texts if the other language cannot be loaded.
    }
  }

  function updateCount() {
    count.textContent = format(t.counter || "{n} / 500", { n: input.value.length });
    reportHeight();
  }

  function showStatus(message, kind) {
    status.textContent = message;
    status.className = "status" + (kind ? " " + kind : "");
    status.hidden = false;
    reportHeight();
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Append text to a node, turning **bold**, `code` and [n] markers into elements.
  function appendInline(parent, text, sourceCount) {
    const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[(\d+)\]/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
      if (match[1] !== undefined) {
        parent.appendChild(el("strong", {}, match[1]));
      } else if (match[2] !== undefined) {
        parent.appendChild(el("code", {}, match[2]));
      } else {
        const n = Number(match[3]);
        if (n >= 1 && n <= sourceCount) {
          parent.appendChild(el("a", { class: "cite", href: "#source-" + n, "aria-label": format(t.source_aria, { n: n }) }, "[" + n + "]"));
        } else {
          parent.appendChild(document.createTextNode(match[0]));
        }
      }
      last = pattern.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // Paragraphs and "- " lists only; everything goes through textContent.
  function renderAnswer(text, sourceCount) {
    answerEl.replaceChildren();
    let list = null;
    text.split(/\n/).forEach((rawLine) => {
      const line = rawLine.trim();
      if (!line) {
        list = null;
        return;
      }
      const bullet = line.match(/^[-*]\s+(.*)$/);
      if (bullet) {
        if (!list) {
          list = el("ul");
          answerEl.appendChild(list);
        }
        const item = el("li");
        appendInline(item, bullet[1], sourceCount);
        list.appendChild(item);
      } else {
        list = null;
        const paragraph = el("p");
        appendInline(paragraph, line, sourceCount);
        answerEl.appendChild(paragraph);
      }
    });
  }

  function renderSources(sources) {
    sourcesEl.replaceChildren();
    sources.forEach((source) => {
      const item = el("li", { id: "source-" + source.n });
      if (source.public_url) {
        item.appendChild(el("a", { href: source.public_url, rel: "noopener", target: "_blank" }, source.title));
      } else {
        item.appendChild(document.createTextNode(source.title));
      }
      item.appendChild(el("span", { class: "source-type" }, t["type_" + source.doc_type] || source.doc_type));
      if (source.section) item.appendChild(el("span", { class: "source-section" }, source.section));
      sourcesEl.appendChild(item);
    });
  }

  function renderResult(body) {
    renderAnswer(body.answer, body.sources.length);
    renderSources(body.sources);
    metaEl.textContent = format(t.answered_in, { seconds: (body.latency_ms / 1000).toFixed(1), model: body.model });
    reportHeight();
  }

  function errorMessage(statusCode, body) {
    // The API localizes its messages with the language sent in the request.
    if (body && typeof body.detail === "string" && (statusCode === 429 || statusCode === 502)) return body.detail;
    if (statusCode === 429) return t.error_rate;
    if (statusCode === 422) return t.error_length;
    if (statusCode >= 500) return t.error_server;
    return t.error_generic;
  }

  async function ask(question) {
    button.disabled = true;
    result.setAttribute("aria-busy", "true");
    answerBlock.hidden = true;
    lastAnswer = null;
    showStatus(t.loading, "loading");
    try {
      const response = await fetch("/ask?lang=" + lang, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, lang: lang }),
      });
      let body = null;
      try {
        body = await response.json();
      } catch (e) {
        body = null;
      }
      if (!response.ok) {
        showStatus(errorMessage(response.status, body), "error");
        return;
      }
      status.hidden = true;
      lastAnswer = body;
      answerBlock.hidden = false;
      renderResult(body);
    } catch (e) {
      showStatus(t.error_network, "error");
    } finally {
      button.disabled = false;
      result.setAttribute("aria-busy", "false");
      if (!isEmbed) result.focus();
      reportHeight();
    }
  }

  // ---- embedding: height to the parent, language from the parent ----

  // The parent's origin, when it can be known: from a message it sent, from
  // location.ancestorOrigins (Chromium, Safari) or from the referrer. Posting only to that
  // origin avoids "target origin does not match" console errors for the other allowed ones.
  let parentOrigin = null;
  function parentTargets() {
    if (parentOrigin) return [parentOrigin];
    let origin = null;
    if (window.location.ancestorOrigins && window.location.ancestorOrigins.length) {
      origin = window.location.ancestorOrigins[0];
    } else if (document.referrer) {
      try {
        origin = new URL(document.referrer).origin;
      } catch (e) {
        origin = null;
      }
    }
    if (origin) return allowedOrigins.includes(origin) ? [origin] : [];
    return allowedOrigins; // unknown parent: postMessage drops every non-matching origin
  }

  let lastHeight = 0;
  function reportHeight() {
    if (!isEmbed || window.parent === window || allowedOrigins.length === 0) return;
    const height = Math.ceil(document.documentElement.scrollHeight);
    if (height === lastHeight) return;
    lastHeight = height;
    parentTargets().forEach((origin) => {
      window.parent.postMessage({ type: "ask-washington:height", height: height }, origin);
    });
  }

  window.addEventListener("message", (event) => {
    if (!allowedOrigins.includes(event.origin)) return; // ignore anyone else
    if (event.source === window.parent) parentOrigin = event.origin;
    const data = event.data;
    if (data && data.type === "ask-washington:lang" && LANGS.includes(data.lang)) {
      setLanguage(data.lang);
    }
  });

  if (isEmbed && "ResizeObserver" in window) {
    new ResizeObserver(reportHeight).observe(document.body);
  }

  // ---- events ----

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (question.length < 3 || question.length > 500) {
      showStatus(t.error_length, "error");
      input.focus();
      return;
    }
    ask(question);
  });

  input.addEventListener("input", updateCount);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  document.querySelectorAll(".suggestion").forEach((suggestion) => {
    suggestion.addEventListener("click", () => {
      input.value = suggestion.textContent.trim();
      updateCount();
      form.requestSubmit();
    });
  });

  // The server already rendered the texts; load them for dynamic messages.
  const requested = params.get("lang");
  setLanguage(LANGS.includes(requested) ? requested : lang).then(reportHeight);
})();
