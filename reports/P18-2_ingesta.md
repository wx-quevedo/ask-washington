# P18·2 - Reporte de ingesta

Fecha: 2026-10-17. Ejecución de referencia: `uv run python -m scripts.ingest --reset` sobre Postgres 16 + pgvector 0.8.7 (Podman), embeddings locales `BAAI/bge-small-en-v1.5` en CPU.

## Documentos y chunks por doc_type

| doc_type | Documentos | Chunks | Fuente |
|---|---:|---:|---|
| cv | 2 | 28 | `data/sources/cv/` (AI Engineer: 13, XR + AI Engineer: 15) |
| linkedin | 1 | 15 | `data/sources/linkedin/LINKEDIN_EN.md`, solo secciones publicadas |
| repo_readme | 6 | 64 | plan-vivo-kit 10, localia-genai-platform 10, forex-trading-system 14, agent-office-visualizer 10, focus 11, riemann-hypothesis 9 |
| paper | 25 | 25 | `data/papers.yaml`, un chunk por paper |
| **Total** | **34** | **132** | |

Chunking: `MarkdownNodeParser` y luego `SentenceSplitter` (500 tokens, solape 60). Cada chunk lleva `doc_id`, `doc_type`, `title`, `section`, `public_url`, `chunk_index`, `content_hash` y, en papers, `year`, `citations` y `doi`.

## Tiempo de ingesta

| Paso | Tiempo |
|---|---|
| Ingesta completa con `--reset` (34 documentos, 132 chunks), tiempo total | 22.2 s |
| De eso, carga de fuentes, embeddings y escritura (medido por el script) | 10.9 s |
| Segunda ejecución sin cambios (todo "unchanged") | 0.3 s |

La primera vez se descarga además el modelo (unos 130 MB) a la caché de Hugging Face.

Idempotencia comprobada: una segunda ejecución omite los 34 documentos; un documento con hash alterado se reemplaza (11 chunks borrados y reinsertados) y el total queda en 132 chunks con 132 `node_id` distintos; `--reset --only linkedin` borra y reinserta solo ese tipo.

## Papers: abstracts

25 de 25 con DOI, URL y abstract, copiados textualmente de la página del editor. Ninguno quedó sin abstract.

| Editorial | Papers |
|---|---|
| Springer (link.springer.com) | p01-p06, p08-p15, p18-p21, p23-p25 (21) |
| ACM Digital Library | p07, p17, p22 (3) |
| IEEE Xplore | p16 (1) |

Los DOI se localizaron con la API de Crossref y se verificó en cada caso que el título coincide y que Quevedo figura como autor. No se usó Google Scholar, ResearchGate, Academia.edu ni Semantic Scholar.

