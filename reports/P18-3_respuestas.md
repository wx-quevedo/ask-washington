# P18·3 - Reporte de respuestas

Fecha: 2026-10-17. Modelo: `claude-haiku-5-5` (Anthropic, vía `langchain-anthropic`), `max_tokens` 600, razonamiento desactivado, top_k 6. Precios usados: USD 0.10 / 0.50 por millón de tokens de entrada / salida.

## Resumen de la prueba real

| # | Pregunta | Ruta | Tokens entrada | Tokens salida | Costo USD | Latencia |
|---|---|---|---:|---:|---:|---:|
| 1 | What XR experience does Washington have? | rag | 1863 | 387 | 0.000380 | 12219 ms |
| 2 | What is his most cited paper? | ranking | 814 | 186 | 0.000174 | 1193 ms |
| 3 | Production ML experience | rag | 2619 | 298 | 0.000411 | 1730 ms |
| 4 | What is plan-vivo-kit? | rag | 3382 | 348 | 0.000512 | 1977 ms |
| 5 | ¿Qué hizo en rehabilitación con realidad virtual? | rag | 3135 | 447 | 0.000537 | 2364 ms |
| | **Total** | | **11813** | **1666** | **0.002014** | |

La latencia de la primera pregunta (12 s) incluye la carga en frío del modelo de embeddings; las demás tardan entre 1.2 y 2.4 s. El total coincide con la fila del día en `usage_daily` (5 solicitudes, USD 0.002014). Salida completa en `reports/P18-3_real_answers.json`.

## Las 5 respuestas

### 1. What XR experience does Washington have?

> Washington has about 10 years of experience building VR/AR training, simulation and interactive experiences in Unity [2]. He shipped XR and game work for a social VR platform (Sansar, via BairesDev), an AR company (Merge) and a pharmaceutical sales force [2]. He also founded Inmersoft in 2018, with 200+ delivered projects [2].
>
> Selected XR projects include:
> - A synchronized 360° VR experience for 31 Meta Quest headsets, with a guided meditation and a head-movement rhythm game [4].
> - SkyNest, a multiplayer VR combat sandbox in development with Unity 6 and Meta Quest [4].
> - RayNeo Power, a HUD for RayNeo Air 4 Pro AR glasses, in development [4].
> - Earlier work including a VR maze game (VR Runner), a DJI Matrice 600 Pro VR simulator, and a Unity3D–MATLAB robotics simulator [4].
>
> He has also published 30+ peer-reviewed papers in virtual reality [2]. For more detail, see his LinkedIn profile: https://www.linkedin.com/in/wxquevedo

Fuentes:

| n | Documento | Tipo | Sección | URL | Score |
|---|---|---|---|---|---|
| 1 | CV - XR + AI Engineer | cv | Overview | https://www.linkedin.com/in/wxquevedo | 0.618 |
| 2 | CV - XR + AI Engineer | cv | Summary | https://www.linkedin.com/in/wxquevedo | 0.575 |
| 3 | CV - AI Engineer | cv | Overview | https://www.linkedin.com/in/wxquevedo | 0.567 |
| 4 | CV - XR + AI Engineer | cv | Selected XR Projects | https://www.linkedin.com/in/wxquevedo | 0.555 |
| 5 | CV - XR + AI Engineer | cv | Earlier roles | https://www.linkedin.com/in/wxquevedo | 0.551 |
| 6 | CV - XR + AI Engineer | cv | Education | https://www.linkedin.com/in/wxquevedo | 0.550 |

### 2. What is his most cited paper?

> Washington's most cited paper is "Unity3D-MatLab simulator in real time for robotics applications" (2016), presented at the International Conference on Augmented Reality, Virtual Reality and Computer Graphics (AVR, Springer LNCS). It has 88 citations on Google Scholar, as of a 2026-10-17 snapshot [1].
>
> His next most cited papers are "Augmented reality as a new marketing strategy" (2018), with 55 citations [2], and "Virtual reality on e-Tourism" (2017), with 54 citations [3].

Fuentes:

