# P20 - Reporte de idioma en Ask Washington

Fecha: 2026-10-18. Todo verificado en local; no se tocó el VPS.

## Reglas implementadas

- **Idioma de la interfaz:** `?lang=en|es`; sin parámetro, o con un valor desconocido, inglés. Ask Washington no tiene selector propio: cuando está incrustado, el portafolio puede cambiarlo en caliente con `postMessage({type: "ask-washington:lang", lang: "es"})`, aceptado solo desde `EMBED_ALLOWED_ORIGINS` (vacía por defecto).
- **Idioma de la respuesta:** el de la interfaz, que el frontend envía como `lang` en `POST /ask` (opcional, `en` por defecto). Si la pregunta está claramente en el otro idioma, se responde en el de la pregunta; si es ambigua (un nombre propio, una sigla), en el de la interfaz. Vale también para la ruta de ranking y para los mensajes de error.

## Cambios

| Área | Cambio |
|---|---|
| Textos | `app/static/i18n/en.json` y `es.json` (36 claves, español latino neutro): título de la página, descripción, título, subtítulo, 4 preguntas sugeridas, etiqueta, placeholder, ayuda, contador, botón, etiquetas de respuesta y fuentes, carga, "respondido en", tipos de fuente, errores, pie y aviso. |
| Página | `app/static/index.html` es una plantilla: cada texto visible es `{{clave}}` y lleva `data-i18n` (o `data-i18n-attr` para `placeholder`, `content` y `aria-label`). El servidor la rellena con el idioma pedido (`app/i18n.py`, escapando HTML), con `<html lang>` y `<title>` del idioma. El primer render no depende de JS. |
| JS | `app/static/app.js` no contiene textos visibles: carga el JSON del idioma activo, aplica los textos (también a una respuesta ya mostrada), envía `{question, lang}` a `POST /ask?lang=...`, escucha `ask-washington:lang` solo de orígenes permitidos y, en modo widget, publica `ask-washington:height` solo hacia esos orígenes. |
| Widget | `?embed=1`: clase `embed` en `<body>`; sin encabezado ni pie, márgenes y tarjetas compactos, fondo claro; el alto se informa con un `ResizeObserver`. |
| Backend | `POST /ask` acepta `lang`; `app/i18n.py` decide el idioma de la respuesta con un detector determinista (signos `¿` `¡`, palabras frecuentes de cada idioma y acentos); el system prompt recibe "Write the whole answer in {Spanish/English}. The page is shown in {...}". La respuesta incluye `"lang"`. |
| Errores de la API | 422 (validación), 429 (rate limit y presupuesto) y 502 salen en el idioma pedido. Para 422 y el 429 del rate limit el idioma se toma del `lang` del cuerpo o de `?lang=`; para el presupuesto y el 502, del idioma resuelto de la respuesta. |
| Cabeceras | La app envía `Content-Security-Policy` completa con `frame-ancestors 'self'` más los orígenes de `EMBED_ALLOWED_ORIGINS` (validados: solo `http(s)://host[:puerto]`). Sin orígenes permitidos, también `X-Frame-Options: SAMEORIGIN`; con orígenes, no (no admite listas). `/docs` queda fuera de la CSP. |

## Iframe y nginx: qué cambia en el servidor

Antes, el sitio nginx enviaba `X-Frame-Options: DENY` y una CSP con `frame-ancestors 'none'`. Cualquiera de los dos impide incrustar el widget, y una segunda CSP de nginx se aplicaría además de la de la app. Por eso:

- `deploy/nginx/ask.inmersoft.com.conf` ya no envía esas dos cabeceras (las demás se mantienen).
- El sitio del VPS es el que certbot modificó, y el deploy no lo sobrescribe salvo con `-ForceNginx`. Para no perder las líneas de certbot, `deploy/remote-deploy.sh` ahora quita solo las líneas `add_header X-Frame-Options ...` y `add_header Content-Security-Policy ...` del sitio existente: hace una copia de respaldo, corre `nginx -t` y recarga solo si pasa; si falla, restaura la copia y aborta sin recargar.
- Probado contra una copia simulada de un sitio gestionado por certbot: se borran exactamente esas 2 líneas, se conservan las 6 líneas "managed by Certbot" y una segunda pasada no cambia nada.

**El redeploy no necesita `-ForceNginx`.** `-ForceNginx` reemplazaría el archivo por la plantilla y dependería de que certbot lo reinstale; la migración puntual es más segura.

`EMBED_ALLOWED_ORIGINS` se pasa al `.env` de producción desde `deploy/.deploy.local` (clave nueva, vacía en el ejemplo). Mientras esté vacía, ningún otro sitio puede incrustar el widget, que es lo correcto hasta que exista el dominio del portafolio.

## Pruebas

Suite normal (`uv run pytest`): **74 aprobadas, 1 omitida** (la de JS, cuando Playwright no está instalado). Nuevas en `tests/test_i18n.py` (31 casos, LLM simulado):