Venues completados desde el editor (estaban vacíos en el seed): p07, p17 y p22 (ACM ICETC '17); p14, p15 y p23 (Springer ISVC); p16 (IEEE CISTI 2021); p18-p21 y p24 (Springer AVR); p25 (Emerging Technologies for Education, Springer LNCS).

## Resultados de search_check

`uv run python -m scripts.search_check` (top 3, similitud coseno):

| Consulta | # | Score | Documento / sección | public_url |
|---|---|---|---|---|
| What XR experience does Washington have? | 1 | 0.618 | cv: CV - XR + AI Engineer / Overview | linkedin.com/in/wxquevedo |
| | 2 | 0.575 | cv: CV - XR + AI Engineer / Summary | linkedin.com/in/wxquevedo |
| | 3 | 0.567 | cv: CV - AI Engineer / Overview | linkedin.com/in/wxquevedo |
| Which papers are about rehabilitation? | 1 | 0.645 | paper: Assistance system for rehabilitation and valuation of motor skills | doi.org/10.1007/978-3-319-60928-7_14 |
| | 2 | 0.607 | paper: Virtual reality integration with force feedback in upper limb rehabilitation | doi.org/10.1007/978-3-319-50832-0_25 |
| | 3 | 0.600 | paper: Virtual rehabilitation system for fine motor skills using a functional hand orthosis | doi.org/10.1007/978-3-319-95282-6_6 |
| What is plan-vivo-kit? | 1 | 0.793 | repo_readme: plan-vivo-kit / Overview | github.com/wx-quevedo/plan-vivo-kit |
| | 2 | 0.760 | repo_readme: plan-vivo-kit / What problem it solves | github.com/wx-quevedo/plan-vivo-kit |
| | 3 | 0.736 | repo_readme: plan-vivo-kit / Architecture | github.com/wx-quevedo/plan-vivo-kit |
| Production ML experience | 1 | 0.652 | paper: Virtual training for industrial automation processes through pneumatic controls | doi.org/10.1007/978-3-319-95282-6_37 |
| | 2 | 0.646 | paper: Multi-user industrial training and education environment | doi.org/10.1007/978-3-319-95282-6_38 |
| | 3 | 0.645 | paper: Immersive industrial process environment from a P&ID diagram | doi.org/10.1007/978-3-319-50835-1_63 |
| Most cited paper | 1 | 0.582 | linkedin: LinkedIn profile / Headline | linkedin.com/in/wxquevedo |
| | 2 | 0.579 | cv: CV - AI Engineer / Research & Recognition | linkedin.com/in/wxquevedo |
| | 3 | 0.566 | cv: CV - XR + AI Engineer / Selected XR Projects | linkedin.com/in/wxquevedo |

Lectura:

- **Bien**: rehabilitación (los 3 son papers de rehabilitación), plan-vivo-kit (los 3 del repo correcto) y experiencia XR (CV XR primero).
- **Floja**: "Production ML experience" trae papers de entrenamiento industrial; los chunks del CV y LinkedIn sobre Stanford/Buscapez (YOLO, FastAPI + ONNX en producción) no entran en el top 3. La consulta es corta y genérica, y "production"/"industrial" pesan más que "ML" para bge-small.
- **Esperable**: "Most cited paper" no puede resolverse por similitud. El chunk del CV en el puesto 2 sí contiene la respuesta ("Most cited: Unity3D-MatLab simulator ... 88 citations"), pero ningún paper aparece. En P18·3 conviene resolver estas preguntas con el metadato `citations`.

## Problemas y decisiones

- **Datos privados en las fuentes**: los dos CV traen email y teléfono en el encabezado. Se eliminan antes de indexar (comprobado: ningún chunk contiene `@inmersoft` ni `+593`). El archivo de LinkedIn es un archivo de trabajo con notas internas en español (ajustes de privacidad, Open to Work solo para reclutadores, borradores de Featured, pendientes); se ingieren solo las secciones publicadas 1, 2, 4, 5 y 6, y se omite la línea de aptitudes quitadas.
- **CV sin URL pública**: `public_url` de los CV apunta al perfil de LinkedIn. Si los CV se publican (por ejemplo en el portafolio), conviene cambiarlo.
- **Abstract duplicado**: p03 (Springer, IT Convergence and Security 2017) y p22 (ACM ICETC '17) muestran el mismo abstract palabra por palabra en sus editoriales. Se copiaron tal cual y quedó anotado en `notes` de cada paper.
- **ACM e IEEE bloquean descargas automáticas** (403 y respuestas vacías); esos 4 abstracts se leyeron en el navegador.
- **Hash solo de texto**: la primera versión no detectaba cambios de metadatos (un cambio de `section` en papers quedó como "unchanged"). Se corrigió: el hash cubre texto, metadatos, parámetros de chunking y `PIPELINE_VERSION`.
- **`PGVectorStore` y `doc_id`**: el store sobrescribe `metadata_.doc_id` con el id del documento de origen del nodo y borra por ese campo; se fija la relación SOURCE de cada chunk al `doc_id` para que coincidan.
- **Logs de Hugging Face**: `llama-index-readers-file` configura el logging raíz en INFO y huggingface_hub registra cada petición HTTP con el logger `httpx2`; se silencian en `vector_store.quiet_logs()`.
- **Modelo sin token de Hugging Face**: funciona sin `HF_TOKEN`; huggingface_hub solo avisa de límites de velocidad más bajos.