| n | Documento | Tipo | Sección | URL | Score |
|---|---|---|---|---|---|
| 1 | Unity3D-MatLab simulator in real time for robotics applications | paper | Citations ranking | https://doi.org/10.1007/978-3-319-40621-3_19 | - |
| 2 | Augmented reality as a new marketing strategy | paper | Citations ranking | https://doi.org/10.1007/978-3-319-95270-3_29 | - |
| 3 | Virtual reality on e-Tourism | paper | Citations ranking | https://doi.org/10.1007/978-981-10-6454-8_13 | - |

### 3. Production ML experience

> Washington's sources describe several production ML projects:
>
> - **Buscapez (Stanford University marine research platform):** He is building the species-identification module, a YOLO detector trained in PyTorch (mAP50 0.96), served by a FastAPI + ONNX Runtime service at 49 ms per image on a 2-core VPS, and running offline on iOS and Android via ExecuTorch. The app is live on the App Store and Google Play [5].
> - **Laboratorios Bagó del Ecuador:** He built an AI campaign builder for product managers that generates campaign concepts grounded in expert product information, used at the company's MKT Attack event [4].
>
> His profile also lists LLM application work with Claude, OpenAI and Gemini APIs, and local LLM serving with llama.cpp [5].
>
> For more detail, see his LinkedIn profile: https://www.linkedin.com/in/wxquevedo

Fuentes:

| n | Documento | Tipo | Sección | URL | Score |
|---|---|---|---|---|---|
| 1 | Virtual training for industrial automation processes through pneumatic controls | paper | Abstract | https://doi.org/10.1007/978-3-319-95282-6_37 | 0.652 |
| 2 | Multi-user industrial training and education environment | paper | Abstract | https://doi.org/10.1007/978-3-319-95282-6_38 | 0.646 |
| 3 | Immersive industrial process environment from a P&ID diagram | paper | Abstract | https://doi.org/10.1007/978-3-319-50835-1_63 | 0.645 |
| 4 | CV - AI Engineer | cv | Experience > Laboratorios Bagó del Ecuador — Digital Solutions & AI Developer | https://www.linkedin.com/in/wxquevedo | 0.644 |
| 5 | LinkedIn profile | linkedin | About | https://www.linkedin.com/in/wxquevedo | 0.636 |
| 6 | Oil processes VR training | paper | Abstract | https://doi.org/10.1007/978-3-030-03801-4_62 | 0.635 |

### 4. What is plan-vivo-kit?

> Plan-vivo-kit, known as Plan Vivo, is a project plan kept in one JSON file (`plan.json`) that AI coding agents keep up to date, along with a local live viewer that shows phases, real time spent per actor, and a calibrated projection of when the work will finish [1]. It answers questions such as what is done, what is waiting on a human, how long each step really took compared to the estimate, and when the work will finish [2].
>
> The kit includes:
>
> - A plan format split into phases and items (`prompt`, `gate`, `unplanned`), described by a JSON Schema and a matching zod schema [2].
> - A localhost React viewer that reloads automatically when `plan.json` is saved, with a UI in Spanish and English [2].
> - A `tiempos` command that rebuilds time segments per actor from Claude Code session logs and `git log` [2].
> - Commands to validate and migrate plans, with `schema_version` for format versioning [2].
>
> Washington built it, and its repository is at github.com/wx-quevedo/plan-vivo-kit [6].

Fuentes:

| n | Documento | Tipo | Sección | URL | Score |
|---|---|---|---|---|---|
| 1 | GitHub repository plan-vivo-kit | repo_readme | Overview | https://github.com/wx-quevedo/plan-vivo-kit | 0.793 |
| 2 | GitHub repository plan-vivo-kit | repo_readme | What problem it solves | https://github.com/wx-quevedo/plan-vivo-kit | 0.760 |
| 3 | GitHub repository plan-vivo-kit | repo_readme | Architecture | https://github.com/wx-quevedo/plan-vivo-kit | 0.737 |
| 4 | GitHub repository plan-vivo-kit | repo_readme | What I learned / key technical decisions | https://github.com/wx-quevedo/plan-vivo-kit | 0.723 |
| 5 | GitHub repository plan-vivo-kit | repo_readme | Architecture | https://github.com/wx-quevedo/plan-vivo-kit | 0.721 |
| 6 | GitHub repository plan-vivo-kit | repo_readme | Running locally | https://github.com/wx-quevedo/plan-vivo-kit | 0.721 |

