# P18·5 - Reporte de interfaz y despliegue

Fecha: 2026-10-17. Todo se validó en local; no se ejecutó nada contra el VPS. El despliegue lo corre Washington con los comandos del final.

## Interfaz

`GET /` sirve una página sola (`app/static/index.html`, `styles.css`, `app.js`), sin framework ni build: título y subtítulo, 4 preguntas sugeridas clicables, caja de pregunta con contador, respuesta con `[n]` enlazados a la lista de fuentes (título, tipo y enlace público), estados de carga y error (429 con el mensaje del servidor), pie con LinkedIn, GitHub y Google Scholar y la nota "Answers are generated from public sources and may contain errors."

- Accesibilidad: `label` en la caja, enlace para saltar al formulario, foco visible, `aria-live` y `aria-busy` en el resultado, el foco pasa al resultado al terminar, contraste alto, animación desactivada con `prefers-reduced-motion`.
- Seguridad: el texto del modelo se inserta solo con `textContent` (negritas, `código` y citas se crean como elementos), sin `innerHTML` ni scripts inline, así que funciona con la CSP estricta de nginx.
- Revisión con Playwright: sin errores de consola en escritorio ni en móvil, sin desplazamiento horizontal en 390 px, fuente mínima de 12 px, las 8 citas de la respuesta apuntan a fuentes que existen.

Capturas (Playwright, Chromium):

| Archivo | Vista |
|---|---|
| `reports/screenshots/desktop-initial.png` | Escritorio 1280x900, página inicial |
| `reports/screenshots/desktop-answer.png` | Escritorio, respuesta a "What is plan-vivo-kit?" con 6 fuentes |
| `reports/screenshots/desktop-error.png` | Escritorio, validación en el cliente ("hi", sin llamar a la API) |
| `reports/screenshots/mobile-initial.png` | Móvil 390x844 a 2x, página inicial |
| `reports/screenshots/mobile-answer.png` | Móvil, la misma respuesta (se reutilizó la respuesta de escritorio: una sola llamada al LLM) |

Las capturas costaron 2 llamadas al LLM (la primera tanda y la repetición tras corregir dos detalles visuales: los backticks se mostraban literales y la etiqueta "GitHub repository" repetía el título; ahora se renderizan como código y la etiqueta dice "README"), unos USD 0.0008.

## Reranker liviano (`rerank_light`)

`RETRIEVAL_MODE=rerank_light`: candidatos híbridos (20) reordenados por `cross-encoder/ms-marco-MiniLM-L-6-v2`, quedan 6. `uv run python -m scripts.eval --modes vector,hybrid,rerank_light` (solo recuperación, sin LLM; salida en `reports/eval/retrieval_p18-5.*`):

| Configuración | hit@3 | hit@6 | MRR | kw@6 | Latencia media | Latencia p95 | Faltan keywords en el top 6 |
|---|---:|---:|---:|---:|---:|---:|---|
| vector | 0.889 | 1.000 | 0.914 | 0.981 | 28 ms | 35 ms | q20 |
| **hybrid (por defecto)** | **1.000** | **1.000** | **0.981** | **0.981** | **63 ms** | **100 ms** | q20 |
| rerank_light | 1.000 | 1.000 | 0.963 | 0.981 | 779 ms | 972 ms | q20 |

Criterio: acertar q20 sin bajar hit@3 ni MRR y quedar bajo 250 ms. `rerank_light` no cumple ninguna de las tres condiciones (q20 sigue fuera, el MRR baja, 779 ms), así que **queda `hybrid` por defecto**. `rerank_light` sigue disponible por env.

## Producción

