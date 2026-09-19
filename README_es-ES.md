# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — Entrena a tu IA · Crece con tu IA · Donde la IA y los humanos crecen juntos" width="100%" />

**Un coach de programación a largo plazo que vive en la barra lateral de tu VS Code.**

**Planifica, entrena, verifica y lo recuerda todo sobre ti — pero nunca escribe tu código.**

**// Output ≠ Crecimiento // Verificar + Repasar = Crecimiento**

[English](README.md) · [简体中文](README_zh-CN.md) · Español · [Français](README_fr-FR.md) · [Deutsch](README_de-DE.md) · [日本語](README_ja-JP.md) · [한국어](README_ko-KR.md) · [Português](README_pt-BR.md)

[![Versión](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![Licencia](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Plataformas](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#instalación)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#compuertas-de-calidad)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--ocho-idiomas)

[Por qué](#por-qué-existe-trainer) ·
[Instalación](#instalación) ·
[Configuración](#tres-pasos-sin-cuarto) ·
[Mecánicas](#mecánicas-centrales) ·
[Cinco vistas](#cinco-vistas) ·
[Comparativa](#comparativa) ·
[Demo de 5 min](#demo-de-cinco-minutos) ·
[Diseño](#por-qué-se-siente-distinto) ·
[Arquitectura](#arquitectura) ·
[Seguridad](#modelo-de-seguridad) ·
[Calidad](#compuertas-de-calidad) ·
[Agradecimientos](#agradecimientos) ·
[🎭 El reparto](docs/CAST.md)

</div>

---

## Por qué existe Trainer

> Los desarrolladores no se atascan por falta de tutoriales.
> Se atascan porque nada cierra el bucle de aprendizaje.

Una charla con un LLM se evapora en cuanto termina; los vídeos son pasivos; el concepto que casi entendiste el martes ya se esfumó el viernes.

Peor aún: **vibe coding** — dejar que la IA escriba código durante tres meses sin que entiendas nada.

Los marcadores se acumulan mientras el output se queda plano. Los repos crecen mientras tu mente se vacía.

**Trainer lo resuelve desde dentro del editor.**

No es una carcasa de chat — es un coach con memoria, un temario y una política de exámenes:

- **Planifica** tu aprendizaje en etapas y registra dónde estás de verdad — no dónde crees que estás
- Te **entrena** con flash cards, ejercicios de teoría y experimentos de escenario
- **Verifica** el dominio contra tu código real — hablar de FastAPI no cuenta nada hasta que el archivo actual lo demuestre
- Te **recuerda** entre sesiones, proyectos y semanas, programando repasos sobre la curva de olvido de FSRS
- **Nunca escribe código de producción por ti** — tú escribes, él enseña, **crecéis juntos**

<div align="center">

| vibe coding · la norma de hoy | Trainer · cómo debería ser |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# ¿lo entendiste?` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| output = olvido | output + memoria + repaso = crecimiento |

</div>

---

## Instalación

**Desde VSIX (precompilado, tres plataformas):**

Descarga el `.vsix` para tu plataforma (`darwin-arm64` / `linux-x64` / `win32-x64`) desde la [versión v1.0.3](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3).

Panel de extensiones de VS Code → `···` → *Install from VSIX* → recarga la ventana.

**Desde el código fuente:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

Abre este repo en VS Code y pulsa F5 (Extension Development Host), o instala el VSIX empaquetado.

**Requisitos:** VS Code ≥ 1.96 · Python ≥ 3.12 (compilación desde fuente) · macOS / Linux / Windows

---

## Tres pasos, sin cuarto

1. Abre la barra lateral de Trainer → Settings
2. Pega la info de conexión de tu relay (el bloque JSON completo copiado del panel del relay se parsea automáticamente — endpoint y key se separan por ti) → pega tu API key
3. Pulsa **Save & Connect**

Trainer obtiene la lista de modelos en vivo, elige un modelo por defecto y verifica la ruta de streaming de una sola pasada.

Una key inválida reporta `invalid_key_or_permission` — no un spinner vago.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Configuración rápida" width="420" />
</p>

---

## Mecánicas centrales

### ① Compuertas de verificación — tú escribes el código, el código lo demuestra

Una tarjeta de entrenamiento no puede avanzar a «implementada» hasta que la verificación se ejecuta contra tu archivo real; el botón manual de «marcar como hecho» se ha omitido a propósito.

La forma más rápida de fingir que aprendes es marcar todas las casillas. Trainer se niega.

<p align="center"><img src="assets/feat-verify.png" alt="Compuertas de verificación" width="720" /></p>

**Cómo:**
- El `EvaluatorService` del servidor **copia** el archivo actual a un `tempfile.TemporaryDirectory`, ejecuta ruff + pyright + pytest y destruye el tempdir
- Las herramientas **nunca** se ejecutan en el proyecto del estudiante — cero contaminación de `.pytest_cache`
- Cada comprobación reporta detalle Matched/Missing criterio a criterio contra una lista explícita de `acceptance_criteria` + `expected_symbols`
- Código: `server/app/evaluator/service.py:198-312`

### ② Memoria a largo plazo — planificación sobre la curva de olvido de FSRS

El dominio, los puntos débiles y los repasos pendientes viven en SQLite con recuperación semántica de Qdrant.

Los repasos aparecen sobre la curva de olvido de FSRS — surgen justo antes de que olvides, y callan mientras aún recuerdas.

<p align="center"><img src="assets/feat-memory.png" alt="Memoria a largo plazo" width="720" /></p>

**Cómo:**
- Memoria de dos capas: estructurada (`StructuredMemoryService`, ~480 registros) + semántica (Qdrant + fallback offline de sentence-transformer)
- **`_should_delay_live_thread_reviews()`** — los repasos se suprimen activamente mientras un flujo de implementación de ideas está en curso, así el hilo de pensamiento nunca se interrumpe
- **Las skills transferibles aplican fail closed entre workspaces**: el éxito en un proyecto nunca se convierte en dominio global; la promoción exige pasar en ≥2 workspaces
- Código clave: `server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ El bucle de entrenamiento — aparece cuando toca, avanza cuando verifica

Las flash cards, los ejercicios de teoría y los experimentos de escenario hacen cola en la vista Training: los repasos aparecen cuando toca, las tarjetas avanzan cuando se verifican, y cualquier hueco de conocimiento en una conversación se convierte en tarjeta de entrenamiento con un clic.

<p align="center"><img src="assets/feat-training.png" alt="El bucle de entrenamiento" width="720" /></p>

**Cómo:**
- **Máquina de estados de 5 fases** `LEARN → TRY → VERIFY → REFLECT → RETURN`, cada transición queda registrada en `phase_history`
- **Lista blanca de fuentes de verificación de confianza**: `automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` — una «afirmación manual» jamás avanza una tarjeta
- Los handlers `onSkip` / `onRate` de la UI de tarjetas están marcados **`@deprecated Unused`** — el único camino de progresión es `onCardStatusTransition`
- Código clave: `server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ Tú escribes, el coach guía

El coach lee tus archivos, consulta los diagnósticos y busca en el workspace — pero el código de producción siempre sale de tus manos.

`direct` responde al instante; `coach-first` te obliga a pensar primero. **La carga cognitiva es tuya, no suya.**

<p align="center"><img src="assets/feat-youwrite.png" alt="Tú escribes, el coach guía" width="720" /></p>

**Cómo:**
- `PedagogyService` emite una `ImplementationGuide` de 12 campos en cada turno — cada campo es una restricción sobre lo que el coach puede preguntar después
- `ImplementationCoach._current_step` se ancla a «la primera ruta que falla» o «el primer punto de entrada conocido» — nunca a «explora el codebase»
- Tono guiado por el afecto: `AffectService` cambia al modo `concise_rescue` tras dos fallos consecutivos
- Código clave: `server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## Cinco vistas

> Cinco vistas fijas de primer nivel. Cada una con una frontera de responsabilidad estricta.

| Vista | Rol | En una línea |
|-----------|------|--------|
| **Coach** | Chat en streaming | **Entrada**: acceso a herramientas + paleta de skills `$` + adjuntos de imagen + modos de respuesta |
| **Plan** | Plan de aprendizaje | **Mapa**: etapas, progreso, evidencias, congelar/descongelar el plan |
| **Resources** | Biblioteca | **Estantería**: búsqueda FTS5 + previsualización sandbox de 3 niveles + papelera restaurable |
| **Training** | Entrenamiento | **Zona de juegos**: flash cards FSRS + ejercicios de teoría + experimentos de escenario + compuertas de verificación |
| **Settings** | Ajustes | **Consola**: 59 comandos + test de velocidad de endpoints + intensidad de razonamiento + admisión de workspace |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="Vista Plan" width="260" />
  <img src="assets/screenshots/resources.png" alt="Vista Resources" width="260" />
  <img src="assets/screenshots/training.png" alt="Vista Training" width="260" />
</p>

### Vista Coach (entrada)

Chat en streaming con el coach: acceso a herramientas, paleta de skills `$`, adjuntos de imagen, modos de respuesta, anillo de uso de contexto, historial de sesiones y compartir.

**Cada respuesta del coach lleva tres acciones rápidas debajo:**

- **Copiar la respuesta como Markdown**
- **Guardar en la biblioteca** (buscable + previsualizable)
- **Convertir en tarjeta de entrenamiento verificable** — por mensaje, no por sesión

<p align="center"><img src="assets/screenshots/message-actions.png" alt="Acciones por mensaje" width="520" /></p>

### Skills `$` personalizadas — crea, comparte, instala

Escribe `$` para abrir la paleta de skills: además de las integradas, puedes envolver tus propios prompts en skills con palabras de disparo y keywords, compartirlos con otros o instalar skills que compartan los demás — **todo por un canal de datos puro, sin ejecución de código**.

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="Paleta de skills" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="Gestor de skills" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="Skills personalizadas" width="720" /></p>

**Cómo:**
- Las skills personalizadas son importaciones de JSON puro — `{ _type, version, trigger, title, prompt, keywords }`; sin `eval`, sin `Function()`, sin ruta de código
- Límites duros: prompt ≤ 4000 caracteres, título ≤ 160, keywords ≤ 16, skills de usuario ≤ 24
- Los triggers integrados ganan las colisiones — una `$explain` importada por el usuario no puede eclipsar la de serie
- Código clave: `shared/src/skillCatalog.ts:614-764`

---

## Comparativa

> Trainer no viene a reemplazar a nadie — cubre un hueco que nadie más reclama.

| Dimensión | herramientas vibe | IDEs con chat | apps de flash cards | **Trainer** |
|---|---|---|---|---|
| Escribe código por ti | ✅ | ✅ | ❌ | ❌ |
| Verifica tu código | ❌ | ❌ | ❌ | ✅ contra el archivo actual |
| Recuerda entre sesiones | ⚠️ ventana de contexto | ⚠️ resúmenes | ✅ | ✅ SQLite + Qdrant |
| Repetición espaciada con FSRS | ❌ | ❌ | ✅ | ✅ + supresión en flujo activo |
| Niveles de permiso del workspace | ❌ | ⚠️ diálogo de confianza | ❌ | ✅ 6 niveles + bloqueo duro en remoto |
| Progresión de tarjetas con compuerta | ❌ | ❌ | ⚠️ casillas manuales | ✅ verificada y forzada |
| Promoción de skills transferibles | ❌ | ❌ | ❌ | ✅ fail closed entre workspaces |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ claves × 8 |
| Suite de tests | código cerrado | código cerrado | código cerrado | ✅ **3.328 casos** (abierta) |
| Se niega a escribir por ti | ❌ | ❌ | n/a | ✅ una línea roja filosófica |

> En una línea: las demás herramientas te hacen escribir más rápido; Trainer hace que escribas de verdad.

---

## Demo de cinco minutos

> Esto es lo que de verdad parecen tus primeros cinco minutos.

### T+0:00 — Abre la barra lateral

Haz clic en el icono de Trainer en la barra de actividad. La barra lateral se abre, por defecto en la **vista Coach**.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Primera apertura" width="420" />
</p>

### T+0:30 — Configura el proveedor (solo la primera vez)

Settings → pega tu JSON del relay + API key → Save & Connect.

Trainer obtiene la lista de modelos en vivo, elige uno por defecto y verifica el streaming. Key inválida → te dice `invalid_key_or_permission`.

### T+1:30 — Primera conversación

Cambia a Coach y escribe: `@current_file explain what this async/await is doing?`

Trainer emite la respuesta en streaming. **No reescribe tu código.** Señala la línea 17: «esto es un fan-out»; línea 23: «esta es la barrera. Para aprender esto de verdad, escribe una versión que cancele una tarea a mitad de vuelo — la verificación la ejecuto contigo».

### T+2:30 — Tarjeta de entrenamiento en un clic

Pasa el cursor sobre la respuesta. Tres botones: `Copy` / `Save to library` / **`Create training card`**.

Haz clic en `Create training card` → tarjeta generada → entra en la vista Training → FSRS la programa para dentro de 3 días.

### T+4:00 — Escríbelo tú y pasa la verificación

Tú escribes el código. Trainer **no lo escribe por ti**.

Abre Training → voltea la tarjeta → mira los criterios de aprobación → escribe → pulsa `Request verification` → Trainer ejecuta ruff + pyright + pytest en un sandbox → reporta aprobado o señala el criterio que falta.

### T+5:00 — Al día siguiente

Abre VS Code mañana: Trainer se restaura solo — última sesión, plan y progreso de tarjetas, todo en su sitio.

Esa tarjeta pulsa en el disco de ritmo de FSRS — toca hoy.

**Ya no eres un desarrollador de vibe coding.**

---

## Por qué se siente distinto

### Fracaso honesto

Una key inválida dice `invalid_key_or_permission`; un destino inalcanzable dice `network`; una respuesta corrupta dice «esta respuesta no se leyó bien, reenvíala» — **un output roto nunca se disfraza de respuesta**.

Los gateways desconocidos no se asumen silenciosamente compatibles con OpenAI.

**Cómo:** clasificador de errores (`provider_service.py:2823-2874`) + limpieza de credenciales (`provider_protocols.py:640-681`) + sondeo de huellas desconocidas (`provider_gateway.py:39-70`).

### Test de velocidad de endpoints

Los endpoints del proveedor compiten en paralelo (**primero un warm-up para anular la penalización de arranque en frío, luego cronometrado**).

Verde por debajo de 500 ms, amarillo por debajo de 1 s. Un clic adopta el más rápido.

<p align="center"><img src="assets/feat-speed.png" alt="Test de velocidad de endpoints" width="720" /></p>

**Cómo:** `Promise.all` + una petición de warm-up descartada por URL antes de la cronometrada (`providerWebviewCommands.ts:2275-2352`).

### Anillo de uso de contexto

Un anillo de uso de contexto en vivo corona la conversación — **ves venir la compresión antes de que ocurra**.

### Intensidad de razonamiento

Condicionada a evidencia por modelo — capacidad declarada **o** sonda verificada. Nunca se reenvía a ciegas.

### Biblioteca a toda potencia

<p align="center"><img src="assets/feat-library.png" alt="Biblioteca a toda potencia" width="720" /></p>

Subidas indexadas al llegar, búsqueda de texto completo con FTS5, **previsualización sandbox de 3 niveles** (A rica / B convertida / C metadatos + fallback al editor nativo), los borrados van a una papelera restaurable.

**Separación física en 3 zonas**: workspace / sandbox / papelera. Nunca se mezclan.

Las respuestas del coach entran con un clic — **si puedes buscarlo de vuelta, es que de verdad lo aprendiste**.

### Estado de largo plazo

Los planes se congelan y descongelan; las sesiones sobreviven a los reinicios; el progreso de las tarjetas vive en SQLite; los repasos vencen en la curva de FSRS — **no en una lista de tareas**.

---

## Arquitectura

### Topología del sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Window                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   Trainer Sidebar                                     │  │
│  │   (React 19 + Zustand, 8-language i18n, 24 governance)│  │
│  │                                                       │  │
│  │   ─── postMessage ─── CommandRegistry ── 59 commands  │  │
│  │                                       │               │  │
│  └───────────────────────────────────────┼───────────────┘  │
│                                          │                   │
│                          ┌───────────────▼──────────────┐    │
│                          │  FastAPI sidecar (127.0.0.1)│    │
│                          │  PyInstaller --onedir frozen│    │
│                          │  (250 MB / 6 platform arch) │    │
│                          │                              │    │
│                          │  ├── ReAct agent loop        │    │
│                          │  │   (dual-channel stream)   │    │
│                          │  ├── Pedagogy (12-field guide)│   │
│                          │  ├── Affect (failures→rescue)│    │
│                          │  ├── Memory                  │    │
│                          │  │   SQLite + Qdrant semantic│    │
│                          │  ├── FSRS scheduler          │    │
│                          │  ├── Authority (6 tiers)     │    │
│                          │  ├── Provider (5 protocols)  │    │
│                          │  ├── Training handoff (5 ph.)│    │
│                          │  └── Resources (3 zones+FTS5)│    │
│                          │                              │    │
│                          │  ─── 24 shared pure fns ────│    │
│                          │      (host + webview + test)  │    │
│                          └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Estructura de directorios

| Carpeta | Contenido | Tamaño |
|---|---|---|
| `extension/src/` | Host: comandos, confianza del workspace, almacenamiento de secretos, ciclo de vida del sidecar | ~30k líneas de TS |
| `extension/webview/` | Workbench en React: 5 vistas + Zustand + 8 idiomas | ~50k líneas de TSX |
| `extension/tests/` | suite node:test (220 archivos / 1.679 casos) | 73.744 líneas |
| `server/app/` | Cerebro FastAPI: agente / pedagogía / memoria / FSRS / entrenamiento | ~120k líneas de Python |
| `server/tests/` | suite pytest (159 archivos / 1.649 casos) | 106.422 líneas |
| `shared/src/` | **Funciones puras compartidas + 24 módulos de gobernanza** (host + webview + test) | ~3k líneas de TS |
| `extension/bundled/` | Sidecar empaquetado en el VSIX (PyInstaller onedir) | ~250 MB |

### Un único sobre canónico

> Todas las respuestas HTTP de Trainer (excepto `/health`) devuelven el **mismo** `WorkbenchSnapshot` (31 campos).

| Categoría | Campos de ejemplo | Productor |
|---|---|---|
| Sesión | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| Plan | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| Memoria | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| Enseñanza | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| Afecto | `affect_state`, `tone_decision` | `affect/service.py` |
| Entrenamiento | `evaluation`, `review_queue_summary` | `training/*` |
| Meta | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**Por qué un solo sobre:**
- El webview renderiza **enteramente desde este único objeto** — 12 subsistemas escriben sus campos, se hidrata una vez
- **Sincronización incremental tipo CRDT ligero**: cada snapshot lleva una `snapshot_revision`; `GET /snapshot?since_revision=N` solo envía el blob completo cuando N está obsoleto; si no, `{unchanged: true}`
- Código clave: `server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### Módulos de gobernanza compartidos

> La columna vertebral arquitectónica de Trainer son **24 módulos de gobernanza de funciones puras** — host, webview y tests ejecutan la misma lógica determinista.

| Módulo | Rol |
|---|---|
| `planGovernance` · `masterPlanGovernance` | Edición del plan, plan maestro entre proyectos |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | Enrutado de tarjetas, recuperación, fiabilidad |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | Ordenación de la cola FSRS, revisión de evidencias |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | Permisos de 6 niveles, recuperación |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | Acciones sugeridas, arbitraje de conversación |
| `transferEvidenceGovernance` · `transferSkillGovernance` | Evidencias entre proyectos, promoción de skills |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Orientación de las vistas Coach/Resources |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | Condicionado de capacidades de Settings, fiabilidad de operaciones |
| `hostLastTestGovernance` · `providerModelPolicy` | Último test del proveedor, política de modelos |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | Narrativa de capacidades del sandbox, carriles de proyecto |
| `previewAssets` · `materialRecommendationGovernance` | Niveles de assets de previsualización, recomendaciones de material |

**Por qué:** el mismo `resolveSuggestedActionGovernance` corre en host, webview y tests — **consistencia a tres bandas, sin viajes de ida y vuelta**.

---

## Modelo de seguridad

- Las API keys viven en **VS Code SecretStorage** (cifrado a nivel de SO) — nunca en archivos de configuración, nunca en git
- El workspace sigue la **confianza nativa de VS Code** — todas las escrituras se rechazan mientras no sea de confianza
- **Escalera de permisos de 6 niveles**: INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE — solo lectura por defecto; escribir/borrar/modificar exige una certificación escalonada
- **Los workspaces remotos están bloqueados en duro por debajo de REORGANIZE** — ni con permiso del usuario se puede subir de nivel
- **Borrar va a la papelera**: no existe la operación `delete`, solo `move to <root>/.trash/<timestamp-uuid>/`
- Las previsualizaciones del sandbox aplican una **gobernanza de rutas** estricta — las rutas fuera de límites reciben un 422 sin más
- Compartir skills es una **importación de datos puros** — longitudes de campo limitadas, las integradas ganan, **no existe ruta de código**

**Código clave:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## Compuertas de calidad

> Trainer trata su propia pila de verificación como un producto.

| Compuerta | Cobertura | Notas |
|---|---|---|
| **Tests del servidor** (pytest) | **159 archivos / 1.649 casos / 106.422 líneas** | incl. 6 suites de propiedades con Hypothesis |
| **Tests de la extensión** (node:test) | **220 archivos / 1.679 casos / 73.744 líneas** | 109 archivos de guardas de fuente + 111 tests de comportamiento |
| **E2E** | **11 specs / 4.335 líneas** | instancia real de VS Code contra un modelo real |
| **Matriz de experiencia** | **200 escenarios × 2 capas** | fixture de preview + sidecar real |
| **Driver del host VSIX** | **33 pasos** | instalar → activar → stream → verificar → comprobar el renderizado real del webview |
| **Análisis estático** | ruff + pyright + tsc | cero warnings |
| **Matriz de protocolos** | **5 protocolos** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 idiomas × 600+ claves** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **sidecar bundled** | **6 binarios de plataforma** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**La suite E2E corre en una instancia real de VS Code contra un modelo real:**

> Activa la extensión empaquetada → arranca el sidecar bundled → guarda el proveedor → emite un turno completo del coach en streaming → genera y verifica una tarjeta de entrenamiento → comprueba lo que el webview **realmente renderizó** → captura pantallas → reabre entre workspaces y recupera el historial.

**Los tests atestiguan sus propios límites:**
Cada escenario E2E lleva `evidence: { realSidecar, limitation }` — **el test declara lo que no demuestra.**

---

## i18n · Ocho idiomas

| Idioma | Código | Principal |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**Cadena de fallback:** preferencia del usuario > `env.language` de VS Code > `zh-CN` (por defecto)

**6 overrides por superficie:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` — quien traduce solo rellena las superficies que le corresponden, **no la tabla completa de 600+ claves**.

Código clave: `extension/webview/src/lib/i18n/copy.ts` (5.283 líneas)

---

## Agradecimientos

> Trainer se apoya en hombros de gigantes.

### 🏃 Núcleo en ejecución

| Proyecto | Propósito | Por qué es imprescindible |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | Framework del sidecar local | async + Pydantic + documentación OpenAPI automática |
| [Uvicorn](https://github.com/encode/uvicorn) | Servidor ASGI | HTTP/1.1 + WebSocket + alta concurrencia |
| [Pydantic](https://github.com/pydantic/pydantic) | Validación y serialización de datos | el WorkbenchSnapshot de 31 campos corre sobre él |
| [httpx](https://github.com/encode/httpx) | Cliente HTTP asíncrono | todo el enrutado de protocolos sidecar ↔ gateway del LLM |

### 🤖 Protocolos LLM

| Proyecto | Propósito |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | Cliente compatible con OpenAI / Anthropic / Gemini (enrutado de 5 protocolos) |

### 🧠 Entrenamiento y memoria

| Proyecto | Propósito |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | Planificación de repasos según la curva de olvido FSRS · mueve `TrainingCardState` |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | Recuperación vectorial de memoria semántica (con fallback a sentence-transformer) |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | Parseo de PDF (previsualización Tier A de la biblioteca) |
| [trafilatura](https://github.com/adbar/trafilatura) | Extracción de contenido web (ingesta de recursos) |
| [markitdown](https://github.com/microsoft/markitdown) | Conversión de documentos a Markdown (previsualización Tier B de la biblioteca) |

### ⚛️ Núcleo de frontend

| Proyecto | Propósito |
|---|---|
| [React](https://github.com/facebook/react) | UI del workbench de la barra lateral |
| [Vite](https://github.com/vitejs/vite) | Herramienta de build + servidor de desarrollo |
| [Zustand](https://github.com/pmndrs/zustand) | Gestión de estado del workbench |
| [Zod](https://github.com/colinhacks/zod) | Validación de tipos en runtime |

### 🎨 Renderizado

| Proyecto | Propósito |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Renderizado de Markdown |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | Extensiones GFM (tablas, listas de tareas) |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | Renderizado de matemáticas |
| [Shiki](https://github.com/shikijs/shiki) | Resaltado de código (gramáticas TextMate de VS Code) |
| [Mermaid](https://github.com/mermaid-js/mermaid) | Diagramas y flujogramas |
| [@tanstack/react-table](https://github.com/TanStack/table) | Tablas de la biblioteca / cola de entrenamiento |

### 📄 Previsualización

| Proyecto | Propósito |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | Renderizado rico de DOCX (Tier A) |
| PDF.js (incluido) | Renderizado rico de PDF (Tier A) |

### 🧪 Tests y calidad

| Proyecto | Propósito |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | Servidor: 159 archivos / 1.649 casos |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | Testing de propiedades (planner / evaluator / scheduler) |
| [ruff](https://github.com/astral-sh/ruff) | Lint + formato de Python (E/F/I/B, py312, 100 columnas) |
| [pyright](https://github.com/microsoft/pyright) | Comprobación estática de tipos de Python |
| [TypeScript](https://github.com/microsoft/TypeScript) | modo strict, cero warnings |
| [Playwright](https://github.com/microsoft/playwright) | E2E + matriz de experiencia de 200 escenarios |

### 📦 Empaquetado y distribución

| Proyecto | Propósito |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | Congelación del sidecar en un solo binario (6 plataformas, manifest sha256) |

### 💡 Inspiración metodológica

| Proyecto | Inspiración |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | El paper original de FSRS y su implementación de referencia |
| [obra/superpowers](https://github.com/obra/superpowers) | La disciplina de coaching de «workflows obligatorios, no sugerencias» |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | La ambición de «hacer todo el software agent-native» |

### 🎨 Recursos visuales

| Proyecto | Propósito |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | Todas las imágenes de este README (ver `assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md`) |
| La chica moe oficial de DeepSeek | referencia de proporciones chibi / tendencia cel-shading |
| Pieter Bruegel, *La Torre de Babel* | referencia de composición de conjunto con dos bandos izquierda-derecha |
| Rembrandt, *La ronda de noche* | referencia de contraste claroscuro 7:1 |
| Diseño de personajes de Studio Ghibli | ojos grandes con luces de tres puntos, expresiones contenidas |

---

## Licencia

[MIT](LICENSE)

---

## Citar Trainer

Si Trainer mejoró tu flujo de trabajo, siéntete libre de citarlo en tu blog / paper / charla:

```bibtex
@software{trainer2026,
  title  = {Trainer: A Long-Term Coding Coach Living in Your Editor},
  author = {AI-yyf and contributors},
  year   = {2026},
  url    = {https://github.com/AI-yyf/trainer},
  note   = {v1.0.3}
}
```

---

<div align="center">

**// Entrena a tu IA · Crece con tu IA**

`v1.0.3` · Hecho con café, FSRS, 24 funciones puras, 3.328 tests y un corazón que se niega a escribir código por ti.

</div>
