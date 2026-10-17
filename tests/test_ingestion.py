"""Chunking and metadata tests. They do not need the database or the embedding model."""

from llama_index.core.node_parser import TokenTextSplitter

from app.ingestion import (
    CHUNK_SIZE,
    clean_linkedin,
    cv_text_to_markdown,
    make_document,
    paper_text,
    split_document,
)

REQUIRED_KEYS = {"doc_id", "doc_type", "title", "section", "public_url"}

README = (
    """# demo-repo

Intro paragraph about the repository.

## Features

"""
    + "\n".join(f"- Feature {i}: " + "word " * 40 for i in range(40))
    + """

## Install

Run `uv sync`.
"""
)


def count_tokens(text: str) -> int:
    return len(TokenTextSplitter()._tokenizer(text))


def test_readme_chunks_have_citation_metadata_and_bounded_size():
    doc = make_document(
        README,
        doc_id="repo-demo",
        doc_type="repo_readme",
        title="GitHub repository demo-repo",
        public_url="https://github.com/wx-quevedo/demo-repo",
    )
    nodes = split_document(doc)

    assert len(nodes) > 3
    for i, node in enumerate(nodes):
        assert node.metadata.keys() >= REQUIRED_KEYS
        assert node.metadata["doc_type"] == "repo_readme"
        assert node.metadata["public_url"] == "https://github.com/wx-quevedo/demo-repo"
        assert node.node_id == f"repo-demo#{i:03d}"
        assert node.ref_doc_id == "repo-demo"
        assert count_tokens(node.text) <= CHUNK_SIZE
    sections = {node.metadata["section"] for node in nodes}
    assert {"Features", "Install"} <= sections
    # Only title, section and doc_type go into the embedding text.
    embed_text = nodes[0].get_content(metadata_mode="embed")
    assert "public_url" not in embed_text and "title: GitHub repository demo-repo" in embed_text


def test_paper_is_a_single_chunk_with_year():
    paper = {
        "id": "p99",
        "title": "A test paper",
        "venue": "Test Venue",
        "year": 2017,
        "citations": 12,
        "abstract": "This paper tests things. " * 30,
    }
    doc = make_document(
        paper_text(paper),
        doc_id="paper-p99",
        doc_type="paper",
        title=paper["title"],
        public_url="https://doi.org/10.0000/test",
        year=2017,
    )
    nodes = split_document(doc)

    assert len(nodes) == 1
    assert nodes[0].metadata["year"] == 2017
    assert nodes[0].text.startswith("Title: A test paper\nVenue: Test Venue\nYear: 2017")


def test_content_hash_is_stable_and_detects_changes():
    a = make_document("same text", doc_id="x", doc_type="cv", title="t", public_url="u")
    b = make_document("same text", doc_id="x", doc_type="cv", title="t", public_url="u")
    c = make_document("other text", doc_id="x", doc_type="cv", title="t", public_url="u")
    assert a.metadata["content_hash"] == b.metadata["content_hash"]
    assert a.metadata["content_hash"] != c.metadata["content_hash"]


def test_cv_contacts_are_redacted_and_sections_detected():
    text = (
        "Washington X. Quevedo\n"
        "Quito · me@example.com · +593 98 000 0000 ·\n"
        "Summary\nAI engineer.\nExperience\n"
        "Acme — Engineer\n07/2026 – present\n•\nBuilt things.\n"
    )
    md = cv_text_to_markdown(text)
    assert "@" not in md and "+593" not in md
    assert "## Summary" in md and "### Acme — Engineer" in md
    assert "- Built things." in md


def test_linkedin_keeps_only_published_sections():
    raw = (
        "# Working notes\nintro\n## 0. Ajustes aplicados\n- private setting\n"
        "## 1. Headline (max 220)\nAI Engineer\n## 3. Featured\n- draft\n"
        "## 5. Skills (21 publicadas)\nPython\nQuitadas: SCADA\n## 7. Pendiente para F2\n- todo\n"
    )
    cleaned = clean_linkedin(raw)
    assert "## Headline" in cleaned and "AI Engineer" in cleaned
    assert "## Skills" in cleaned and "Python" in cleaned
    for hidden in ("private setting", "draft", "SCADA", "todo", "Working notes"):
        assert hidden not in cleaned


def test_content_hash_changes_with_metadata():
    a = make_document("same text", doc_id="x", doc_type="cv", title="t", public_url="u1")
    b = make_document("same text", doc_id="x", doc_type="cv", title="t", public_url="u2")
    assert a.metadata["content_hash"] != b.metadata["content_hash"]