| Pieza | Detalle |
|---|---|
| `Dockerfile` | Multi-stage sobre `python:3.12-slim` con uv 0.11.32; `uv sync --frozen --no-dev`; torch 2.14.1+cpu (índice de PyTorch CPU, sin paquetes NVIDIA en el lock); `bge-small-en-v1.5` descargado en el build (`HF_HUB_OFFLINE=1` en tiempo de ejecución; rerankers opcionales con `--build-arg RERANKER_MODELS=...`); usuario `app` (uid 10001); `HEALTHCHECK` a `/health`; uvicorn con `--proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"`. |
| `docker-compose.prod.yml` | Proyecto `ask-washington`; `app` en `127.0.0.1:${APP_PORT:-8710}:8000`; `db` `pgvector/pgvector:pg16` sin puertos; volumen `pgdata` y red `internal` propios (Compose los prefija con `ask-washington_`); `restart: unless-stopped`; `mem_limit` 1536m (app) y 512m (db). |
| IP real | `ProxyHeadersMiddleware` dentro de la app con `FORWARDED_ALLOW_IPS` (por defecto `127.0.0.1`; en producción `127.0.0.1,172.16.0.0/12,192.168.0.0/16`, porque nginx llega al contenedor por el gateway del bridge de Docker). Solo esos pares pueden fijar `X-Forwarded-For`; se toma la IP de más a la derecha que no sea de confianza. nginx sobrescribe la cabecera con `$remote_addr`. La app solo escucha en el loopback del host, así que nadie más alcanza el contenedor. |
| nginx | `deploy/nginx/ask.inmersoft.com.conf`: `server_name ask.inmersoft.com`, proxy a `127.0.0.1:8710`, `X-Forwarded-For/Proto/Host` y `X-Real-IP`, `client_max_body_size 16k`, timeouts, CSP, `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`. certbot agrega HTTPS y la redirección. |

**Puerto elegido: 8710** (configurable con `APP_PORT` en `deploy/.deploy.local`). No conozco los puertos ocupados del VPS; el deploy verifica con `ss` y `docker ps` que esté libre o que sea de este mismo proyecto, y si no, aborta sin cambiar nada.

**Tamaño de la imagen: no medido.** El build local con Podman no pudo empezar: la máquina de Podman volvió a quedar sin `/etc/resolv.conf` (el mismo problema de P18·1) y no resuelve DNS (`lookup registry-1.docker.io: Temporary failure in name resolution`), aunque la conectividad IP funciona. No restauré el enlace porque es un cambio en la máquina que antes no tuve permiso de hacer. Se mide en el servidor con `sudo docker image ls ask-washington-app` después del deploy, o en local tras arreglar la máquina con `podman machine ssh "sudo ln -sf /mnt/wsl/resolv.conf /etc/resolv.conf"` y `podman build -t ask-washington-app:local .`.

## Datos en el servidor

`deploy.ps1` vuelca solo `data_chunks` (132 chunks con embeddings, índices HNSW y de texto completo) e `ingested_documents` (34 documentos) con `pg_dump -Fc` desde el contenedor local, a un directorio temporal fuera del repo que se borra al terminar. `data/sources` nunca sale de la máquina. `usage_daily` y `qa_log` las crea la app al arrancar.

Validación local: el volcado se restauró dos veces seguidas con `pg_restore --clean --if-exists --no-owner` en una base de prueba (`askw_restore_test`, borrada después): 132 chunks de 34 documentos, 34 filas de seguimiento y los 4 índices (`data_chunks_pkey`, `chunks_idx_1`, `data_chunks_embedding_idx`, `data_chunks_fts_idx`) en ambas pasadas.

## Scripts de despliegue

