# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer — Trainiere deine KI · Wachse mit deiner KI · Wo KI und Menschen zusammen wachsen" width="100%" />

**Ein langfristiger Coding-Coach, der in deiner VS Code Sidebar lebt.**

**Er plant, drillt, verifiziert und merkt sich alles über dich — aber deinen Code schreibt er nie.**

**// Output ≠ Wachstum // Verifizieren + Wiederholen = Wachstum**

[English](README.md) · [简体中文](README_zh-CN.md) · [Español](README_es-ES.md) · [Français](README_fr-FR.md) · Deutsch · [日本語](README_ja-JP.md) · [한국어](README_ko-KR.md) · [Português](README_pt-BR.md)

[![Release](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#installation)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#qualitätsgates)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--acht-sprachen)

[Warum](#warum-es-trainer-gibt) ·
[Installation](#installation) ·
[Einrichtung](#drei-schritte-kein-vierter) ·
[Mechaniken](#kernmechaniken) ·
[Fünf Ansichten](#fünf-ansichten) ·
[Vergleich](#vergleich) ·
[5-Min-Demo](#fünf-minuten-demo) ·
[Design](#warum-es-sich-anders-anfühlt) ·
[Architektur](#architektur) ·
[Sicherheit](#sicherheitsmodell) ·
[Qualität](#qualitätsgates) ·
[Danksagungen](#danksagungen) ·
[🎭 Die Crew](docs/CAST.md)

</div>

---

## Warum es Trainer gibt

> Entwickler bleiben nicht hängen, weil es an Tutorials mangelt.
> Sie bleiben hängen, weil nichts die Lernschleife schließt.

Ein Chat mit einem LLM verdampft in dem Moment, in dem er endet; Videos sind passiv; das Konzept, das du am Dienstag fast verstanden hattest, ist am Freitag weg.

Schlimmer noch: **vibe coding** — drei Monate lang Code von der KI schreiben lassen, während du nichts davon verstehst.

Lesezeichen stapeln sich, während der Output flach bleibt. Repos wachsen, während dein Kopf sich leert.

**Trainer löst das direkt im Editor.**

Er ist keine Chat-Shell — er ist ein Coach mit Gedächtnis, Lehrplan und Prüfungsordnung:

- Er **plant** dein Lernen in Etappen und verfolgt, wo du wirklich stehst — nicht, wo du dich nur fühlst
- Er **trainiert** dich mit Lernkarten, Theorie-Drills und Szenario-Experimenten
- Er **verifiziert** dein Können an deinem echten Code — über FastAPI reden zählt nichts, solange die aktuelle Datei es nicht beweist
- Er **erinnert** sich über Sitzungen, Projekte und Wochen hinweg an dich und plant Wiederholungen auf der FSRS-Vergessenskurve
- Er **schreibt niemals Produktionscode für dich** — du schreibst, er lehrt, **ihr wächst zusammen**

<div align="center">

| vibe coding · der heutige Standard | Trainer · wie es sein sollte |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# hast du es verstanden?` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| Output = Vergessen | Output + Gedächtnis + Wiederholung = Wachstum |

</div>

---

## Installation

**Per VSIX (vorgebaut, drei Plattformen):**

Hol dir die `.vsix` für deine Plattform (`darwin-arm64` / `linux-x64` / `win32-x64`) aus dem [v1.0.3-Release](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3).

VS Code Extensions-Panel → `···` → *Install from VSIX* → Fenster neu laden.

**Aus dem Quellcode:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

Öffne dieses Repo in VS Code und drücke F5 (Extension Development Host), oder installiere das gepackte VSIX.

**Voraussetzungen:** VS Code ≥ 1.96 · Python ≥ 3.12 (Quellcode-Build) · macOS / Linux / Windows

---

## Drei Schritte, kein vierter

1. Öffne die Trainer-Sidebar → Settings
2. Füge deine Relay-Verbindungsdaten ein (der komplette JSON-Block, kopiert aus einem Relay-Dashboard, wird automatisch geparst — Endpoint und Key werden dir sauber getrennt) → füge deinen API-Key ein
3. Klick auf **Save & Connect**

Trainer zieht die Live-Modellliste, wählt ein Standardmodell und prüft den Streaming-Pfad in einem Durchgang.

Ein ungültiger Key meldet `invalid_key_or_permission` — kein vager Spinner.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Schnelleinrichtung" width="420" />
</p>

---

## Kernmechaniken

### ① Verifikationsgates — du schreibst den Code, der Code beweist es

Eine Trainingskarte rückt nicht auf „implementiert“ vor, bis die Verifikation gegen deine tatsächliche Datei läuft; einen manuellen „als erledigt markieren“-Button gibt es absichtlich nicht.

Der schnellste Weg, Lernen vorzutäuschen, ist, jedes Kästchen abzuhaken. Trainer macht da nicht mit.

<p align="center"><img src="assets/feat-verify.png" alt="Verifikationsgates" width="720" /></p>

**Wie:**
- Der Server-`EvaluatorService` **kopiert** die aktuelle Datei in ein `tempfile.TemporaryDirectory`, führt dort ruff + pyright + pytest aus und räumt das Temp-Verzeichnis wieder ab
- Tools laufen **nie** im Projekt des Lernenden — keine `.pytest_cache`-Verschmutzung
- Jeder Check meldet Details pro Kriterium (Matched/Missing) gegen eine explizite Liste aus `acceptance_criteria` + `expected_symbols`
- Code: `server/app/evaluator/service.py:198-312`

### ② Langzeitgedächtnis — FSRS-Vergessenskurven-Planung

Gelerntes, Schwachstellen und fällige Wiederholungen leben in SQLite, mit semantischem Abruf über Qdrant.

Wiederholungen folgen der FSRS-Vergessenskurve — sie erscheinen genau kurz bevor du vergessen würdest und halten sich zurück, solange du dich noch erinnerst.

<p align="center"><img src="assets/feat-memory.png" alt="Langzeitgedächtnis" width="720" /></p>

**Wie:**
- Zweischichtiges Gedächtnis: strukturiert (`StructuredMemoryService`, ~480 Einträge) + semantisch (Qdrant + sentence-transformer als Offline-Fallback)
- **`_should_delay_live_thread_reviews()`** — Wiederholungen werden aktiv unterdrückt, solange ein Idee-Umsetzungs-Flow läuft, damit dein Gedankengang nie unterbrochen wird
- **Übertragbare Skills sind über Workspaces fail-closed**: Erfolg in einem Projekt wird nie zur globalen Meisterschaft; befördert wird nur, was in ≥2 Workspaces besteht
- Zentraler Code: `server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ Die Trainingsschleife — kommt bei Fälligkeit, rückt weiter bei Verifikation

Lernkarten, Theorie-Drills und Szenario-Experimente warten in der Training-Ansicht: Wiederholungen erscheinen bei Fälligkeit, Karten rücken nach Verifikation weiter, und jede Wissenslücke im Gespräch wird mit einem Klick zur Trainingskarte.

<p align="center"><img src="assets/feat-training.png" alt="Die Trainingsschleife" width="720" /></p>

**Wie:**
- **5-Phasen-Zustandsmaschine** `LEARN → TRY → VERIFY → REFLECT → RETURN`, jeder Übergang wird in `phase_history` protokolliert
- **Whitelist vertrauenswürdiger Verifikationsquellen**: `automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` — eine „manuelle Behauptung“ kann eine Karte nie weiterbringen
- Die `onSkip`/`onRate`-Handler der Karten-UI sind **`@deprecated Unused`** — der einzige Weg nach vorn führt über `onCardStatusTransition`
- Zentraler Code: `server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ Du schreibst, der Coach führt

Der Coach liest deine Dateien, prüft Diagnostics und durchsucht den Workspace — aber Produktionscode entsteht immer in deinen Händen.

`direct` antwortet sofort; `coach-first` lässt dich zuerst denken. **Die kognitive Last gehört dir, nicht ihm.**

<p align="center"><img src="assets/feat-youwrite.png" alt="Du schreibst, der Coach führt" width="720" /></p>

**Wie:**
- Der `PedagogyService` stellt in jedem Turn einen `ImplementationGuide` mit 12 Feldern bereit — jedes Feld ist eine Einschränkung dessen, was der Coach als Nächstes fragen darf
- `ImplementationCoach._current_step` ist am „ersten scheiternden Pfad“ oder am „ersten bekannten Einstiegspunkt“ verankert — nie bei „erkunde die Codebasis“
- Affect-getriebener Ton: Der `AffectService` schaltet nach zwei Fehlern in Folge in den `concise_rescue`-Modus
- Zentraler Code: `server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## Fünf Ansichten

> Fünf feste Ansichten auf oberster Ebene. Jede mit einer strikten Verantwortungsgrenze.

| Ansicht | Rolle | Kurzfassung |
|-----------|------|--------|
| **Coach** | Streaming-Chat | **Einstieg**: Tool-Zugriff + `$`-Skill-Palette + Bildanhänge + Antwortmodi |
| **Plan** | Lernplan | **Karte**: Etappen, Fortschritt, Evidenz, Plan einfrieren/auftauen |
| **Resources** | Bibliothek | **Bücherregal**: FTS5-Suche + 3-stufige Sandbox-Vorschau + wiederherstellbarer Papierkorb |
| **Training** | Training | **Spielplatz**: FSRS-Lernkarten + Theorie-Drills + Szenario-Experimente + Verifikationsgates |
| **Settings** | Einstellungen | **Konsole**: 59 Befehle + Endpoint-Speedtest + Denkintensität + Workspace-Zulassung |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="Plan-Ansicht" width="260" />
  <img src="assets/screenshots/resources.png" alt="Resources-Ansicht" width="260" />
  <img src="assets/screenshots/training.png" alt="Training-Ansicht" width="260" />
</p>

### Coach-Ansicht (Einstieg)

Streaming-Coach-Chat mit Tool-Zugriff, `$`-Skill-Palette, Bildanhängen, Antwortmodi, Kontextnutzungs-Ring, Sitzungsverlauf und Teilen-Funktion.

**Unter jeder Coach-Antwort sitzen drei Schnellaktionen:**

- **Antwort als Markdown kopieren**
- **In die Bibliothek speichern** (durchsuchbar + in der Vorschau ansehbar)
- **In eine überprüfbare Trainingskarte umwandeln** — pro Nachricht, nicht pro Sitzung

<p align="center"><img src="assets/screenshots/message-actions.png" alt="Aktionen pro Nachricht" width="520" /></p>

### Eigene `$`-Skills — erstellen, teilen, installieren

Tippe `$`, um die Skill-Palette zu öffnen: Neben den eingebauten Skills kannst du eigene Prompts in Skills mit Trigger-Wörtern und Keywords verpacken, sie mit anderen teilen oder Skills installieren, die andere teilen — **alles über einen reinen Datenkanal, ohne Code-Ausführung**.

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="Skill-Palette" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="Skill-Manager" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="Eigene Skills" width="720" /></p>

**Wie:**
- Eigene Skills sind reine JSON-Importe — `{ _type, version, trigger, title, prompt, keywords }`; kein `eval`, kein `Function()`, kein Code-Pfad
- Harte Limits: Prompt ≤ 4000 Zeichen, Titel ≤ 160, Keywords ≤ 16, User-Skills ≤ 24
- Bei Kollisionen gewinnen eingebaute Trigger — ein importierter `$explain` kann den mitgelieferten nicht überschatten
- Zentraler Code: `shared/src/skillCatalog.ts:614-764`

---

## Vergleich

> Trainer ist nicht da, um jemanden zu ersetzen — er füllt eine Lücke, die niemand sonst besetzt.

| Dimension | Vibe-Tools | Chat-IDEs | Flashcard-Apps | **Trainer** |
|---|---|---|---|---|
| Schreibt Code für dich | ✅ | ✅ | ❌ | ❌ |
| Verifiziert deinen Code | ❌ | ❌ | ❌ | ✅ gegen die aktuelle Datei |
| Erinnert sich über Sitzungen hinweg | ⚠️ Kontextfenster | ⚠️ Zusammenfassungen | ✅ | ✅ SQLite + Qdrant |
| Spaced Repetition auf FSRS | ❌ | ❌ | ✅ | ✅ + Live-Flow-Unterdrückung |
| Workspace-Berechtigungsstufen | ❌ | ⚠️ Trust-Dialog | ❌ | ✅ 6 Stufen + harte Remote-Sperre |
| Karten-Fortschritt gegated | ❌ | ❌ | ⚠️ manuelle Checkboxen | ✅ Verifikation erzwungen |
| Beförderung übertragbarer Skills | ❌ | ❌ | ❌ | ✅ fail-closed über Workspaces |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ Keys × 8 |
| Testsuite | closed source | closed source | closed source | ✅ **3.328 Fälle** (offen) |
| Verweigert das Schreiben für dich | ❌ | ❌ | n/v | ✅ eine philosophische Grenze |

> In einem Satz: Andere Tools bringen dich zum schnelleren Schreiben; Trainer bringt dich zum tatsächlichen Schreiben.

---

## Fünf-Minuten-Demo

> So sehen deine ersten fünf Minuten tatsächlich aus.

### T+0:00 — Sidebar öffnen

Klick auf das Trainer-Symbol in der Activity Bar. Die Sidebar öffnet sich, standardmäßig in der **Coach-Ansicht**.

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="Erstes Öffnen" width="420" />
</p>

### T+0:30 — Provider konfigurieren (nur beim ersten Mal)

Settings → Relay-JSON + API-Key einfügen → Save & Connect.

Trainer zieht die Live-Modellliste, wählt einen Default, prüft das Streaming. Ungültiger Key → du bekommst `invalid_key_or_permission`.

### T+1:30 — Erstes Gespräch

Wechsle zu Coach und tipp: `@current_file explain what this async/await is doing?`

Trainer streamt eine Antwort. **Er schreibt deinen Code nicht um.** Er zeigt auf Zeile 17: „das ist ein Fan-out“; Zeile 23: „das ist die Barriere. Um das wirklich zu lernen, schreib eine Version, die einen Task mitten in der Ausführung abbricht — ich führe die Verifikation mit dir durch.“

### T+2:30 — Trainingskarte mit einem Klick

Fahr mit der Maus über die Antwort. Drei Buttons: `Copy` / `Save to library` / **`Create training card`**.

Klick auf `Create training card` → Karte generiert → landet in der Training-Ansicht → FSRS plant sie für 3 Tage ab heute ein.

### T+4:00 — Selbst schreiben, verifizieren lassen

Du schreibst Code. Trainer **schreibt ihn nicht für dich**.

Öffne Training → Karte umdrehen → Bestehenskriterien ansehen → schreiben → `Request verification` klicken → Trainer führt ruff + pyright + pytest in einer Sandbox aus → meldet Bestehen oder markiert ein fehlendes Kriterium.

### T+5:00 — Am nächsten Tag

Öffne morgen VS Code: Trainer stellt alles automatisch wieder her — letzte Sitzung, Plan, Karten-Fortschritt, alles da.

Die Karte pulsiert auf der FSRS-Rhythmanzeige — heute fällig.

**Du bist kein Vibe-Coding-Entwickler mehr.**

---

## Warum es sich anders anfühlt

### Ehrliches Scheitern

Ein ungültiger Key sagt `invalid_key_or_permission`; nicht erreichbar sagt `network`; eine kaputte Antwort sagt „diese Antwort war nicht klar lesbar, bitte erneut senden“ — **kaputter Output wird nie als Antwort verkleidet**.

Unbekannte Gateways werden nicht stillschweigend als OpenAI-kompatibel angenommen.

**Wie:** Fehlerklassifizierer (`provider_service.py:2823-2874`) + Credential-Scrubbing (`provider_protocols.py:640-681`) + Unknown-Fingerprint-Abtastung (`provider_gateway.py:39-70`).

### Endpoint-Speedtest

Provider-Endpoints treten parallel gegeneinander an (**erst Warm-up, um die Cold-Start-Strafe zu neutralisieren, dann wird gestoppt**).

Grün unter 500 ms, gelb unter 1 s. Ein Klick übernimmt den Schnellsten.

<p align="center"><img src="assets/feat-speed.png" alt="Endpoint-Speedtest" width="720" /></p>

**Wie:** `Promise.all` + eine verworfene Warm-up-Anfrage pro URL vor der gestoppten (`providerWebviewCommands.ts:2275-2352`).

### Kontextnutzungs-Ring

Ein Live-Ring zur Kontextnutzung sitzt über dem Gespräch — **du siehst die Kompression kommen, bevor sie passiert**.

### Denkintensität

Gegated anhand von Evidenz pro Modell — deklarierte Fähigkeit **oder** verifizierte Sondierung. Wird nie blind durchgereicht.

### Bibliothek auf Vollgas

<p align="center"><img src="assets/feat-library.png" alt="Bibliothek auf Vollgas" width="720" /></p>

Uploads werden beim Eintreffen indexiert, FTS5-Volltextsuche, **3-stufige Sandbox-Vorschau** (A reich / B konvertiert / C Metadaten + nativer Editor-Fallback), Löschungen landen im wiederherstellbaren Papierkorb.

**Physische 3-Zonen-Trennung**: Workspace / Sandbox / Papierkorb. Niemals vermischt.

Coach-Antworten landen mit einem Klick darin — **wenn du es wiederfinden kannst, hast du es wirklich gelernt**.

### Zustand mit langem Horizont

Pläne frieren ein und tauen auf; Sitzungen überleben Neustarts; der Karten-Fortschritt lebt in SQLite; Wiederholungen werden auf der FSRS-Kurve fällig — **nicht auf einer To-do-Liste**.

---

## Architektur

### Systemtopologie

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

### Verzeichnisstruktur

| Ordner | Inhalt | Größe |
|---|---|---|
| `extension/src/` | Host: Commands, Workspace-Trust, Secret Storage, Sidecar-Lebenszyklus | ~30k Zeilen TS |
| `extension/webview/` | React-Workbench: 5 Ansichten + Zustand + 8 Sprachen | ~50k Zeilen TSX |
| `extension/tests/` | node:test-Suite (220 Dateien / 1.679 Fälle) | 73.744 Zeilen |
| `server/app/` | FastAPI-Gehirn: Agent / Pädagogik / Memory / FSRS / Training | ~120k Zeilen Python |
| `server/tests/` | pytest-Suite (159 Dateien / 1.649 Fälle) | 106.422 Zeilen |
| `shared/src/` | **Geteilte Pure Functions + 24 Governance-Module** (Host + Webview + Test) | ~3k Zeilen TS |
| `extension/bundled/` | Sidecar, ins VSIX gebündelt (PyInstaller onedir) | ~250 MB |

### Ein kanonischer Umschlag

> Alle Trainer-HTTP-Antworten (außer `/health`) geben denselben `WorkbenchSnapshot` zurück (31 Felder).

| Kategorie | Beispielfelder | Produzent |
|---|---|---|
| Sitzung | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| Plan | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| Gedächtnis | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| Unterricht | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| Affekt | `affect_state`, `tone_decision` | `affect/service.py` |
| Training | `evaluation`, `review_queue_summary` | `training/*` |
| Meta | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**Warum ein Umschlag:**
- Das Webview rendert **vollständig aus diesem einen Objekt** — 12 Subsysteme schreiben ihre Felder, ein einziger Hydrationsschritt
- **CRDT-light inkrementelle Synchronisierung**: Jeder Snapshot hat eine `snapshot_revision`; `GET /snapshot?since_revision=N` verschickt den vollen Blob nur, wenn N veraltet ist, sonst `{unchanged: true}`
- Zentraler Code: `server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### Gemeinsame Governance-Module

> Das architektonische Rückgrat von Trainer sind **24 Governance-Module aus Pure Functions** — Host, Webview und Test fahren alle dieselbe deterministische Logik.

| Modul | Rolle |
|---|---|
| `planGovernance` · `masterPlanGovernance` | Plan-Bearbeitung, projektübergreifender Masterplan |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | Karten-Routing, Recovery, Zuverlässigkeit |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | FSRS-Queue-Ordnung, Evidenz-Review |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | 6-stufige Berechtigungen, Recovery |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | Vorgeschlagene Aktionen, Gesprächs-Schlichtung |
| `transferEvidenceGovernance` · `transferSkillGovernance` | Projektübergreifende Evidenz, Skill-Beförderung |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Orientierung in Coach-/Resources-Ansicht |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | Settings-Fähigkeits-Gating, Betriebszuverlässigkeit |
| `hostLastTestGovernance` · `providerModelPolicy` | Letzter Provider-Test, Modell-Policy |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | Sandbox-Fähigkeits-Narrativ, Projekt-Spuren |
| `previewAssets` · `materialRecommendationGovernance` | Vorschau-Asset-Stufen, Material-Empfehlungen |

**Warum:** Dasselbe `resolveSuggestedActionGovernance` läuft in Host, Webview und Tests — **dreifach konsistent, keine Round-Trips**.

---

## Sicherheitsmodell

- API-Keys liegen im **VS Code SecretStorage** (Verschlüsselung auf OS-Ebene) — nie in Config-Dateien, nie in git
- Der Workspace folgt dem **nativen VS Code Trust** — solange nicht vertraut, wird jeder Schreibzugriff verweigert
- **6-stufige Berechtigungsleiter**: INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE — standardmäßig read-only; Schreiben/Löschen/Ändern erfordern eskalierende Attestierung
- **Remote-Workspaces sind unterhalb von REORGANIZE hart verriegelt** — selbst eine Nutzerfreigabe hebt das nicht auf
- **Löschen geht in den Papierkorb**: kein `delete`-Op, nur `move to <root>/.trash/<timestamp-uuid>/`
- Sandbox-Vorschauen erzwingen strenge **Path-Governance** — Pfade außerhalb der Grenzen bekommen ein kompromissloses 422
- Skill-Sharing ist ein **reiner Datenimport** — begrenzte Feldlängen, Eingebaute gewinnen, **ein Code-Pfad existiert nicht**

**Zentraler Code:** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## Qualitätsgates

> Trainer behandelt seinen eigenen Verifikations-Stack als Produkt.

| Gate | Abdeckung | Anmerkungen |
|---|---|---|
| **Server-Tests** (pytest) | **159 Dateien / 1.649 Fälle / 106.422 Zeilen** | inkl. 6 Hypothesis-Property-based-Suiten |
| **Extension-Tests** (node:test) | **220 Dateien / 1.679 Fälle / 73.744 Zeilen** | 109 Source-Guard-Dateien + 111 Verhaltenstests |
| **E2E** | **11 Specs / 4.335 Zeilen** | echte VS Code-Instanz gegen ein echtes Modell |
| **Experience-Matrix** | **200 Szenarien × 2 Ebenen** | Preview-Fixture + echter Sidecar |
| **VSIX-Host-Treiber** | **33 Schritte** | installieren → aktivieren → streamen → verifizieren → echtes Webview-Rendering prüfen |
| **Statische Analyse** | ruff + pyright + tsc | null Warnungen |
| **Protokoll-Matrix** | **5 Protokolle** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 Sprachen × 600+ Keys** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **Gebündelter Sidecar** | **6 Plattform-Binaries** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**Die E2E-Suite läuft in einer echten VS Code-Instanz gegen ein echtes Modell:**

> Aktiviert die gepackte Extension → startet den gebündelten Sidecar → speichert den Provider → streamt einen vollen Coach-Turn → generiert und verifiziert eine Trainingskarte → prüft, was das Webview **tatsächlich gerendert** hat → macht Screenshots → öffnet über Workspaces hinweg neu und stellt den Verlauf wieder her.

**Tests bezeugen ihre eigenen Grenzen:**
Jedes E2E-Szenario trägt `evidence: { realSidecar, limitation }` — **der Test erklärt selbst, was er nicht beweist.**

---

## i18n · Acht Sprachen

| Sprache | Code | Primär |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**Fallback-Kette:** Nutzereinstellung > VS Code `env.language` > `zh-CN` (Standard)

**6 oberflächenbezogene Overrides:** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` — Übersetzer:innen füllen nur die Oberflächen, die sie betreuen, **nicht die volle 600+-Key-Tabelle**.

Zentraler Code: `extension/webview/src/lib/i18n/copy.ts` (5.283 Zeilen)

---

## Danksagungen

> Trainer steht auf den Schultern von Riesen.

### 🏃 Laufzeitkern

| Projekt | Zweck | Warum unersetzlich |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | Lokales Sidecar-Framework | async + Pydantic + automatische OpenAPI-Docs |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI-Server | HTTP/1.1 + WebSocket + hohe Nebenläufigkeit |
| [Pydantic](https://github.com/pydantic/pydantic) | Datenvalidierung & Serialisierung | der 31-Felder-WorkbenchSnapshot läuft darauf |
| [httpx](https://github.com/encode/httpx) | Async-HTTP-Client | gesamtes Sidecar ↔ LLM-Gateway-Protokoll-Routing |

### 🤖 LLM-Protokolle

| Projekt | Zweck |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | OpenAI-/Anthropic-/Gemini-kompatibler Client (5-Protokoll-Routing) |

### 🧠 Training & Gedächtnis

| Projekt | Zweck |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS-Wiederholungsplanung nach Vergessenskurve · treibt `TrainingCardState` an |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | Vektorabruf für semantisches Gedächtnis (mit sentence-transformer-Fallback) |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF-Parsing (Tier-A-Vorschau in der Bibliothek) |
| [trafilatura](https://github.com/adbar/trafilatura) | Web-Content-Extraktion (Ressourcen-Ingest) |
| [markitdown](https://github.com/microsoft/markitdown) | Dokument-zu-Markdown-Konvertierung (Tier-B-Vorschau in der Bibliothek) |

### ⚛️ Frontend-Kern

| Projekt | Zweck |
|---|---|
| [React](https://github.com/facebook/react) | Sidebar-Workbench-UI |
| [Vite](https://github.com/vitejs/vite) | Build-Tool + Dev-Server |
| [Zustand](https://github.com/pmndrs/zustand) | Workbench-State-Management |
| [Zod](https://github.com/colinhacks/zod) | Typvalidierung zur Laufzeit |

### 🎨 Rendering

| Projekt | Zweck |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Markdown-Rendering |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | GFM-Erweiterungen (Tabellen, Task-Listen) |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | Math-Rendering |
| [Shiki](https://github.com/shikijs/shiki) | Code-Highlighting (VS Code TextMate-Grammatiken) |
| [Mermaid](https://github.com/mermaid-js/mermaid) | Diagramme & Flowcharts |
| [@tanstack/react-table](https://github.com/TanStack/table) | Tabellen für Bibliothek / Training-Queue |

### 📄 Vorschau

| Projekt | Zweck |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | DOCX-Rich-Rendering (Tier A) |
| PDF.js (gebündelt) | PDF-Rich-Rendering (Tier A) |

### 🧪 Testing & Qualität

| Projekt | Zweck |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | Server: 159 Dateien / 1.649 Fälle |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | Property-Testing (Planner / Evaluator / Scheduler) |
| [ruff](https://github.com/astral-sh/ruff) | Python-Linting + Formatierung (E/F/I/B, py312, 100 Spalten) |
| [pyright](https://github.com/microsoft/pyright) | Statische Python-Typprüfung |
| [TypeScript](https://github.com/microsoft/TypeScript) | Strict Mode, null Warnungen |
| [Playwright](https://github.com/microsoft/playwright) | E2E + Experience-Matrix mit 200 Szenarien |

### 📦 Paketierung & Verteilung

| Projekt | Zweck |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | Sidecar als Single-Binary-Freeze (6 Plattformen, Manifest-sha256) |

### 💡 Methodische Inspiration

| Projekt | Inspiration |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | Das ursprüngliche FSRS-Paper und die Referenzimplementierung |
| [obra/superpowers](https://github.com/obra/superpowers) | Coach-Disziplin nach „verpflichtenden Workflows statt Vorschlägen“ |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | Der Ehrgeiz, „alle Software agent-nativ zu machen“ |

### 🎨 Bildmaterial

| Projekt | Zweck |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | Jedes Bild in diesem README (siehe `assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md`) |
| DeepSeek offizielles Moe-Girl | Referenz für Chibi-Proportionen / Cel-Shading-Tendenz |
| Pieter Bruegel, *Der Turm zu Babel* | Referenz für die Links-rechts-Lager-Komposition des Ensembles |
| Rembrandt, *Die Nachtwache* | Referenz für den 7:1-Chiaroscuro-Kontrast |
| Studio Ghibli Charakterdesign | große Augen mit Dreipunkt-Glanzlichtern, zurückhaltende Mimik |

---

## Lizenz

[MIT](LICENSE)

---

## Trainer zitieren

Wenn Trainer deinem Workflow geholfen hat, zitiere es gern in deinem Blog / Paper / Vortrag:

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

**// Trainiere deine KI · Wachse mit deiner KI**

`v1.0.3` · Gemacht mit Kaffee, FSRS, 24 Pure Functions, 3.328 Tests und einem Herzen, das sich weigert, für dich Code zu schreiben.

</div>
