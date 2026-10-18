# Ask Washington - documento del proyecto

## Contexto

Ask Washington es un chat RAG para el portafolio de Washington X. Quevedo (AI Engineer, XR + AI Engineer). Un reclutador pregunta sobre su experiencia y el sistema responde citando las fuentes públicas de Washington: CV, perfil de LinkedIn, READMEs de sus repos públicos y abstracts de sus papers. Desde P18·2 solo se ingieren fuentes públicas; PROFILE.md queda fuera.

También es su proyecto para aprender RAG, bases vectoriales, LangChain y LlamaIndex.

Este proyecto es P18 dentro del plan de `C:\xampp\htdocs\enhanced-me`. El seguimiento de fases y tiempos vive en el `plan.json` de enhanced-me y se actualiza desde ese proyecto; este repo no lleva `plan.json` propio.

## Decisiones y su porqué

| Decisión | Por qué |
|---|---|
| Python + FastAPI | Python es el ecosistema natural de RAG (LlamaIndex, LangChain, modelos de embeddings). FastAPI da una API tipada, documentación automática y async con poco código. |
| uv para entorno y dependencias | Rápido, con lockfile reproducible y gestión de la versión de Python en una sola herramienta. |
| LlamaIndex para ingesta e índice | Es fuerte en cargar documentos, partirlos en fragmentos y construir índices; aprenderlo es parte del objetivo. |
| LangChain para la cadena de respuesta | Es fuerte en componer prompts, modelos y recuperadores; usar ambos permite comparar en un mismo proyecto. |
| Postgres con pgvector | Una sola base para vectores y metadatos, SQL conocido, y la misma tecnología sirve en local y en el VPS sin depender de un servicio pago. |
| Embeddings locales con BAAI/bge-small-en-v1.5 | Modelo pequeño (384 dimensiones), buena calidad para inglés, corre en CPU y no cuesta por llamada. |
| Respuestas con la API de Claude, modelo económico, con límites de uso y de gasto | Buena calidad de redacción y citas a bajo costo; los límites evitan sorpresas en un endpoint público. |
| Evaluación con un set de unas 30 preguntas | Permite medir si los cambios de ingesta o prompt mejoran o empeoran las respuestas, en vez de juzgar a ojo. |
| Repo público en inglés | Es parte del portafolio y lo leen reclutadores internacionales. |
| Despliegue en su VPS más adelante | Control total y costo fijo; se aborda en P18.5 cuando la app funcione en local. |
| Podman en local (en lugar de Docker Desktop) | Ya está instalado y corriendo en la máquina de desarrollo. El `docker-compose.yml` es compatible con Docker y Podman, y el README documenta ambos. |
| Puerto 5432 en el host | Estaba libre al crear el proyecto; se puede cambiar con `POSTGRES_PORT` en `.env`. |
| `scripts/dev-db-host.ps1` para la IP de la máquina de Podman | La máquina de Podman (WSL, rootful) no reenvía puertos a `localhost` de Windows y el modo de red de usuario no lo resolvió. El script reescribe solo `DATABASE_URL` en el `.env` local con la IP actual de la máquina; con Docker o en Linux se sigue usando `localhost`. |
| Sin la skill python-executor | autoskills la propuso por detectar Python, pero manda el código a ejecutar al servicio en la nube inference.sh mediante su CLI `belt`. Este proyecto corre todo en local con uv, no queremos enviar código ni datos a un tercero, y sus palabras de activación ("python", "execute code") son tan genéricas que se dispararía en casi cualquier tarea. |
| psycopg 3 directo en la base (sin ORM) | Para la base solo hace falta comprobar conexión y extensión; el acceso a vectores lo harán LlamaIndex y LangChain. |
| Chunks de ~500 tokens con 60 de solape; primero por título Markdown | Partir por título mantiene juntas las piezas de un mismo puesto o sección y da la `section` para citar; 500 tokens caben bien en el contexto de bge-small (512) y el solape evita cortar una idea a la mitad. |
| Un chunk por paper (título + venue + año + citas + abstract) | Un abstract cabe entero y es la unidad que se cita; partirlo solo diluiría la búsqueda. |
| Hash de texto + metadatos + parámetros de chunking, en la tabla `ingested_documents` | Hace la ingesta idempotente y detecta también cambios de metadatos o de chunking, no solo de texto. Más simple y transparente que un docstore de LlamaIndex. |
| Ids de chunk estables (`<doc_id>#NNN`) | Facilitan depurar y comparar resultados entre ejecuciones. |
| Solo `title`, `section` y `doc_type` entran al embedding | Dan contexto a cada chunk sin meter URLs ni hashes en el vector. |
| Se quitan email y teléfono de los CV, y se ingieren solo las secciones publicadas de LinkedIn | El chat responde a reclutadores sobre experiencia; los datos de contacto y las notas internas del archivo de trabajo de LinkedIn (privacidad, Open to Work, pendientes) no son públicos. |
| `public_url` de los CV = perfil de LinkedIn | Los CV no están publicados en ninguna URL; LinkedIn es la fuente pública equivalente. |
| `data/papers.yaml` versionado; `data/sources/` no | Los papers enriquecidos son datos públicos y costosos de reconstruir; las fuentes se copian o descargan de nuevo. |
| Abstracts tomados de la página del editor (Springer, ACM, IEEE) vía Crossref y DOI | Son la fuente oficial y citable; no se usa Google Scholar ni sitios de terceros. |
| Claude Haiku 5.5 (`claude-haiku-5-5`) como modelo por defecto | Es el modelo económico actual de Anthropic ($0.10 / $0.50 por millón de tokens de entrada / salida); responder con citas a partir de 6 chunks no necesita un modelo mayor. Costo medido: unos USD 0.0004 por respuesta. |
| Sin `temperature` (se pidió 0.2) | Claude Haiku 5.5 rechaza con un 400 cualquier valor de muestreo distinto del predeterminado. `LLM_TEMPERATURE` queda vacío (no se envía) y se puede fijar para modelos que lo acepten. |
| Razonamiento (thinking) desactivado | En Haiku 5.5 viene activado por defecto y sus tokens cuentan contra `max_tokens` (600) y el presupuesto; para respuestas cortas con fuentes no aporta. |
| Fábrica de proveedores en `app/llm.py` | La cadena solo recibe un `BaseChatModel` de LangChain; agregar Ollama o la API de Localia es escribir un constructor y registrarlo, sin tocar la cadena. |
| Ruta de ranking determinista con expresiones regulares | "Más citado", "más reciente", "cuántos papers" o el h-index no se resuelven por similitud; se calculan desde `data/papers.yaml` y los totales del perfil, y el LLM solo redacta. Las regex (inglés y español) son predecibles y gratis. |
| El retriever de LangChain envuelve el `PGVectorStore` de LlamaIndex | Reutiliza la misma tabla, el mismo modelo de embeddings y la misma instrucción de consulta de P18·2, sin una segunda integración con pgvector. |
| Presupuesto diario en `usage_daily` y log en `qa_log` (Postgres) | Sobrevive reinicios y varios procesos; se calcula con los tokens reales de cada respuesta y precios configurables. La IP se guarda como hash SHA-256 con sal. |
| Rate limit con slowapi en memoria | Suficiente para un solo proceso; se reinicia con la app. El gasto, que es lo que importa proteger, sí queda en Postgres. |
| La pregunta va entre etiquetas `<question>` y las fuentes numeradas entre `<sources>` | Separa con claridad la entrada no confiable de las instrucciones y facilita que el modelo cite `[n]`. |
| p22 sin abstract | Su página de ACM muestra, palabra por palabra, el mismo abstract que p03 en Springer. El texto describe una app de VR para turismo (sin marketing), así que se conservó en p03; p22 queda con título, venue, año y citas. |
| Recuperación híbrida por defecto (`RETRIEVAL_MODE=hybrid`) | Vector + full-text de Postgres fusionados con RRF: hit@3 de 0.889 a 1.000 y MRR de 0.914 a 0.981 con 60 ms por consulta. El reranker bge-base logra MRR 1.000 pero tarda 4 s en CPU; queda como opción (`rerank`). |
| Set de 30 preguntas versionado en `data/eval/questions.yaml` | Permite medir cada cambio de recuperación o prompt con el mismo criterio; la parte de recuperación es gratis y la de respuestas cuesta unos USD 0.011. |
| LinkedIn solo cuando falta información, con 2 ejemplos en el prompt | Las menciones innecesarias bajaron del 59% al 7% sin perder keywords ni citas y con el mismo costo. |
| Interfaz en HTML, CSS y JS sin framework, servida por la misma FastAPI | Una sola página no necesita build ni dependencias; sin scripts inline, funciona con una CSP estricta (`default-src 'self'`). |
| `rerank_light` (MiniLM) no queda por defecto | No acierta q20, baja el MRR de 0.981 a 0.963 y tarda 779 ms (el límite era 250 ms). Queda disponible por env. |
| Docker: multi-stage con uv, torch solo CPU y modelo de embeddings dentro de la imagen | Sin dependencias CUDA (unos 2.5 GB menos) y sin descargas en tiempo de ejecución (`HF_HUB_OFFLINE=1`). torch pasó a ser dependencia directa porque `[tool.uv.sources]` solo aplica a dependencias directas. |
| Proyecto Compose propio, app solo en 127.0.0.1, db sin puertos, red y volumen propios | Regla dura: no afectar otros proyectos del VPS. Todo comando del deploy usa `-p ask-washington`. |
| IP real con `ProxyHeadersMiddleware` en la app (además de `--proxy-headers` en uvicorn) | La lógica queda cubierta por pruebas. Se confía en `X-Forwarded-For` solo desde `FORWARDED_ALLOW_IPS`: 127.0.0.1 y los rangos privados de Docker, porque nginx llega al contenedor por el gateway del bridge. nginx sobrescribe la cabecera con `$remote_addr`, así que un cliente no puede falsificarla. |
| Datos al servidor por `pg_dump -Fc` de `data_chunks` e `ingested_documents` | El servidor nunca recibe los CV ni las demás fuentes; el dump restaura también los índices HNSW y de texto completo. |
| Host y usuario del VPS solo en `deploy/.deploy.local` (ignorado) | El repo será público. Los secretos de producción (contraseña de la db, sal del hash de IP) se generan una vez y se guardan en ese mismo archivo para que los redeploys no cambien la contraseña del volumen. |
| Cachés de modelos fijas en `/app/models` y verificación offline en el build | LlamaIndex usa una carpeta de caché por usuario distinta de `HF_HOME`; fijarlas todas y cargar el modelo como el usuario final durante el build evita que el error aparezca recién en producción. |
| Ask Washington no tiene selector de idioma propio | Lo incrusta el portafolio, que ya tiene el switch EN/ES; el widget obedece a `?lang=` y a `postMessage` de orígenes permitidos. |
| Textos solo en `app/static/i18n/{en,es}.json`; el servidor los inserta en la página | Sin parpadeo ni dependencia de JS para el primer render (y mejor para buscadores); el JS usa los mismos archivos para cambiar de idioma en caliente. Una prueba verifica que la plantilla no tenga texto visible fijo. |
| Idioma de la respuesta decidido en el backend con un detector simple | Reglas deterministas y comprobables: idioma de la interfaz salvo que la pregunta esté claramente en el otro; lo ambiguo (un nombre, una sigla) sigue a la interfaz. El prompt recibe una instrucción explícita ("Write the whole answer in Spanish."). |
| CSP con `frame-ancestors` en la app, no en nginx | Depende de `EMBED_ALLOWED_ORIGINS`, que vive en el `.env`. Dos cabeceras CSP se aplican a la vez, así que nginx ya no debe enviar la suya ni `X-Frame-Options: DENY`. |
| `X-Frame-Options: SAMEORIGIN` solo cuando no hay orígenes permitidos | `X-Frame-Options` no admite listas; con orígenes permitidos manda `frame-ancestors`. |
| Migración puntual del sitio nginx en `remote-deploy.sh` | Quita solo las dos líneas de cabecera del sitio gestionado por certbot (con respaldo y `nginx -t`), así que el redeploy no necesita `-ForceNginx` ni arriesga las líneas de certbot. |
| Orígenes del portafolio en `EMBED_ALLOWED_ORIGINS` (incluido `http://localhost:4321`) | El portafolio incrusta el widget en producción (con y sin `www`) y en su servidor de desarrollo de Astro; cualquier otro origen sigue bloqueado. |
| El widget publica su alto solo hacia el origen real del padre | Con varios orígenes permitidos, publicar hacia todos genera errores de consola en el portafolio por cada origen que no coincide. |
| Línea de aviso propia en el widget | El widget no muestra el pie; el aviso de posibles errores debe estar visible donde se lee la respuesta. |
| Interfaz de chat sin memoria | Se ve y se usa como un chat, pero cada pregunta va sola a `/ask` (sin historial ni localStorage): el costo por pregunta no crece con la conversación y no se guarda nada del visitante. |
| Widget de alto fijo; solo el hilo tiene scroll | Así se comportan los chats de soporte en paneles flotantes; el composer siempre a la vista. El mensaje `ask-washington:height` queda solo por compatibilidad. |
| Respuesta larga visible desde su inicio | Bajar siempre al final escondía el comienzo de las respuestas largas; ahora se baja al final solo si la respuesta cabe en el hilo. |
| Separador entre citas pegadas, insertado por el JS | Con superíndices, [4][5][6] se leía como "456"; un selector CSS no distingue si hay texto en medio. |
| Correcciones de fuentes en `data/source_corrections.yaml`, aplicadas en la ingesta | Los CV y el LinkedIn viven fuera del repo y no se editan desde aquí; el archivo versionado reemplaza los pasajes incorrectos antes del hash (solo se reingiere lo afectado) y avisa cuando una corrección deja de coincidir porque ya se corrigió el original. |
| Solo la cifra pública del detector (mAP50 0.96, detección, validación) | Los porcentajes internos de prueba (66 % a 93 %) y el IoU de caja 0.90 no se publican; la clasificación de especies sigue mejorando con más fotos validadas. |
| Producción sin `http://localhost:4321` | Solo el portafolio (`https://washingtonquevedo.com` y `www`) puede incrustar el widget en producción; el origen de desarrollo vive en el `.env` local. |
| El sitio nginx se instala solo la primera vez (o con `-ForceNginx`) | Después de certbot el archivo queda gestionado por certbot; sobrescribirlo en cada deploy quitaría el bloque HTTPS. |

