"""Load the public sources, clean them and split them into chunks with citation metadata.

Nothing in this module touches the database, so it can be tested on its own.
"""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import yaml
from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCES_DIR = DATA_DIR / "sources"
PAPERS_FILE = DATA_DIR / "papers.yaml"
# Passages of sources outside this repository that are replaced at ingestion time.
CORRECTIONS_FILE = DATA_DIR / "source_corrections.yaml"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 60
# Bump when the cleaning or splitting logic changes, so every document is re-ingested.
PIPELINE_VERSION = 1

DOC_TYPES = ("cv", "linkedin", "repo_readme", "paper")

GITHUB_USER = "wx-quevedo"
LINKEDIN_URL = "https://www.linkedin.com/in/wxquevedo"

REPOS = (
    "plan-vivo-kit",
    "localia-genai-platform",
    "forex-trading-system",
    "agent-office-visualizer",
    "focus",
    "riemann-hypothesis",
)

# file name -> (doc_id, title)
CV_FILES = {
    "CV_Washington_X_Quevedo_AI_Engineer_EN.pdf": ("cv-ai-engineer", "CV - AI Engineer"),
    "CV_Washington_X_Quevedo_XR_AI_Engineer_EN.pdf": ("cv-xr-ai-engineer", "CV - XR + AI Engineer"),
}
CV_SECTIONS = {
    "Summary",
    "Experience",
    "Earlier roles",
    "Selected Projects",
    "Selected XR Projects",
    "Skills",
    "Research & Recognition",
    "Education",
    "Languages",
}

# LinkedIn working file: only the sections published on the profile are ingested.
# Section 0 (profile settings), 3 (Featured drafts) and 7 (to-do list) are internal notes.
LINKEDIN_FILE = "LINKEDIN_EN.md"
LINKEDIN_SECTIONS = {
    "1": "Headline",
    "2": "About",
    "4": "Experience",
    "5": "Skills",
    "6": "Education, awards and other sections",
}

# Contact details are not needed to answer questions and stay out of the index.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+\d[\d\s-]{7,}\d")

# Metadata that is embedded with the text; the rest is only stored for citations.
EMBED_METADATA_KEYS = {"title", "section", "doc_type"}
LLM_EXCLUDED_METADATA_KEYS = ["content_hash", "chunk_index"]


