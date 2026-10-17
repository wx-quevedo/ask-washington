# Ask Washington - documento del proyecto

## Contexto

Ask Washington es un chat RAG para el portafolio de Washington X. Quevedo (AI Engineer, XR + AI Engineer). Un reclutador pregunta sobre su experiencia y el sistema responde citando las fuentes de Washington: CV, PROFILE.md, READMEs de sus repos públicos y resúmenes de sus papers.

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

## Plan de los 5 prompts

1. **P18·1 base**: entorno, Postgres con pgvector en contenedor, app FastAPI con `/health`, pruebas, ruff, documentos y primer commit.
2. **P18·2 ingesta**: cargar CV, PROFILE.md, READMEs y resúmenes de papers con LlamaIndex, generar embeddings con bge-small y guardarlos en pgvector.
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

## Próximos pasos

- P18·2: reunir los documentos fuente en `data/` y construir la ingesta con LlamaIndex.
- Decidir el tamaño de fragmento y los metadatos de cita (fuente, sección, URL).
- Elegir el modelo económico de Claude y definir los límites de uso y gasto antes de P18·3.