## Plan de los 5 prompts

1. **P18·1 base**: entorno, Postgres con pgvector en contenedor, app FastAPI con `/health`, pruebas, ruff, documentos y primer commit.
2. **P18·2 ingesta**: cargar CV, LinkedIn, READMEs y abstracts de papers con LlamaIndex, generar embeddings con bge-small y guardarlos en pgvector.
3. **P18·3 respuestas**: cadena de LangChain que recupera fragmentos y responde con la API de Claude citando fuentes, con límites de uso y de gasto.
4. **P18·4 evaluación**: set de unas 30 preguntas con respuestas esperadas y métricas de recuperación y de respuesta.
5. **P18·5 interfaz y despliegue**: interfaz de chat y despliegue en el VPS.

## Bitácora

### 2026-10-16 - P18·1 base

- Entorno revisado: Python 3.11.9 y 3.12.11 (uv), uv 0.11.32, git 2.45.2, Node 24.17. Docker Desktop no está instalado; se usa Podman 6.0.2 con podman-compose 1.6.0.
- `docker-compose.yml` con `pgvector/pgvector:pg16`, volumen con nombre `ask_washington_pgdata`, puerto 5432 y credenciales de desarrollo desde `.env`.
- Proyecto con uv y Python 3.12: `app/` (main, config, db), `scripts/init_db.py`, `tests/`, `data/` ignorada salvo su README.
- `GET /health` informa el estado de la app, la conexión a la base y la extensión vector. La extensión se crea al arrancar y con `scripts/init_db.py`.
- pytest (health, extensión vector, operación con el tipo vector) y ruff.
- LICENSE MIT, README en inglés y este documento.
- Skills de autoskills instaladas para claude-code: fastapi, fastapi-python, fastapi-templates, pydantic, python-testing-patterns y python-executor (esta última se quitó el 2026-10-17).
- Problema encontrado: la máquina de Podman (WSL, rootful) no reenvía puertos a `localhost` de Windows; tampoco funciona para otros contenedores. La verificación se hizo con `DATABASE_URL` apuntando a la IP de la VM (172.29.23.4). Hay que corregirlo de forma permanente (ver próximos pasos).
- Verificación: `/health` 200 con conexión y vector 0.8.7; pytest 3 aprobadas; ruff sin errores.

