"use strict";

(function () {
  const LANGS = ["en", "es"];
  const MAX_CHARS = 500;
  const COUNTER_FROM = 400; // show the counter only when getting close to the limit

  const form = document.getElementById("ask-form");
  const input = document.getElementById("question");
  const sendButton = document.getElementById("send");
  const count = document.getElementById("question-count");
  const thread = document.getElementById("thread");
  const messages = document.getElementById("messages");
  const chips = document.getElementById("chips");

  const params = new URLSearchParams(window.location.search);
  const isEmbed = document.body.classList.contains("embed");
  // Origins allowed to embed this page and to talk to it (set by the server).
  const originsMeta = document.querySelector('meta[name="ask-washington-embed-origins"]');
  const allowedOrigins = (originsMeta ? originsMeta.content : "").split(/\s+/).filter(Boolean);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let lang = LANGS.includes(document.documentElement.lang) ? document.documentElement.lang : "en";
  let t = {};
  let busy = false;
  let messageCount = 0; // gives each answer's source anchors a unique id

  function format(template, values) {
    return String(template).replace(/\{(\w+)\}/g, (_, key) => (key in values ? values[key] : ""));
  }

  async function loadTexts(code) {
    const response = await fetch("/static/i18n/" + code + ".json", { cache: "force-cache" });
    if (!response.ok) throw new Error("texts not found");
    return response.json();
  }

  // Every node with data-i18n (static texts, labels of rendered answers) follows the language.
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

  // ---- composer ----

  function updateCount() {
    const n = input.value.length;
    if (n >= COUNTER_FROM) {
      count.textContent = format(t.counter || "{n} / 500", { n: n });
      count.classList.toggle("near-limit", n >= MAX_CHARS);
      count.hidden = false;
    } else {
      count.hidden = true;
    }
  }

  // Grow with the text up to four lines (CSS max-height), then scroll inside.
  function autoGrow() {
    input.style.height = "auto";
    const max = parseFloat(getComputedStyle(input).maxHeight) || Infinity;
    input.style.height = Math.min(input.scrollHeight, max) + "px";
    input.style.overflowY = input.scrollHeight > max ? "auto" : "hidden";
  }

  // ---- thread ----

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function scrollToEnd() {
    thread.scrollTo({ top: thread.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
  }

  // A new answer taller than the thread is shown from its start, so it reads top-down;
  // shorter answers simply scroll the thread to the end.
  function scrollToAnswer(msg) {
    if (msg.offsetHeight > thread.clientHeight) {
      thread.scrollTo({ top: msg.offsetTop - 8, behavior: reduceMotion ? "auto" : "smooth" });
    } else {
      scrollToEnd();
    }
  }

  function addMessage(role, extraClass) {
    const msg = el("div", { class: "msg " + role + (extraClass ? " " + extraClass : "") });
    // Screen readers hear who speaks; the visual layout shows it by side and colour.
    msg.appendChild(el("p", { class: "sr-only", "data-i18n": role === "user" ? "you_label" : "assistant_label" }, role === "user" ? t.you_label : t.assistant_label));
    const bubble = el("div", { class: "bubble" });
    msg.appendChild(bubble);
    messages.appendChild(msg);
    scrollToEnd();
    return { msg: msg, bubble: bubble };
  }

  // Append text to a node, turning **bold**, `code` and [n] markers into elements.
  function appendInline(parent, text, sourceCount, prefix) {
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
          // Citations right next to each other ([4][5]) get a visual separator.
          const previous = parent.lastChild;
          if (match.index === last && previous && previous.classList && previous.classList.contains("cite")) {
            parent.appendChild(el("span", { class: "cite-sep", "aria-hidden": "true" }, ","));
          }
          parent.appendChild(el("a", { class: "cite", href: "#" + prefix + n, "aria-label": format(t.source_aria, { n: n }) }, String(n)));
        } else {
          parent.appendChild(document.createTextNode(match[0]));
        }
      }
      last = pattern.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // Paragraphs and "- " lists only; everything goes through textContent.
  function renderMarkdown(bubble, text, sourceCount, prefix) {
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
          bubble.appendChild(list);
        }
        const item = el("li");
        appendInline(item, bullet[1], sourceCount, prefix);
        list.appendChild(item);
      } else {
        list = null;
        const paragraph = el("p");
        appendInline(paragraph, line, sourceCount, prefix);
        bubble.appendChild(paragraph);
      }
    });
  }

  function renderSources(msg, sources, prefix) {
    if (!sources.length) return;
    msg.appendChild(el("p", { class: "sources-title", "data-i18n": "sources_label" }, t.sources_label));
    const list = el("ol", { class: "sources" });
    sources.forEach((source) => {
      const item = el("li", { id: prefix + source.n });
      item.appendChild(el("span", { class: "num" }, source.n + "."));
      if (source.public_url) {
        item.appendChild(el("a", { href: source.public_url, rel: "noopener", target: "_blank" }, source.title));
      } else {
        item.appendChild(document.createTextNode(source.title));
      }
      item.appendChild(document.createTextNode(" · "));
      item.appendChild(el("span", { "data-i18n": "type_" + source.doc_type }, t["type_" + source.doc_type] || source.doc_type));
      list.appendChild(item);
    });
    msg.appendChild(list);
  }

  function showTyping() {
    const msg = el("div", { class: "msg assistant typing" });
    msg.appendChild(el("p", { class: "sr-only", "data-i18n": "typing" }, t.typing));
    const bubble = el("div", { class: "bubble", "aria-hidden": "true" });
    for (let i = 0; i < 3; i++) bubble.appendChild(el("span", { class: "dot" }));
    msg.appendChild(bubble);
    messages.appendChild(msg);
    scrollToEnd();
    return msg;
  }

  function showError(key, detail) {
    const { bubble } = addMessage("assistant", "error");
    bubble.appendChild(el("p", {}, detail || t[key]));
  }

  function errorFor(statusCode, body) {
    // The API localizes 429 and 502 with the language sent in the request.
    if (body && typeof body.detail === "string" && (statusCode === 429 || statusCode === 502)) return [null, body.detail];
    if (statusCode === 429) return ["error_rate", null];
    if (statusCode === 422) return ["error_length", null];
    if (statusCode >= 500) return ["error_server", null];
    return ["error_generic", null];
  }

  async function ask(question) {
    busy = true;
    sendButton.disabled = true;
    if (chips) chips.remove();

    const { bubble } = addMessage("user");
    bubble.textContent = question;
    const typing = showTyping();
    reportHeight();

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
      typing.remove();
      if (!response.ok) {
        const [key, detail] = errorFor(response.status, body);
        showError(key, detail);
        return;
      }
      messageCount += 1;
      const prefix = "m" + messageCount + "-source-";
      const answer = addMessage("assistant");
      renderMarkdown(answer.bubble, body.answer, body.sources.length, prefix);
      renderSources(answer.msg, body.sources, prefix);
      scrollToAnswer(answer.msg);
    } catch (e) {
      typing.remove();
      showError("error_network");
    } finally {
      busy = false;
      sendButton.disabled = false;
      reportHeight();
    }
  }

  function submitQuestion(text) {
    const question = text.trim();
    if (busy) return;
    if (question.length < 3 || question.length > MAX_CHARS) {
      showError("error_length");
      input.focus();
      return;
    }
    input.value = "";
    autoGrow();
    updateCount();
    ask(question);
  }

  // ---- embedding: language from the parent, optional height report ----

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

  // The widget fills the iframe (the panel gives it a fixed height), so this only reports
  // the current size; kept for parents that listen to it.
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

  // ---- events ----

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitQuestion(input.value);
  });

  input.addEventListener("input", () => {
    autoGrow();
    updateCount();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitQuestion(input.value);
    }
  });

  if (chips) {
    chips.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        submitQuestion(chip.textContent);
        input.focus();
      });
    });
  }

  // The server already rendered the texts; load them for dynamic messages.
  const requested = params.get("lang");
  setLanguage(LANGS.includes(requested) ? requested : lang).then(() => {
    autoGrow();
    reportHeight();
    document.documentElement.dataset.ready = "1"; // texts loaded (used by the browser tests)
  });
})();