- `en.json` y `es.json` tienen las mismas claves y ningún emoji; la plantilla no tiene texto visible fuera de los marcadores; el JS no contiene los textos en inglés.
- `/`, `?lang=en`, `?lang=es` y `?lang=fr`: `lang` del `<html>`, subtítulo, sugerencia y placeholder del idioma correcto, sin textos del otro.
- `?embed=1` agrega la clase `embed`.
- `frame-ancestors` sin orígenes (`'self'` y `X-Frame-Options: SAMEORIGIN`) y con orígenes (lista validada, sin `X-Frame-Options`, la misma lista en la meta etiqueta; los valores inválidos se descartan).
- Detector de idioma: inglés, español con y sin `¿`, y casos ambiguos ("Buscapez", "XR", "Production ML experience").
- La instrucción enviada al modelo: `lang` por defecto `en`; interfaz `es` con pregunta en español; **interfaz `en` con pregunta en español -> "Write the whole answer in Spanish."**; interfaz `es` con pregunta en inglés -> inglés; "Buscapez" sigue a la interfaz; `lang=de` -> inglés.
- Ruta de ranking en español ("¿Cuál es su artículo más citado?") -> instrucción en español y p01 con 88 citas.
- Errores localizados: 422 (por cuerpo y por `?lang=`), 429 de rate limit, 429 de presupuesto (según el idioma de la pregunta) y 502.

Prueba de JS (`tests/e2e/test_embed_postmessage.py`, Playwright; `uv run --with playwright pytest tests/e2e`): **3 aprobadas**.

1. Padre en un origen permitido: el mensaje `ask-washington:lang` cambia el iframe a `lang="es"` y "Tu pregunta", y el padre recibe mensajes `ask-washington:height` con alto positivo.
2. Padre en un origen no permitido, con las cabeceras reales: el navegador no muestra el iframe (`frame-ancestors`) y no llega ningún mensaje de alto.
3. Padre en un origen no permitido, quitando la CSP solo en el navegador de prueba para aislar el filtro del JS: el mensaje de idioma se ignora (sigue en inglés) y no llega ningún mensaje de alto.

## Prueba real (servidor local, Claude Haiku 5.5)

| Interfaz | Pregunta | Idioma de la respuesta | Citas | Costo |
|---|---|---|---|---:|
| EN | What XR experience does Washington have? | inglés (`lang: en`) | [2], [3], [5], válidas | USD 0.000350 |
| EN | ¿Qué hizo en rehabilitación con realidad virtual? | español (`lang: es`) | [1], [3], [5], válidas | USD 0.000487 |
| ES | ¿Qué es plan-vivo-kit? | español (`lang: es`) | [1], [3], [4], válidas | USD 0.000496 |
| ES | Buscapez (ambigua) | español (`lang: es`) | [1], [2], [3], válidas | USD 0.000485 |
| | **Total** | 4 de 4 en el idioma esperado | | **USD 0.001818** |

La primera respuesta tardó 17 s porque incluye la carga en frío del modelo de embeddings; las otras, unos 2 s. Respuestas completas en `reports/P20_real_answers.json`. Ejemplo (interfaz EN, pregunta en español): "Washington trabajó en varios sistemas de rehabilitación con realidad virtual para motricidad fina: ...".

## Capturas

En `reports/screenshots/` (Playwright, Chromium, estado inicial, sin llamadas al LLM; sin errores de consola en ninguna):

| Archivo | Vista |
|---|---|
| `page-en-desktop.png`, `page-es-desktop.png` | Página completa, 1280x900 |
| `page-en-mobile.png`, `page-es-mobile.png` | Página completa, 390x844 a 2x |
| `widget-en-desktop.png`, `widget-es-desktop.png` | Widget (`?embed=1`) en un iframe de 420 px dentro de una página de demo en otro origen permitido; el alto del iframe sale de los mensajes `ask-washington:height` |
| `widget-en-mobile.png`, `widget-es-mobile.png` | La misma página de demo a 390x844, iframe al 100% |

Revisión: todos los textos cambian de idioma (encabezado, sugerencias, etiqueta, placeholder, ayuda, botón, pie y aviso); en el widget no hay encabezado ni pie; sin desplazamiento horizontal en móvil; el iframe toma el alto del contenido sin barra interna. Observaciones menores: en móvil y en el widget el contador "0 / 500" baja a su propia línea; al cargar, el widget envía dos mensajes de alto (difieren unos 21 px mientras se rellena el contador) y luego queda estable.

## Decisiones

| Decisión | Por qué |
|---|---|
| El servidor rellena la plantilla con el JSON; el JS reutiliza el mismo JSON | Primer render sin parpadeo y sin depender de JS; una sola fuente de textos. |
| Detector de idioma determinista en el backend | Las reglas quedan comprobables y el modelo recibe una instrucción explícita en vez de adivinar. Ante la duda (pocas palabras, nombres), manda la interfaz. |
| CSP y `X-Frame-Options` en la app | Dependen de `EMBED_ALLOWED_ORIGINS`; dos CSP se aplican juntas, así que nginx no debe enviar la suya. |
| Mensajes `postMessage` con origen explícito y filtro por `event.origin` | El widget solo escucha y solo publica hacia los orígenes configurados. |
| Widget sin pie | Lo pide el diseño; el README recomienda que la página que lo incrusta muestre el aviso de posibles errores. |

## Redeploy

```powershell
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1
```

Sin `-ForceNginx`. El script quita del sitio nginx solo las dos cabeceras que ahora envía la app, conserva las líneas de certbot y termina con la prueba de humo de `POST /ask`. Para permitir el portafolio cuando tenga dominio: `EMBED_ALLOWED_ORIGINS=https://<dominio del portafolio>` en `deploy/.deploy.local` y volver a correr el mismo comando.