### 2026-10-17 - P18·1 base: puertos de Podman y limpieza de skills

Problema: con la máquina de Podman en WSL y rootful, los puertos publicados (`0.0.0.0:5432->5432`) no llegan a `localhost` de Windows. Afecta a todos los contenedores de la máquina, no solo a este proyecto (vive-bago-api en 8080 tampoco respondía). En modo rootful Podman publica los puertos con reglas NAT y sin socket en escucha dentro de la máquina, así que el relay de localhost de WSL no los ve.

Lo que se probó:

1. Modo de red de usuario (`podman machine set --user-mode-networking=true` con la máquina detenida). La máquina arrancó con gvproxy y la distro `podman-net-usermode` activos, pero ningún puerto respondió en localhost.
2. Recrear el contenedor de este proyecto con `podman compose down` y `podman compose up -d` después del cambio, por si `podman start` no registraba los puertos. Siguió sin responder.
3. Consulta a gvproxy (`/services/forwarder/all`): lista vacía, sin ningún reenvío registrado, y el servicio `gvforwarder` de la máquina inactivo. Conclusión: con Podman 6.0.2 y máquina rootful, el modo de red de usuario no publica los puertos.

Solución adoptada: volver al modo de red anterior (`--user-mode-networking=false`) y usar `scripts/dev-db-host.ps1`, que detecta la IP actual de la máquina y reescribe solo `DATABASE_URL` en el `.env` local. Se corre antes de levantar la app y después de cada reinicio de la máquina. No se probaron la red `mirrored` de WSL ni el modo rootless.

