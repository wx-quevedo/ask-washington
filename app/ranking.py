"""Deterministic answers for ranking and count questions about the papers.

Similarity search cannot answer "most cited" or "how many", so these questions are
computed from data/papers.yaml and the Google Scholar profile totals. The LLM only
writes the answer from the facts produced here.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.ingestion import PAPERS_FILE

SNAPSHOT_DATE = "2026-10-17"
PROFILE_TOTALS = {
    "citations": 640,
    "h_index": 14,
    "i10_index": 21,
    "entries": 40,
}

INTENT_PATTERNS = {
    "most_cited": re.compile(
        r"\b(most|highest|top|best)[- ]cited\b|\bm[aá]s citad|\bmayor(es)? (n[uú]mero de )?citas",
        re.I,
    ),
    "latest": re.compile(
        r"\b(latest|newest|most recent|last)\b.*\b(paper|publication|article)s?\b"
        r"|\b(paper|publication|article)s?\b.*\b(latest|newest|most recent)\b"
        r"|\b[uú]ltim[oa]s?\b.*\b(paper|art[ií]culo|publicaci[oó]n)"
        r"|\b(paper|art[ií]culo|publicaci[oó]n)\w*\b.*\bm[aá]s recientes?\b",
        re.I,
    ),
    "count": re.compile(
        r"\bhow many\b.*\b(papers|publications|articles)\b"
        r"|\bnumber of (papers|publications|articles)\b"
        r"|\bcu[aá]nt[oa]s\b.*\b(papers|art[ií]culos|publicaciones)\b",
        re.I,
    ),
    "metrics": re.compile(
        r"\bh[- ]?index\b|\bi10\b|[ií]ndice h\b|\btotal citations\b|\bcitations? in total\b"
        r"|\bhow many citations\b|\bcu[aá]ntas citas\b|\bcitas totales\b",
        re.I,
    ),
}


@dataclass
class RankingResult:
    intents: list[str]
    facts: list[str] = field(default_factory=list)
    # Each source: title, doc_type, section, public_url, doc_id
    sources: list[dict] = field(default_factory=list)


def detect_intents(question: str) -> list[str]:
    return [name for name, pattern in INTENT_PATTERNS.items() if pattern.search(question)]


@lru_cache
def load_papers(path: Path = PAPERS_FILE) -> tuple[list[dict], str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["papers"], data.get("profile_url", "")


def _paper_source(paper: dict, section: str) -> dict:
    doi = paper.get("doi") or ""
    return {
        "doc_id": f"paper-{paper['id']}",
        "title": paper["title"],
        "doc_type": "paper",
        "section": section,
        "public_url": paper.get("url") or (f"https://doi.org/{doi}" if doi else ""),
    }


def answer_ranking(question: str) -> RankingResult | None:
    """Return facts and sources for a ranking question, or None if it is not one."""
    intents = detect_intents(question)
    if not intents:
        return None
    papers, profile_url = load_papers()
    result = RankingResult(intents=intents)

    def cite(paper: dict, section: str) -> int:
        source = _paper_source(paper, section)
        for i, existing in enumerate(result.sources, start=1):
            if existing["doc_id"] == source["doc_id"]:
                return i
        result.sources.append(source)
        return len(result.sources)

    def cite_profile() -> int:
        for i, existing in enumerate(result.sources, start=1):
            if existing["doc_id"] == "scholar-profile":
                return i
        result.sources.append(
            {
                "doc_id": "scholar-profile",
                "title": f"Google Scholar profile (snapshot {SNAPSHOT_DATE})",
                "doc_type": "profile",
                "section": "Profile totals",
                "public_url": profile_url,
            }
        )
        return len(result.sources)

    if "most_cited" in intents:
        ranked = sorted(papers, key=lambda p: (-p.get("citations", 0), p["year"]))
        lines = []
        for rank, paper in enumerate(ranked[:3], start=1):
            n = cite(paper, "Citations ranking")
            venue = paper.get("venue") or "venue unknown"
            lines.append(
                f"{rank}. {paper['title']} ({paper['year']}, {venue})"
                f" - {paper.get('citations', 0)} citations [{n}]"
            )
        result.facts.append(
            f"Most cited papers (Google Scholar citation counts, snapshot {SNAPSHOT_DATE}):\n"
            + "\n".join(lines)
        )

    if "latest" in intents:
        newest_year = max(p["year"] for p in papers)
        recent = sorted(papers, key=lambda p: (-p["year"], -p.get("citations", 0)))[:3]
        lines = [
            f"- {p['title']} ({p['year']}, {p.get('venue') or 'venue unknown'})"
            f" [{cite(p, 'Most recent')}]"
            for p in recent
        ]
        result.facts.append(
            f"Most recent papers among the {len(papers)} most cited ones indexed here "
            f"(newest year: {newest_year}):\n" + "\n".join(lines)
        )

    if "count" in intents:
        n = cite_profile()
        result.facts.append(
            f"The Google Scholar profile lists {PROFILE_TOTALS['entries']} entries "
            f"(snapshot {SNAPSHOT_DATE}) [{n}]. This assistant indexes the "
            f"{len(papers)} most cited of them."
        )

    if "metrics" in intents:
        n = cite_profile()
        result.facts.append(
            f"Google Scholar totals (snapshot {SNAPSHOT_DATE}): "
            f"{PROFILE_TOTALS['citations']} citations, h-index {PROFILE_TOTALS['h_index']}, "
            f"i10-index {PROFILE_TOTALS['i10_index']} [{n}]."
        )

    return result