def content_hash(text: str, metadata: dict | None = None) -> str:
    """Hash of everything that ends up in the index: text, metadata and chunking settings.

    A change to any of them makes the document count as changed on the next ingest.
    """
    payload = json.dumps(
        {
            "text": text,
            "metadata": metadata or {},
            "chunking": [CHUNK_SIZE, CHUNK_OVERLAP, PIPELINE_VERSION],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redact_contacts(text: str) -> str:
    text = EMAIL_RE.sub("", text)
    return PHONE_RE.sub("", text)


@lru_cache
def load_corrections(path: Path = CORRECTIONS_FILE) -> tuple[dict, ...]:
    if not path.exists():
        return ()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return tuple(data.get("corrections") or ())


def _passage_pattern(find: str) -> re.Pattern:
    """Match the passage with any whitespace between words (PDF text breaks lines)."""
    return re.compile(r"\s+".join(re.escape(token) for token in find.split()))


# Indexes of the corrections applied in this process (see unmatched_corrections).
APPLIED_CORRECTIONS: set[int] = set()


def apply_corrections(
    doc_id: str, text: str, corrections: tuple[dict, ...] | None = None
) -> tuple[str, list[int]]:
    """Replace the passages listed for this document; return the text and the indexes used."""
    if corrections is None:
        corrections = load_corrections()
    applied = []
    for index, correction in enumerate(corrections):
        if correction["doc_id"] != doc_id:
            continue
        replacement = correction["replace"]
        text, count = _passage_pattern(correction["find"]).subn(lambda _, r=replacement: r, text)
        if count:
            applied.append(index)
    return text, applied


def unmatched_corrections(doc_ids: set[str]) -> list[dict]:
    """Corrections for these documents that did not match: the original was probably fixed."""
    return [
        c
        for i, c in enumerate(load_corrections())
        if c["doc_id"] in doc_ids and i not in APPLIED_CORRECTIONS
    ]


def make_document(
    text: str,
    *,
    doc_id: str,
    doc_type: str,
    title: str,
    public_url: str,
    year: int | None = None,
    extra: dict | None = None,
) -> Document:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"Unknown doc_type: {doc_type}")
    text, applied = apply_corrections(doc_id, text.strip())
    APPLIED_CORRECTIONS.update(applied)
    metadata = {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": title,
        "section": "",
        "public_url": public_url,
    }
    if year is not None:
        metadata["year"] = year
    metadata.update(extra or {})
    metadata["content_hash"] = content_hash(text, metadata)
    return Document(text=text, id_=doc_id, metadata=metadata)


# ---------------------------------------------------------------- loaders


def cv_text_to_markdown(text: str) -> str:
    """Turn the PDF text of a CV into Markdown headings so it can be split by section."""
    lines = [line.rstrip() for line in redact_contacts(text).splitlines()]
    out: list[str] = []
    section = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in CV_SECTIONS:
            section = stripped
            out.append(f"\n## {stripped}")
        elif (
            section == "Experience"
            and " — " in stripped
            and i + 1 < len(lines)
            and re.match(r"^\d", lines[i + 1].strip())
        ):
            out.append(f"\n### {stripped}")
        elif stripped == "•":
            # pypdf puts each bullet on its own line; join it with the next one.
            out.append("- ")
        elif out and out[-1] == "- ":
            out[-1] = f"- {stripped}"
        else:
            out.append(stripped)
    body = "\n".join(out)
    body = re.sub(r"\s*·\s*(·\s*)+", " · ", body)  # separators left behind by the redaction
    return body.strip()


def load_cvs(sources_dir: Path = SOURCES_DIR) -> list[Document]:
    from llama_index.readers.file import PDFReader

    docs = []
    for file_name, (doc_id, title) in CV_FILES.items():
        pages = PDFReader().load_data(sources_dir / "cv" / file_name)
        text = cv_text_to_markdown("\n".join(page.text for page in pages))
        docs.append(
            make_document(text, doc_id=doc_id, doc_type="cv", title=title, public_url=LINKEDIN_URL)
        )
    return docs


def clean_linkedin(markdown: str) -> str:
    """Keep only the published LinkedIn sections, with plain English headings."""
    out: list[str] = []
    keep = False
    for line in markdown.splitlines():
        match = re.match(r"^## (\d+)\.", line)
        if match:
            name = LINKEDIN_SECTIONS.get(match.group(1))
            keep = name is not None
            if keep:
                out.append(f"## {name}")
            continue
        if line.startswith("# "):
            keep = False
            continue
        if keep and not line.startswith("Quitadas:"):
            out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\s*\([^)]*traducidas\)", "", text)
    return redact_contacts(text).strip()


def load_linkedin(sources_dir: Path = SOURCES_DIR) -> list[Document]:
    raw = (sources_dir / "linkedin" / LINKEDIN_FILE).read_text(encoding="utf-8")
    return [
        make_document(
            clean_linkedin(raw),
            doc_id="linkedin-profile",
            doc_type="linkedin",
            title="LinkedIn profile",
            public_url=LINKEDIN_URL,
        )
    ]


def load_repo_readmes(sources_dir: Path = SOURCES_DIR) -> list[Document]:
    docs = []
    for repo in REPOS:
        text = (sources_dir / "repos" / f"{repo}.md").read_text(encoding="utf-8")
        docs.append(
            make_document(
                redact_contacts(text),
                doc_id=f"repo-{repo}",
                doc_type="repo_readme",
                title=f"GitHub repository {repo}",
                public_url=f"https://github.com/{GITHUB_USER}/{repo}",
            )
        )
    return docs