Incidencia al volver al modo anterior: al salir del modo de red de usuario, la máquina quedó sin `/etc/resolv.conf`. WSL generó `/mnt/wsl/resolv.conf`, pero se perdió el enlace de `/etc/resolv.conf` hacia ese archivo. Sin él, aardvark-dns falla (`open resolv.conf: No such file or directory`) y no arranca ningún contenedor de la máquina, incluidos los de vive-bago. Se arregló restaurando el enlace y volviendo a arrancar los contenedores:

```powershell
podman machine ssh "sudo ln -sf /mnt/wsl/resolv.conf /etc/resolv.conf"
podman start vive-bago-oracle vive-bago-minio vive-bago-api ask-washington-db
```

Verificación con la solución adoptada (`.env` sin variables temporales, tras correr `scripts/dev-db-host.ps1`): `/health` 200 con conexión y vector 0.8.7; pytest 3 aprobadas; ruff sin errores.

Skills: se quitó python-executor (ver decisiones) de `.agents/skills`, `.claude/skills` y `skills-lock.json`.

### 2026-10-17 - P18·2 ingesta

Estado: terminado. Detalle completo en `reports/P18-2_ingesta.md`.

- Fuentes copiadas a `data/sources/`: 2 CV en inglés y `LINKEDIN_EN.md` desde enhanced-me, y los README de los 6 repos públicos descargados con `gh api`.
- `data/papers.yaml`: los 25 papers del seed con DOI, URL y abstract textual de la página del editor (21 Springer, 3 ACM, 1 IEEE); los 25 tienen abstract. p03 y p22 tienen el mismo abstract en sus editoriales y quedó anotado.
- `app/ingestion.py` (carga, limpieza, chunking y metadatos, sin base de datos) y `app/vector_store.py` (bge-small, `PGVectorStore`, tabla `ingested_documents`).
- `scripts/ingest.py` con `--reset` y `--only <doc_type>`, idempotente; `scripts/search_check.py` con 5 consultas de prueba.
- Índice: 34 documentos y 132 chunks (cv 2/28, linkedin 1/15, repo_readme 6/64, paper 25/25). Ingesta completa desde cero en unos 22 s (11 s de embeddings y escritura).
- Pruebas: 6 de chunking y metadatos sin base de datos; 9 en total aprobadas.
- Búsqueda: buena para papers por tema y para repos; floja en "Production ML experience" (salen papers de entrenamiento industrial antes que la experiencia en Stanford) y en "Most cited paper" (la búsqueda semántica no ordena por citas).

### 2026-10-17 - P18·3 respuestas

Estado: terminado. Detalle completo en `reports/P18-3_respuestas.md`.

- `POST /ask` con validación (3 a 500 caracteres), respuesta con `answer`, `sources` numeradas `[n]`, `provider`, `model`, `latency_ms` y `usage`.
- `app/llm.py` (fábrica por `LLM_PROVIDER`, solo `anthropic`), `app/rag.py` (retriever sobre `data_chunks`, top_k 6, prompt de sistema en inglés), `app/ranking.py` (ruta determinista), `app/usage.py` (`usage_daily`, `qa_log`).
- Límites: 10 por minuto y 100 por día por IP (slowapi) y tope diario de USD 1.00 con tokens reales; al superarlos, 429.
- p03/p22: verificado en ambas editoriales; el abstract queda en p03 y p22 queda vacío. Re-ingesta con `--only paper`: 1 documento actualizado (p22), 24 sin cambios.
- Pruebas: 31 aprobadas (22 nuevas de `/ask` con LLM simulado: formato y citas, longitud, rate limit, tope diario, ranking, fábrica de proveedores).
- Prueba real con 5 preguntas y Claude Haiku 5.5: 11 813 tokens de entrada y 1 666 de salida, USD 0.0020 en total; las 5 respuestas citan fuentes correctas, incluida "Production ML experience" (Buscapez) y "most cited" (p01, 88 citas) por la ruta de ranking.