### 5. ¿Qué hizo en rehabilitación con realidad virtual?

> Washington trabajó en varios proyectos de rehabilitación con realidad virtual, principalmente para habilidades motoras de brazos y piernas. Por ejemplo:
>
> - Desarrolló un sistema no invasivo para rehabilitar habilidades motoras de extremidades superiores e inferiores, usando realidad aumentada para lesiones crónicas y realidad virtual para lesiones menores [1].
> - Creó un sistema de rehabilitación de motricidad fina de extremidades superiores con dispositivos hápticos, Unity3D, Novint Falcon, Oculus Rift y Leap Motion, basado en ejercicios de fisioterapeutas [2].
> - Diseñó un sistema de rehabilitación de motricidad fina que usa una ortesis activa de mano, con el brazalete Myo para identificar movimientos [4].
> - Construyó un guante de estimulación háptica para rehabilitación de motricidad fina en entornos de realidad virtual, con sensores de flexibilidad y actuadores vibratorios [5].
>
> Estos trabajos fueron publicados en conferencias como AVR (Springer LNCS) e ISVC [1][2][4][5]. Para más detalles, puede consultar su perfil de LinkedIn: https://www.linkedin.com/in/wxquevedo

Fuentes:

| n | Documento | Tipo | Sección | URL | Score |
|---|---|---|---|---|---|
| 1 | Assistance system for rehabilitation and valuation of motor skills | paper | Abstract | https://doi.org/10.1007/978-3-319-60928-7_14 | 0.689 |
| 2 | Virtual reality integration with force feedback in upper limb rehabilitation | paper | Abstract | https://doi.org/10.1007/978-3-319-50832-0_25 | 0.667 |
| 3 | Realism in audiovisual stimuli for phobias treatments through virtual environments | paper | Abstract | https://doi.org/10.1007/978-3-319-60928-7_16 | 0.665 |
| 4 | Virtual rehabilitation system for fine motor skills using a functional hand orthosis | paper | Abstract | https://doi.org/10.1007/978-3-319-95282-6_6 | 0.662 |
| 5 | Haptic stimulation glove for fine motor rehabilitation in virtual reality environments | paper | Abstract | https://doi.org/10.1007/978-3-319-95282-6_16 | 0.652 |
| 6 | Sales maximization based on neuro-marketing techniques in virtual environments | paper | Abstract | https://doi.org/10.1007/978-3-319-95282-6_13 | 0.631 |

## Lectura de las respuestas

- **Las 5 responden con fuentes reales y citas `[n]` que corresponden a las fuentes devueltas.** Ninguna inventa datos de contacto ni habla en primera persona.
- **Ruta de ranking:** "What is his most cited paper?" fue detectada como ranking; los hechos (p01, 88 citas; p02, 55; p03, 54) se calcularon desde `data/papers.yaml` sin LLM, y el modelo solo los redactó con el DOI de cada paper. Es también la más barata (814 tokens de entrada), porque no envía chunks.
- **"Production ML experience" mejoró respecto a P18·2:** la búsqueda sola no ponía Stanford/Buscapez en el top 3, pero con top_k 6 entran el chunk de LinkedIn "About" (puesto 5) y el de Bagó (puesto 4), y el modelo descartó los papers de entrenamiento industrial, que no responden la pregunta.
- **Idioma:** la pregunta en español se respondió en español, con fuentes en inglés.
- **Detalles a ajustar:** el modelo agrega la sugerencia de LinkedIn incluso cuando la respuesta es completa (la regla dice hacerlo solo si falta información), y en la respuesta 4 cita [6] ("Running locally") para "Washington built it", una fuente floja para esa frase. Quedan para medir en P18·4.

## Costo total de la prueba