- `deploy/deploy.ps1`: lee `DEPLOY_HOST` (y `APP_PORT`, `LOCAL_DB_CONTAINER`) de `deploy/.deploy.local`; genera una vez `POSTGRES_PASSWORD` e `IP_HASH_SALT` y los guarda ahí; lee `ANTHROPIC_API_KEY` del `.env` local sin imprimirla; exige un árbol limpio (o `-AllowDirty`); empaqueta `HEAD` con `git archive`; vuelca la base; escribe `env.production` (16 variables); sube 4 archivos con `scp` a `~/ask-washington-deploy` (modo 700); corre `remote-deploy.sh` con `ssh -t`; al final hace `GET https://ask.inmersoft.com/health`. `-DryRun` hace todo lo local y no envía nada. `-ForceNginx` reemplaza el sitio nginx.
- `deploy/remote-deploy.sh`: `sudo -v` una vez (con un proceso que mantiene vivo el permiso durante el build); verifica el puerto y que ningún otro sitio habilitado use `ask.inmersoft.com`; extrae en `/var/www/ask-washington`; instala `.env` con modo 600 y dueño root; `docker compose -p ask-washington ... up -d --build --remove-orphans`; espera `/health`; restaura el dump y reinicia la app; instala el sitio nginx solo si no existe (o con `-ForceNginx`, con copia de respaldo) y el enlace en `sites-enabled`; `nginx -t` y solo si pasa `systemctl reload nginx` (si falla, quita el enlace, restaura el archivo anterior y aborta sin recargar); `certbot --nginx -d ask.inmersoft.com --non-interactive --agree-tos --redirect --keep-until-expiring -m waxshoxp@gmail.com`; borra el staging (incluido el `.env` y el dump) al salir, también si falla.
- `deploy/rollback.ps1`: `docker compose -p ask-washington down` (el volumen se conserva salvo `-Purge`), quita solo `/etc/nginx/sites-enabled/ask.inmersoft.com`, `nginx -t` y recarga solo si pasa.

Validación local sin tocar el VPS:

| Prueba | Resultado |
|---|---|
| Parser de PowerShell sobre `deploy.ps1`, `rollback.ps1`, `dev-db-host.ps1` | 0 errores |
| `bash -n deploy/remote-deploy.sh` | OK |
| shellcheck 0.11.0 (vía `shellcheck-py`) | Limpio (un aviso informativo SC2024 revisado y documentado en el script) |
| `deploy.ps1 -DryRun` con un `.deploy.local` ficticio, desde HEAD limpio | OK: `app.tar.gz` 1.0 MB (incluye las capturas; `.dockerignore` las deja fuera de la imagen), `data.dump` 328 KB, `env.production` 533 bytes, `remote-deploy.sh` tomado de HEAD; directorio temporal borrado |
| `deploy.ps1 -DryRun` con cambios sin commitear | Se detiene con el mensaje de árbol sucio |
| Contenido de `git archive HEAD` | Sin `data/sources`, `.env` ni `.deploy.local`; finales de línea LF en `remote-deploy.sh`, `Dockerfile`, compose y código (0 bytes CR) |
| `podman compose -p ask-washington -f docker-compose.prod.yml config` con `.env` ficticio | Válido: puertos, límites y red como se esperaba |
| `pg_dump` + `pg_restore` dos veces en base de prueba | OK, idempotente |
| Build de la imagen con Podman | No viable hoy (DNS de la máquina de Podman, ver arriba) |

Dos problemas encontrados y corregidos en la validación:

1. Con `core.autocrlf=true` (la configuración de Git for Windows en esta máquina), `git archive` entregaba los archivos con CRLF: `remote-deploy.sh`, el `Dockerfile` y el compose habrían llegado al servidor con CRLF, que rompe bash y las continuaciones de línea. Se agregó `.gitattributes` (`* text=auto eol=lf`, CRLF solo en `.ps1`) y `deploy.ps1` llama a `git -c core.autocrlf=false archive`. Verificado contando bytes CR dentro del tar: 0.
2. En Windows PowerShell 5.1, con `$ErrorActionPreference = "Stop"`, cualquier línea que un programa nativo escribe en stderr se vuelve un error fatal (`ssh -t` imprime "Connection to ... closed" ahí, así que el deploy habría fallado aun saliendo bien). Las llamadas nativas ahora se juzgan por su código de salida.

## Revisión de secretos

Herramientas: gitleaks 8.30.1 (ya instalado) sobre los 5 commits, y una búsqueda propia con expresiones regulares sobre `git log -p --all`, los metadatos de los commits y el árbol de trabajo. El valor real de `ANTHROPIC_API_KEY` se buscó completo y por fragmentos en el texto de los parches y en los 143 objetos de git, sin imprimirlo.