### 2026-10-17 - P18·4 evaluación

Estado: terminado. Detalle completo en `reports/P18-4_evaluacion.md`.

- `data/eval/questions.yaml`: 30 preguntas escritas desde las fuentes indexadas (XR/VR 5, IA/ML en producción 5, papers 5, repos 5, trayectoria 4, español 3, fuera de alcance 2, inyección 1), con documentos y hechos esperados.
- `scripts/eval.py`: recuperación sin LLM (hit@3, hit@6, MRR, kw@6, latencia) y respuestas con LLM (keywords, citas válidas, rechazos, LinkedIn, latencia, costo) con tope de gasto; salida en `reports/eval/`.
- `app/retrieval.py`: modos `vector`, `hybrid` (full-text con tsvector e índice GIN, fusión RRF) y `rerank` (cross-encoder local).
- Recuperación: A vector hit@3 0.889 / MRR 0.914 / 26 ms; B híbrida 1.000 / 0.981 / 60 ms; C con bge-reranker-base 1.000 / 1.000 / 4030 ms. Se eligió B.
- Respuestas (híbrida, prompt nuevo): keywords 0.963, citas válidas 0.984, 3/3 rechazos correctos, LinkedIn en 7% de las respuestas con contenido (antes 59%), 1.6 s de media, USD 0.0110 por corrida. Costo total de la evaluación: USD 0.0220.
- Sigue fallando q20 (precisión del gaze tracker): el chunk con "2.51" solo lo recupera el reranker.
- Pruebas: 37 aprobadas (RRF, puntuación de respuestas y eval en modo solo recuperación sin API).

### 2026-10-17 - P18·5 interfaz y despliegue

Estado: código listo y validado en local; el despliegue al VPS lo ejecuta Washington con `deploy/deploy.ps1`. Detalle completo y comandos exactos en `reports/P18-5_deploy.md`.

- Interfaz en `GET /` (`app/static/`): preguntas sugeridas, citas `[n]` enlazadas a las fuentes, estados de carga y error (429), accesible y usable en móvil. Capturas en `reports/screenshots/`.
- `rerank_light` (ms-marco-MiniLM-L-6-v2, 20 a 6): hit@3 1.000, MRR 0.963, 779 ms; no acierta q20. Queda `hybrid` por defecto.
- Producción: `Dockerfile` multi-stage (torch CPU, modelo dentro, usuario no root, healthcheck), `docker-compose.prod.yml` (proyecto `ask-washington`, app en `127.0.0.1:8710`, db sin puertos, límites 1.5 GB y 512 MB), sitio nginx con cabeceras de seguridad.
- IP real detrás del proxy: `ProxyHeadersMiddleware` con `FORWARDED_ALLOW_IPS`; pruebas de IP real, de cabecera falsificada y de rate limit por cliente detrás del mismo proxy.
- `deploy/deploy.ps1` (con `-DryRun`), `deploy/remote-deploy.sh` y `deploy/rollback.ps1`. Validado en local: sintaxis de PowerShell, `bash -n` y shellcheck, dry run completo (paquete, dump de 328 KB, `.env` de producción), restauración del dump dos veces en una base de prueba, compose de producción con `config`.
- La imagen de producción pesa 1.93 GB (medida en la corrección posterior).
- Revisión de secretos del historial (gitleaks 8.30.1 y búsqueda propia): sin secretos, sin IP ni usuario del VPS, sin emails ni teléfonos privados.
- Pruebas: 43 aprobadas.
- Finales de línea: `git archive` con `core.autocrlf=true` empaquetaba CRLF; se fijó LF con `.gitattributes` y `git -c core.autocrlf=false archive`.

### 2026-10-17 - P18·5 corrección del deploy (502 en /ask)

- Síntoma en el VPS: `/health` ok y datos restaurados, pero `POST /ask` daba 502 en unos 135 ms; el log mostraba que sentence-transformers no encontraba el modelo y no podía descargarlo (modo offline).
- Causa: `HuggingFaceEmbedding` de LlamaIndex usa su propia carpeta de caché por usuario (`platformdirs`), distinta de `HF_HOME`, donde el build había descargado el modelo como root.
- Corrección: `HF_HOME`, `LLAMA_INDEX_CACHE_DIR` y `TIKTOKEN_CACHE_DIR` fijos en `/app/models` en ambos stages; `download_models.py` usa los cargadores de la app; verificación offline como usuario `app` al final del build; prueba de humo `POST /ask` al final de `remote-deploy.sh`; `$PSScriptRoot` fuera de `param()` en los scripts de PowerShell 5.1.
- Verificado en local con el compose de producción: `POST /ask` 200 con citas, imagen de 1.93 GB, app en 578 MB de RAM.

### 2026-10-18 - P20 idioma

Estado: terminado y verificado en local. Detalle completo en `reports/P20_idioma.md`.