5 preguntas: 11 813 tokens de entrada y 1 666 de salida, **USD 0.002014** (unos USD 0.0004 por respuesta). Con el tope por defecto de USD 1.00 diarios caben unas 2 500 respuestas por día; el rate limit por IP (100 por día) se alcanza mucho antes.

Además, se hizo una llamada mínima de validación de parámetros antes de escribir la cadena (16 tokens de entrada y 4 de salida, menos de USD 0.00001).

## p03 / p22

Las dos páginas del editor se revisaron directamente:

- **p03** (Springer, https://link.springer.com/chapter/10.1007/978-981-10-6454-8_13): el abstract empieza "This article proposes the develop of a dynamic virtual environment that with the consumption of real time data about the state of a place, offer an immersion to the tourist..." y coincide con el del archivo.
- **p22** (ACM, https://dl.acm.org/doi/10.1145/3175536.3176651): muestra el mismo abstract palabra por palabra. Crossref no tiene abstract para ninguno de los dos DOI, ni la negociación de contenido de doi.org para p22.

No existe un abstract distinto para p22 en ninguna fuente permitida. El texto describe una app de VR (inmersión en un lugar, datos ambientales y del clima en tiempo real, Google Maps, HTC VIVE y Oculus) y no menciona marketing, así que encaja con "Virtual reality on e-Tourism" (p03). **Se conservó en p03 y se dejó vacío en p22**, con la explicación en `notes` de ambos. Lo más probable es que los autores reutilizaran el abstract en las dos publicaciones.

Re-ingesta con `uv run python -m scripts.ingest --only paper`: 25 documentos, 1 actualizado (p22, ahora con título, venue, año y citas, sección `Metadata`), 24 sin cambios. El índice sigue en 25 chunks de papers.

## Decisiones tomadas

| Decisión | Por qué |
|---|---|
| `temperature` no se envía (se pidió 0.2) | Claude Haiku 5.5 rechaza con un 400 cualquier valor de muestreo distinto del predeterminado. `LLM_TEMPERATURE` vacío significa "no enviar"; se puede fijar para otros modelos. |
| Razonamiento desactivado (`thinking: disabled`) | Haiku 5.5 lo trae activado por defecto y sus tokens cuentan contra `max_tokens` (600) y el gasto. |
| Precio por defecto USD 0.10 / 0.50 por millón | Precio de lista de Claude Haiku 5.5 (prompts de hasta 100K tokens). Configurable por env si cambia el modelo. |
| Ruta de ranking por expresiones regulares (inglés y español) | Determinista, gratis y testeable. Cubre más citado, más reciente, cuántos papers y métricas (citas totales, h-index, i10). Una pregunta de ranking no consulta el índice vectorial. |
| `score: null` en las fuentes de la ruta de ranking | Son hechos calculados, no resultados de similitud. |
| Retriever de LangChain sobre el `PGVectorStore` de LlamaIndex | Reutiliza la tabla, el modelo de embeddings y la instrucción de consulta de P18·2. |
| Pregunta entre `<question>` y fuentes numeradas entre `<sources>` | Separa la entrada no confiable de las instrucciones. |
| Rate limit en memoria (slowapi), gasto en Postgres | El rate limit basta para un proceso; el gasto debe sobrevivir reinicios. |
| IP como hash SHA-256 con sal (16 caracteres) en `qa_log` | Permite agrupar abusos sin guardar la IP. |
| Errores del proveedor: 502 genérico y detalle solo en el log | No expone mensajes internos ni configuración. |
| Pruebas con `GenericFakeChatModel` y retriever falso, día fijo 1999-01-01 | No gastan API y no tocan los contadores reales; borran sus filas al terminar. |

## Problemas encontrados

- `LLM_TEMPERATURE=` vacío en `.env.example` fallaba la validación de pydantic; se agregó un validador que lo convierte en "no enviar", con su prueba.
- ruff marcaba `Depends(...)` en los argumentos (B008); se declaró `fastapi.Depends` como llamada inmutable, que es el patrón de FastAPI.
- Detrás de un proxy (VPS), el rate limit vería la IP del proxy; hay que leer `X-Forwarded-For` en P18·5.
