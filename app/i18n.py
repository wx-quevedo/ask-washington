"""Language handling: interface texts, answer language and localized API messages.

Rules:
- Interface language: ?lang=en|es, English by default (the embedding page decides).
- Answer language: the interface language, unless the question is clearly written in the
  other language. Ambiguous questions (a name, an acronym) use the interface language.
"""

import html
import json
import re
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("en", "es")
DEFAULT_LANG = "en"
LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}

I18N_DIR = Path(__file__).resolve().parent / "static" / "i18n"
ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")

# Short, frequent words that are distinctive for each language (no overlap).
_SPANISH_WORDS = {
    "qué",
    "que",
    "cuál",
    "cual",
    "cuáles",
    "cómo",
    "como",
    "dónde",
    "donde",
    "cuándo",
    "cuántos",
    "cuántas",
    "cuanto",
    "quién",
    "es",
    "son",
    "el",
    "la",
    "los",
    "las",
    "del",
    "de",
    "en",
    "con",
    "por",
    "para",
    "una",
    "uno",
    "unos",
    "sus",
    "su",
    "tiene",
    "hizo",
    "ha",
    "hecho",
    "sobre",
    "experiencia",
    "trabajó",
    "trabajo",
    "proyecto",
    "proyectos",
    "artículo",
    "artículos",
    "y",
    "o",
    "también",
    "algún",
    "alguna",
    "realidad",
}
_ENGLISH_WORDS = {
    "what",
    "which",
    "how",
    "where",
    "when",
    "who",
    "does",
    "did",
    "do",
    "is",
    "are",
    "the",
    "of",
    "in",
    "with",
    "for",
    "his",
    "he",
    "has",
    "have",
    "had",
    "about",
    "and",
    "or",
    "any",
    "work",
    "worked",
    "experience",
    "project",
    "projects",
    "paper",
    "papers",
    "built",
    "build",
    "tell",
    "at",
    "on",
}
_WORD_RE = re.compile(r"[a-záéíóúüñ]+", re.I)

API_MESSAGES = {
    "en": {
        "validation": "Please write a question between 3 and 500 characters.",
        "rate_limit": "Too many questions in a short time. Please wait a minute and try again.",
        "budget": (
            "Ask Washington has reached its daily usage budget. Please try again tomorrow, "
            "or see https://www.linkedin.com/in/wxquevedo in the meantime."
        ),
        "unavailable": "The answer service is unavailable. Please try again later.",
    },
    "es": {
        "validation": "Escribe una pregunta de entre 3 y 500 caracteres.",
        "rate_limit": (
            "Demasiadas preguntas en poco tiempo. Espera un minuto y vuelve a intentarlo."
        ),
        "budget": (
            "Ask Washington alcanzó su límite de uso diario. Vuelve a intentarlo mañana o, "
            "mientras tanto, visita https://www.linkedin.com/in/wxquevedo."
        ),
        "unavailable": (
            "El servicio de respuestas no está disponible. Vuelve a intentarlo más tarde."
        ),
    },
}


def normalize_lang(value: str | None) -> str:
    value = (value or "").strip().lower()[:2]
    return value if value in LANGUAGES else DEFAULT_LANG


def detect_language(text: str) -> str | None:
    """Return "en" or "es" when the text is clearly in that language, otherwise None."""
    if "¿" in text or "¡" in text:
        return "es"
    words = [w.lower() for w in _WORD_RE.findall(text)]
    spanish = sum(w in _SPANISH_WORDS for w in words) + sum(
        any(c in w for c in "áéíóúñ") for w in words
    )
    english = sum(w in _ENGLISH_WORDS for w in words)
    if spanish >= 2 and spanish > 2 * english:
        return "es"
    if english >= 2 and english > 2 * spanish:
        return "en"
    return None


def answer_language(question: str, interface_lang: str) -> str:
    return detect_language(question) or normalize_lang(interface_lang)


def api_message(key: str, lang: str) -> str:
    return API_MESSAGES[normalize_lang(lang)][key]


def parse_origins(raw: str) -> list[str]:
    """Allowed embedding origins from a comma-separated list; invalid entries are dropped."""
    origins = []
    for item in (raw or "").split(","):
        item = item.strip().rstrip("/")
        if item and ORIGIN_RE.match(item) and item not in origins:
            origins.append(item)
    return origins


@lru_cache
def texts(lang: str) -> dict[str, str]:
    return json.loads((I18N_DIR / f"{normalize_lang(lang)}.json").read_text(encoding="utf-8"))


@lru_cache
def _template() -> str:
    return (I18N_DIR.parent / "index.html").read_text(encoding="utf-8")


def render_page(lang: str, embed: bool, origins: list[str]) -> str:
    """Fill the page template with the texts of one language (escaped for HTML)."""
    lang = normalize_lang(lang)
    values = texts(lang)

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key == "embed_class":
            return "embed" if embed else ""
        if key == "embed_origins":
            return html.escape(" ".join(origins), quote=True)
        return html.escape(values[key], quote=True)

    return re.sub(r"\{\{\s*([a-z0-9_]+)\s*\}\}", replace, _template())