- Interfaz en inglés o español con `?lang=en|es` (inglés por defecto); todos los textos en `app/static/i18n/en.json` y `es.json`; `lang` del `<html>` y título según el idioma.
- Modo widget `?embed=1`: sin encabezado ni pie, compacto, informa su alto al padre con `postMessage` solo hacia `EMBED_ALLOWED_ORIGINS`; acepta `{type: "ask-washington:lang"}` solo de esos orígenes.
- `POST /ask` acepta `lang`; el idioma de la respuesta sigue a la interfaz salvo que la pregunta esté claramente en el otro idioma; también en la ruta de ranking y en los mensajes de error (422, 429, 502).
- La app envía la CSP con `frame-ancestors 'self'` más los orígenes permitidos; nginx deja de enviar CSP y `X-Frame-Options`, y `remote-deploy.sh` migra el sitio existente sin tocar certbot.
- Pruebas: 74 en la suite normal, más una prueba de JS con Playwright (`tests/e2e`, se omite si Playwright no está instalado).
- Prueba real (4 preguntas): las 4 en el idioma esperado y con citas válidas, USD 0.0018.

### 2026-10-18 - P9 Ask Washington acepta el portafolio

- Orígenes permitidos: `https://washingtonquevedo.com`, `https://www.washingtonquevedo.com` y `http://localhost:4321`, configurados en `deploy/.deploy.local` (ignorado) y pasados al `.env` de producción por `deploy.ps1`; valores de ejemplo en `deploy/.deploy.local.example`.
- El widget (`?embed=1`) muestra una línea discreta con el aviso de posibles errores (desde los archivos i18n; contraste 6.9:1).
- El alto se publica solo hacia el origen real del padre (sin errores de consola con varios orígenes permitidos).
- Pruebas: 77 en la suite normal (nuevas: orígenes del portafolio aceptados y otros rechazados, aviso del widget en los dos idiomas) y 6 en Playwright: una página en `http://localhost:4321` muestra el widget, cambia el idioma y recibe el alto sin errores de consola; `http://localhost:8102` y `http://127.0.0.1:8103` no pueden incrustarlo ni cambiar su idioma.
- Capturas del widget actualizadas.

### 2026-10-18 - P20b interfaz de chat

Estado: terminado y verificado en local (sin deploy). Referencias y patrones en la sección "Referencias de chats (P20b)".

- Página completa y widget pasan de formulario a chat: cabecera ("Ask Washington"; en el widget, nada más), saludo del asistente en burbuja, 4 preguntas sugeridas como chips que se envían al hacer clic y desaparecen tras la primera pregunta, hilo con burbujas (visitante a la derecha en color de acento, respuestas a la izquierda en fondo neutro), citas como superíndices enlazados y lista compacta de fuentes bajo cada respuesta, indicador de tres puntos con texto para lectores de pantalla, errores como burbuja del asistente.
- Composer fijo abajo: caja que crece hasta 4 líneas, botón de enviar con icono y `aria-label`, Enter envía y Shift+Enter salta de línea, contador solo desde 400 caracteres, aviso de posibles errores en letra pequeña.
- Widget: ocupa el 100 % del alto del iframe, solo el hilo tiene scroll; el portafolio debe darle alto fijo (documentado en el README). Cambio de idioma por `postMessage` y orígenes permitidos sin cambios.
- Textos nuevos en `en.json` y `es.json` (saludo, sugerencias propuestas, etiquetas del chat, indicador de escritura); se quitaron los del formulario.
- Contraste AA verificado: texto del visitante 6.1:1, respuestas 13.8:1, chips 8.6:1, aviso y fuentes 6.9:1, placeholder 4.6:1; borde de la caja 3.0:1.
- Pruebas: 77 en la suite normal y 14 en Playwright (`tests/e2e`, con `/ask` simulado): estado inicial, chip que envía, burbujas a cada lado, indicador, citas y fuentes, Enter y Shift+Enter, segunda pregunta con anclas propias, caja que crece y contador, errores en español, 360 px sin scroll horizontal, respuesta larga desde su inicio, widget en `http://localhost:4321` llenando un panel de 400 x 600 con solo el hilo desplazable, y sin errores de consola.
- Capturas en `reports/screenshots/p20b/` (estado inicial EN y ES, conversación con 2 preguntas y fuentes, indicador de escritura, celular a 390 px, widget en un panel de demo). Costo de las respuestas reales usadas en las capturas: unos USD 0.0018.

### 2026-10-18 - P20c corrección de fuentes (Buscapez) y orígenes de producción

Una respuesta real afirmó que la app de Buscapez está publicada en App Store y Google Play y citó porcentajes internos de prueba. A octubre de 2026 la app móvil está en desarrollo (no publicada) y la cifra pública es "mAP50 0.96 (detection, validation)".

**Dónde estaba** (todo en fuentes fuera del repo; también en `data_chunks` local):