def paper_text(paper: dict) -> str:
    parts = [
        f"Title: {paper['title']}",
        f"Venue: {paper.get('venue') or 'unknown'}",
        f"Year: {paper['year']}",
        f"Citations (Google Scholar, Oct 2026): {paper.get('citations', 0)}",
    ]
    if paper.get("abstract"):
        parts.append(f"Abstract: {paper['abstract'].strip()}")
    return "\n".join(parts)


def load_papers(papers_file: Path = PAPERS_FILE) -> list[Document]:
    data = yaml.safe_load(papers_file.read_text(encoding="utf-8"))
    docs = []
    for paper in data["papers"]:
        doi = paper.get("doi") or ""
        url = paper.get("url") or (f"https://doi.org/{doi}" if doi else data.get("profile_url", ""))
        docs.append(
            make_document(
                paper_text(paper),
                doc_id=f"paper-{paper['id']}",
                doc_type="paper",
                title=paper["title"],
                public_url=url,
                year=paper["year"],
                extra={
                    "section": "Abstract" if paper.get("abstract") else "Metadata",
                    "citations": paper.get("citations", 0),
                    "doi": doi,
                },
            )
        )
    return docs


LOADERS = {
    "cv": load_cvs,
    "linkedin": load_linkedin,
    "repo_readme": load_repo_readmes,
    "paper": load_papers,
}


def load_documents(doc_types: tuple[str, ...] = DOC_TYPES) -> list[Document]:
    docs: list[Document] = []
    for doc_type in doc_types:
        docs.extend(LOADERS[doc_type]())
    return docs


# --------------------------------------------------------------- chunking


def section_for(node: TextNode) -> str:
    """Build a readable section path from the Markdown header path and the node's own heading."""
    parts = [p for p in node.metadata.get("header_path", "/").split("/") if p]
    first_line = node.text.lstrip().split("\n", 1)[0]
    heading = re.match(r"^#{1,6}\s+(.*)", first_line)
    if heading:
        parts.append(heading.group(1).strip())
    # The H1 of a README is the repository name, already in the title.
    if node.metadata.get("doc_type") == "repo_readme" and parts:
        parts = parts[1:]
    return " > ".join(parts)


def split_document(doc: Document) -> list[TextNode]:
    """Split one document into chunks of about CHUNK_SIZE tokens with stable ids."""
    if doc.metadata["doc_type"] == "paper":
        # One chunk per paper: title, venue, year and abstract stay together.
        pieces = [TextNode(text=doc.text, metadata=dict(doc.metadata))]
    else:
        sections = MarkdownNodeParser().get_nodes_from_documents([doc])
        splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        pieces = []
        for section_node in sections:
            if re.fullmatch(r"#{1,6}[^\n]*", section_node.text.strip()):
                continue  # heading with no body, e.g. "## Experience" before its subsections
            section = section_for(section_node) or "Overview"
            for chunk in splitter.get_nodes_from_documents([section_node]):
                chunk.metadata["section"] = section
                pieces.append(chunk)

    nodes = []
    for index, piece in enumerate(pieces):
        metadata = {k: v for k, v in piece.metadata.items() if k != "header_path"}
        metadata["chunk_index"] = index
        node = TextNode(
            id_=f"{doc.doc_id}#{index:03d}",
            text=piece.text,
            metadata=metadata,
            excluded_embed_metadata_keys=[k for k in metadata if k not in EMBED_METADATA_KEYS],
            excluded_llm_metadata_keys=list(LLM_EXCLUDED_METADATA_KEYS),
        )
        # PGVectorStore stores the SOURCE id as metadata doc_id and deletes by it.
        node.relationships = {NodeRelationship.SOURCE: RelatedNodeInfo(node_id=doc.doc_id)}
        nodes.append(node)
    return nodes