**Veredicto: limpio.** gitleaks: "no leaks found". Ningún hallazgo requiere reescribir historial.

| Hallazgo | Dónde | Evaluación |
|---|---|---|
| Clave de Anthropic | En ninguna parte (0 coincidencias) | `.env` nunca se commiteó; `.env.example` tiene la clave vacía. |
| IP o usuario del VPS | En ninguna parte | No hay IPs públicas, `user@host`, ni destinos `ssh`/`scp` reales. Las cifras con puntos de `uv.lock` son versiones de paquetes. |
| Email del autor `waxshoxp@gmail.com` | Metadatos de los 5 commits | Intencional. |
| `wxquevedo@inmersoft.com` o teléfonos reales | En ninguna parte | Los CV no se commitearon nunca. |
| Cadenas `@inmersoft` y `+593` | `reports/P18-2_ingesta.md` (commit 2751f32) | Es la nota que dice que se quitaron email y teléfono; no es un dato de contacto, aunque revela el dominio del correo (que es público: `ask.inmersoft.com`). |
| `me@example.com`, `+593 98 000 0000` | `tests/test_ingestion.py` (2751f32) | Datos de prueba ficticios. |
| Credenciales de desarrollo `askw` / `askw_dev` | `.env.example`, `docker-compose.yml`, `app/config.py` | Solo para desarrollo local; producción usa una contraseña generada. |
| `172.29.23.4` | `PROJECT.md` (5e778cf, 0a5b624) | IP privada de la VM de Podman/WSL; inofensiva. |
| Contraseñas de ejemplo (`secret123`, etc.) | `.agents/skills/*/SKILL.md` (5e778cf) | Ejemplos de documentación de skills de terceros. |

`deploy/.deploy.local` se agregó a `.gitignore` antes de crear cualquier archivo con ese nombre (`git check-ignore` lo confirma).

## Comandos para Washington

Desde PowerShell en `C:\xampp\htdocs\ask-washington`. Requisitos: acceso SSH al VPS (con clave SSH se evitan 3 contraseñas de SSH; la de sudo se pide una vez), el contenedor local `ask-washington-db` corriendo (de ahí sale el volcado) y el commit de P18·5 hecho (deploy empaqueta `HEAD`).

```powershell
# 1. Configuración local, una sola vez (archivo ignorado por git)
Copy-Item deploy\.deploy.local.example deploy\.deploy.local
notepad deploy\.deploy.local        # DEPLOY_HOST=usuario@host real; APP_PORT=8710 salvo que esté ocupado

# 2. Comprobar que la base local está arriba
podman ps --filter name=ask-washington-db

# 3. Ensayo local: genera paquete, dump y .env, y no envía nada
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -DryRun

# 4. Despliegue (pide la contraseña de sudo una vez; el build tarda varios minutos en 2 CPU)
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1

# 5. Verificación
curl.exe -s https://ask.inmersoft.com/health
start https://ask.inmersoft.com

# Si algo sale mal: bajar solo Ask Washington y su sitio nginx (los datos se conservan)
powershell -ExecutionPolicy Bypass -File deploy\rollback.ps1
```

En el servidor, después del primer deploy, conviene anotar el tamaño de la imagen y el consumo real:

```bash
sudo docker image ls ask-washington-app
sudo docker stats --no-stream ask-washington-app-1 ask-washington-db-1
```

## Pendientes y avisos

- **Proceso local sobrante:** un uvicorn que arranqué en P18·3 sigue escuchando en el puerto 8000 (PID 70440, con su padre 13564) y sirve el código de esa versión. No tuve permiso para detenerlo; se puede cerrar con `Stop-Process -Id 70440,13564`.
- **Podman local sin DNS:** falta `/etc/resolv.conf` en la máquina de Podman (comando de arreglo arriba). No afecta al deploy, que construye la imagen en el servidor.
- Después de certbot, el sitio nginx queda gestionado por certbot; los redeploys no lo sobrescriben salvo `-ForceNginx`.
- `/docs` de FastAPI no carga en producción por la CSP (usa un CDN); se usa en local.