| Documento | Original | Fragmento |
|---|---|---|
| cv-ai-engineer (Summary) | `C:\xampp\htdocs\enhanced-me\cv\CV_Washington_X_Quevedo_AI_Engineer_EN.pdf` | "shipped on the web and on the App Store and Google Play." |
| cv-ai-engineer (Experience, Stanford) | mismo PDF | "mAP50 0.96, box IoU 0.90 on validation" |
| cv-ai-engineer (Experience, Stanford) | mismo PDF | "adding letterboxing raised class accuracy from 66% to 93%." |
| cv-ai-engineer (Experience, Stanford) | mismo PDF | "and published the mobile app on the App Store and Google Play." |
| cv-xr-ai-engineer (Experience, Stanford) | `C:\xampp\htdocs\enhanced-me\cv\CV_Washington_X_Quevedo_XR_AI_Engineer_EN.pdf` | "letterboxing raised class accuracy from 66% to 93%." |
| cv-xr-ai-engineer (Experience, Stanford) | mismo PDF | "Delivered the web platform and published the mobile app on the App Store and Google Play." |
| linkedin-profile (About) | `C:\xampp\htdocs\enhanced-me\linkedin\LINKEDIN_EN.md`, sección 2 | "The app is live on the App Store and Google Play." |
| linkedin-profile (Experience, Stanford) | mismo archivo, sección 4 | "mAP50 0.96, box IoU 0.90 on validation" |
| linkedin-profile (Experience, Stanford) | mismo archivo, sección 4 | "letterboxing raised class accuracy from 66% to 93%" |
| linkedin-profile (Experience, Stanford) | mismo archivo, sección 4 | "app published on the App Store and Google Play" |

Ninguna fuente dentro del repo (papers, README de repos, código) contenía estas afirmaciones.

**Corrección:** mecanismo nuevo y mínimo `data/source_corrections.yaml` (10 entradas, cada una con documento, texto, reemplazo, motivo y ruta del original), aplicado en `app/ingestion.py` antes del hash. Reingesta solo de `cv` y `linkedin` (3 documentos actualizados, 43 chunks; el índice sigue en 132). En `data_chunks` quedan 0 fragmentos con esas afirmaciones. La pregunta q08 del set de evaluación ya no espera "66%" y "93%" (ahora "letterboxing" y "distort"); la evaluación de recuperación híbrida sigue igual (hit@3 1.000, MRR 0.981).

**Antes y después** (3 preguntas reales, Claude Haiku 5.5, costo total USD 0.0021):

| Pregunta | Antes | Después |
|---|---|---|
| Is Buscapez available on the App Store? | "Yes ... publishing the mobile app on the App Store and Google Play ... live on the App Store and Google Play." | "The sources state that the Buscapez mobile app is still in development and not yet published on the App Store or Google Play." |
| ¿Qué tan preciso es el detector de Buscapez? | "mAP50 de 0.96 y un IoU de caja de 0.90 ... elevó la precisión por clase del 66% al 93%." | "mAP50 0,96 en la fase de detección y validación ... no la clasificación de especies, que sigue mejorando a medida que se añaden fotos validadas." |
| What is Buscapez? | "... and published the mobile app on the App Store and Google Play." | "... achieved mAP50 0.96 on detection validation. The web platform has been delivered, while the mobile app is still in development." |

**Pendiente fuera de este repo:** corregir los originales (las 3 rutas de la tabla) y volver a copiarlos a `data/sources/`; la ingesta avisará qué correcciones dejaron de coincidir para borrarlas del YAML.

**Orígenes:** `deploy/.deploy.local` queda con `EMBED_ALLOWED_ORIGINS=https://washingtonquevedo.com,https://www.washingtonquevedo.com`; el `.env` local incluye además `http://localhost:4321`. `.deploy.local.example` y el README lo reflejan. Las pruebas de navegador aceptan `ASKW_E2E_DEV_PORT` para correr aunque el servidor de Astro ocupe el 4321.

**Pruebas:** 79 en la suite normal (2 nuevas del mecanismo de correcciones) y 14 en Playwright (con `ASKW_E2E_DEV_PORT=4399`).

### 2026-10-18 - P20c·2 redacción de reportes históricos

El repo ya es público, así que no se reescribe el historial: en un commit normal se reemplazó cada oración de los reportes que repetía las afirmaciones viejas sobre Buscapez (publicación en App Store o Google Play, "66%", "93%", "IoU 0.90") por "[redacted 2026-10-18: outdated claim, see PROJECT.md P20c]". Los JSON siguen siendo válidos y conservan su formato.

| Archivo | Ubicación | Fragmentos redactados |
|---|---|---:|
| `reports/eval/answers_after.json` | respuestas de q06, q07, q08 y keywords encontradas de q08 | 6 |
| `reports/eval/answers_before.json` | respuestas de q06, q07, q08, q22 y keywords encontradas de q08 | 7 |
| `reports/P18-3_real_answers.json` | respuesta de "Production ML experience" | 1 |
| `reports/P18-3_respuestas.md` | la misma respuesta citada en el reporte | 1 |
| `reports/P20_real_answers.json` | respuesta de "Buscapez" (interfaz ES) | 2 |

Quedan esas frases, a propósito, en `data/source_corrections.yaml` (el mecanismo necesita el texto literal para encontrarlo), en esta bitácora (P20c documenta qué estaba mal) y en `tests/test_ingestion.py` (frases de prueba del mecanismo). Las métricas guardadas en los JSON de evaluación no se recalcularon: son el registro de esas corridas.

### 2026-10-18 - P20d widget sin cabecera

En modo widget (`?embed=1`) la cabecera "Ask Washington" queda oculta a la vista, porque el panel del portafolio ya muestra ese título; el `h1` sigue disponible para lectores de pantalla y el subtítulo y los perfiles quedan fuera. La página completa mantiene su cabecera. Pruebas de Playwright ajustadas (cabecera oculta y hilo desde el borde superior del panel en el widget; cabecera visible en la página completa) y capturas del widget actualizadas en `reports/screenshots/p20b/`.

