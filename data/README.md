# data/

Public source documents for ingestion. Only `README.md`, `papers_seed.yaml` and `papers.yaml` are committed; everything else in this folder is ignored by git.

- `sources/cv/` - the two English CVs (PDF), copied from Washington's working folder.
- `sources/linkedin/LINKEDIN_EN.md` - LinkedIn working file. Only the published sections are ingested.
- `sources/repos/<repo>.md` - READMEs of the 6 public repositories of github.com/wx-quevedo.
- `papers_seed.yaml` - the 25 most cited papers (snapshot of the Google Scholar profile, 2026-10-17).
- `papers.yaml` - the seed enriched with DOI, URL and abstract taken verbatim from the publisher pages (Springer, ACM, IEEE). This is the file that is ingested.

Only public material belongs here. Do not add `PROFILE.md`, private documents, server addresses or credentials.
