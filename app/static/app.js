"use strict";

(function () {
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

  const TYPE_LABELS = {
    cv: "CV",
    linkedin: "LinkedIn",
    repo_readme: "README",
    paper: "Paper",
    profile: "Scholar profile",
  };

  function updateCount() {
    count.textContent = input.value.length + " / 500";
  }

  function showStatus(message, kind) {
    status.textContent = message;
    status.className = "status" + (kind ? " " + kind : "");
    status.hidden = false;
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
          parent.appendChild(el("a", { class: "cite", href: "#source-" + n, "aria-label": "Source " + n }, "[" + n + "]"));
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
      item.appendChild(el("span", { class: "source-type" }, TYPE_LABELS[source.doc_type] || source.doc_type));
      if (source.section) item.appendChild(el("span", { class: "source-section" }, source.section));
      sourcesEl.appendChild(item);
    });
  }

  function errorMessage(statusCode, body) {
    if (statusCode === 429) {
      if (body && typeof body.detail === "string") return body.detail;
      return "Too many questions in a short time. Please wait a minute and try again.";
    }
    if (statusCode === 422) return "Please write a question between 3 and 500 characters.";
    if (statusCode >= 500) return "The answer service is not available right now. Please try again later.";
    return "Something went wrong. Please try again.";
  }

  async function ask(question) {
    button.disabled = true;
    result.setAttribute("aria-busy", "true");
    answerBlock.hidden = true;
    showStatus("Looking through the sources...", "loading");
    try {
      const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question }),
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
      renderAnswer(body.answer, body.sources.length);
      renderSources(body.sources);
      metaEl.textContent = "Answered in " + (body.latency_ms / 1000).toFixed(1) + " s by " + body.model + ".";
      answerBlock.hidden = false;
    } catch (e) {
      showStatus("Could not reach the server. Check your connection and try again.", "error");
    } finally {
      button.disabled = false;
      result.setAttribute("aria-busy", "false");
      result.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (question.length < 3 || question.length > 500) {
      showStatus("Please write a question between 3 and 500 characters.", "error");
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

  updateCount();
})();