## Referencias de chats (P20b)

Revisadas el 2026-10-18 en un Chromium sin sesión (Playwright), solo páginas públicas; las capturas se guardaron fuera del repositorio. ChatGPT (verificación de Cloudflare), el Messenger de Intercom y Tidio no cargan en un navegador automatizado: de Intercom se usó su documentación y no se intentó saltar ninguna protección.

| Referencia | Qué se observó |
|---|---|
| Vercel AI Chatbot (template oficial, demo y código) | Hilo centrado y composer fijo abajo; 4 sugerencias solo con el hilo vacío, que se envían al hacer clic; mensaje del usuario a la derecha; Enter envía y Shift+Enter salta de línea (ignorado durante composición IME); caja que crece con el texto; botón de enviar con icono y `aria-label`; región `aria-live`; sin citas. |
| Perplexity | La mejor referencia de citas: marca pequeña al final de la frase y lista de fuentes bajo la respuesta (en 400 px, detrás de un botón "N sources"); indicador de progreso mientras investiga; preguntas relacionadas tras cada respuesta. Banners de inicio de sesión y sin aviso de exactitud visible. |
| Chatwoot (widget en vivo) | Panel flotante de 400 x 636 px abajo a la derecha, pantalla completa en celulares; saludo grande; formulario previo con email y nombre (a evitar); botones de icono sin etiqueta. |
| Intercom Messenger (documentación) | Respuestas de Fin con fuentes, citas y acciones sugeridas; etiqueta "AI Agent" y mensaje de presentación que aclara que es un agente de IA. |
| HuggingChat | Sugerencias sobre el composer; caja de una línea que crece; aviso "Generated content may be inaccurate or false." justo debajo del composer. |

**Patrones adoptados y por qué**

- Composer fijo abajo, caja que crece (aquí hasta 4 líneas), Enter / Shift+Enter, IME respetado y botón de icono con `aria-label` (Vercel, HuggingChat): es lo que la gente espera de un chat y funciona igual en 400 px.
- 4 preguntas sugeridas solo en el estado inicial, que se envían al hacer clic (Vercel, HuggingChat): enseñan qué se puede preguntar y llevan a la primera respuesta en un toque. Como chips en varias líneas, entran en 400 px.
- Citas en línea que llevan a una lista compacta de fuentes bajo la misma respuesta (Perplexity): ata cada afirmación a su evidencia, que es la razón de ser de Ask Washington; no hay espacio para una columna lateral.
- Indicador de espera mientras se recupera y se genera (Vercel, Perplexity): la respuesta tarda unos segundos y conviene mostrar que está trabajando.
- Aviso de posibles errores en letra pequeña bajo el composer (HuggingChat): siempre visible y sin ocupar espacio del hilo.
- Región `aria-live` en el hilo y botones de icono con etiqueta (Vercel, Perplexity; Chatwoot como contraejemplo).
- Panel de unos 400 x 600 px con alto fijo y solo el hilo desplazable (Chatwoot): coincide con el panel flotante del portafolio.
- Errores dentro del hilo, como mensaje del asistente, en vez de un aviso flotante (el toast de Vercel pasa desapercibido en un panel chico).

**Diferencias deliberadas**

- La respuesta va en burbuja de fondo neutro (pedido explícito), aunque Vercel y Perplexity usan texto sin burbuja.
- Las citas son superíndices `[n]` con número, no marcas con el dominio: las fuentes son pocas y propias (CV, LinkedIn, README, papers) y el número enlaza a la lista.

**No adoptado (por ahora)**

- Streaming y botón de detener: `/ask` responde de una vez; queda como mejora futura si se agrega streaming.
- Preguntas de seguimiento tras cada respuesta, botón "ir al final" al leer hacia arriba, copiar y pulgar arriba o abajo, botón de reintentar en los errores, etiqueta "AI" en la cabecera: útiles pero fuera del alcance de P20b.
- Formularios previos, inicio de sesión, historial guardado, barras laterales, selector de modelo, adjuntos y voz: no aportan a una consulta puntual de un reclutador y requieren cuentas o memoria.

## Próximos pasos

- Washington: redeploy con `deploy.ps1` (sube el índice corregido y los orígenes de producción) y verificar el panel del portafolio en https://washingtonquevedo.com.
- Corregir los originales de los CV y del LinkedIn (rutas en P20c) y borrar las entradas de `data/source_corrections.yaml` que la ingesta marque como ya no necesarias.
- Medir en el servidor el tamaño de la imagen, la RAM real del contenedor y la latencia de `/ask`.
- Publicar el repo en GitHub cuando el despliegue esté verificado.
- Volver a correr `scripts/eval.py` tras cada cambio y sumar preguntas reales de `qa_log`.

## Mejoras futuras

- **Proveedor local en la torre (Ollama):** constructor `ollama` en `app/llm.py` con `langchain-ollama`, para responder sin costo por token cuando la torre esté encendida.
- **Servicio de inferencia vía la API de Localia:** constructor `openai_compatible` con `langchain-openai` apuntando a la API de Localia, para reutilizar la plataforma propia.
- Rate limit en Postgres o Redis si la app corre con varios procesos.
- Chat: respuestas en streaming con botón de detener, preguntas de seguimiento tras cada respuesta, botón "ir al final", copiar y valorar respuestas, reintentar tras un error.
- Reranker (`RETRIEVAL_MODE=rerank`) si la inferencia corre con GPU en la torre: es el único que recupera q20.
