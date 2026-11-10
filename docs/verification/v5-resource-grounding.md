# V5 resource grounding — compact citation and open-at-anchor

Date: 2026-11-10

## Product decision

A grounded coach reply must show **where the knowledge came from**, not paste the
resource into the transcript. The transcript now renders one inline source chip
per real passage:

- `REF` / `WEB` + resource title + paragraph anchor;
- the whole chip is the **Open source** action and opens the canonical Markdown
  in the existing full-width editor at the cited line (web chips open the
  fetched URL);
- citation provenance (resource ID, version ID, content hash, anchor,
  citation ID) stays in the tooltip and `data-*` attributes, not in a visible
  block.

The full passage stays in the resource and in the tool result. It is no longer
copied into the visible message or the message part payload.

## What changed

| Area | Change |
| --- | --- |
| `server/app/llm/resource_message_parts.py` | Successful `read_resource_excerpt` and `search_resources` results project to `citation` parts only; no `resource_excerpt` body and no snippet payload. |
| `server/app/llm/tools.py` | Read results carry version/hash/location/anchor, a version-scoped citation fallback, and stale-version truth. Registry reads are scoped through the workspace repository. |
| `server/app/resources/search.py`, `service.py` | Search hits carry version/hash/location and a `stale` flag when the indexed version is older than the resource head. |
| `shared/src/protocol.ts` | One citation representation; removed the unused `resource_excerpt` part. |
| `extension/webview/.../CoachMessageParts.tsx` | Compact `REF` resource card; no passage body; `Open source` opens the canonical resource at `location.start_line`. |
| `extension/webview/src/app/App.tsx` | When a verified tools-capable provider and a non-empty library exist, normal Coach turns enable the agent loop so the model can search/read its own library. |
| `server/app/api/routers.py`, `provider_service.py` | Loopback providers can run the tool loop and streaming without an API key, matching the host's existing local-service save behavior. |
| `server/app/api/router_support.py` | Strict teaching-marker focus heuristics stay separate from the broader automatic library probe, so a probe never changes the turn focus/scenario. |

## Verification

### Passed — deterministic, installed VS Code GUI

`node scripts/verify-resource-grounding-gui.mjs`

The script installs the packaged VSIX into an isolated VS Code profile, imports
a Markdown resource through the real host command, runs a loopback
OpenAI-compatible fixture provider (tools + streaming verified), sends a normal
Coach message, then checks:

- the transcript shows one inline source chip with the real resource ID,
  version, anchor and citation ID; the session example resolves to `¶h2@7`,
  the line that actually contains the requested terms, not the file start;
- the transcript does **not** contain the passage body;
- `Open source` opens the canonical Markdown in an editor tab at the cited
  line (`Ln 7` in the heading/line precision run);
- after the resource is deleted, the same chip becomes inert (`资料已删除`,
  no arrow, no button) instead of opening a dead source.

Evidence: `output/resource-grounding-gui/2026-11-10T05-53-45-524Z/report.json`
(`ok: true`; screenshot `01-grounded-citation.png`, `02-open-full-resource.png`).

This is real VS Code + real extension + real sidecar + real GUI evidence, but
the provider is a deterministic loopback fixture, **not** real-model quality
evidence.

### Passed — browser preview

`npx playwright test e2e/trainer-resource-grounding.spec.js` — **3/3 passed**

- the inline chip renders, with no `figure[data-resource-excerpt]`, no passage
  body and no visible provenance block in the message;
- clicking the chip posts `resource/open` with the real resource ID and line;
- a fetched web source renders as the same chip with a real `https://` link
  (`data-reference-origin="web_research"`);
- when the current resource version differs from the citation version, the chip
  becomes `资料已更新`, drops the open arrow/action, and its tooltip shows the
  current version.

### Passed — automated regression

- `npm run check` (webview + extension TypeScript).
- `node --test extension/tests/typedMessagePartsShared.test.js`.
- `server/.venv/bin/python -m pytest tests/test_resource_message_parts.py`.
- Targeted `test_session_agent_e2e.py` compact-citation, auto-library and
  cross-workspace tests.
- Full server suite: **4043 passed, 28 subtests passed**.
- Full extension suite (`node --test extension/tests/*.test.js`): passed.
- Two-source comparison: one turn reads two resources and renders two distinct
  `library_read` chips (resource/version/anchor/citation all present, no text).

### Passed — installed GUI resource-deletion invalidation

`node scripts/verify-resource-grounding-gui.mjs` (report `ok: true`)

After the chip was verified and its source opened at `Ln 7`, the driver deleted
the resource through the real host command. The same chip re-rendered as
`资料已删除`, lost its arrow and button, and stayed visible as an honest
historical reference. Delete result: `已移入回收站 1 份资料。`

### Passed — live network research (no model key needed)

`cd server && .venv/bin/python ../scripts/live-web-grounding-probe.py`

The real controlled search/fetch path returned three fetched public sources with
URLs and `fetched_at` timestamps. The same projection used by Coach produced
three compact `WEB` citations with `https://` links and no pasted page body.
Evidence: `docs/verification/v5-web-grounding.json` (`ok: true`).

This proves the network acquisition + citation projection. It does not prove
model judgment about which source is relevant; that needs the real provider.

### BLOCKED — real provider

No provider API key is present in the process environment, and the installed
profile has no saved provider. The real gateway/real-model resource-grounding
journey was **not executed** in this round. Do not mark it PASS. The loopback
fixture proves transport, tool loop, UI and open-at-anchor behavior only.

## Defects found and fixed during this round

1. **Cross-workspace resource read (P0).** `read_resource_excerpt` resolved IDs
   from the process-global in-memory registry before the workspace repository.
   A workspace B turn could read workspace A's resource by ID. Fixed by making
   the durable workspace-scoped repository authoritative; the registry is a
   fallback only for embedded/test runtimes with no repository lister. Regression
   test: `test_resource_grounding_never_crosses_workspace_boundaries`.
2. **Loopback provider blocked without an API key (P1).** Provider test could
   pass, but Coach streaming/tools rejected the same local provider because
   `has_api_key` was required. Fixed in `ensure_coach_provider_ready`,
   `ensure_agent_tools_ready`, `ensure_streaming_ready` and
   `supports_executable_tools`; remote providers still require a key.
3. **Normal Coach turns could not use the agent loop (P1).** The webview only
   requested tools for plan/resources/file-reference turns. With a verified
   tools provider and a non-empty library, normal Coach turns now request the
   agent loop so the model can search/read its own library. Empty libraries stay
   on the cheap non-agent path.
4. **Broad library probe changed focus/scenario (P0 regression).** Broadening
   the lookup heuristic affected `resolve_turn_focus_hint`, producing focus
   `「好」` for acknowledgement turns. Split the strict focus heuristic from the
   broad auto-probe; the probe only decides whether to run one local search.
5. **Transcript duplicated the resource (P1 UX).** The first implementation
   rendered the full chunk body inline. Replaced with the compact citation
   surface described above.
6. **Search citation opened the wrong section (P1).** `_enrich_search_locations`
   picked the earliest occurrence of any query term, so a common word such as
   `lock` in the first paragraph beat `finally/release/strand` in the boundary
   section. It now scores sections first (heading match + distinct-term
   coverage), then the strongest line inside the winning section. This also
   prevents a footnote that quotes every term from stealing a citation from the
   matching section. Regressions:
   `test_best_match_position_prefers_distinct_term_coverage`,
   `test_best_match_position_prefers_the_matching_section_over_a_footnote`,
   `test_docx_becomes_canonical_markdown_and_is_searchable`; GUI evidence opens
   `¶h2@7` at `Ln 7`.
7. **Old citation stayed live after resource deletion/update (P1).** Chat
   citation parts were static; deleting or replacing the resource left an
   apparently clickable chip. `CitationPartView` now compares the cited
   resource/version/hash with the current library records passed from App.
   Missing resources become `资料已删除`; version/hash changes become
   `资料已更新`; both are inert (no arrow, no button). Installed-GUI evidence:
   deletion step in `output/resource-grounding-gui/2026-11-10T05-53-45-524Z/report.json`;
   deterministic update scenario: `resource-grounding-updated` in
   `e2e/trainer-resource-grounding.spec.js`.
8. **Mixed-language principle patch (P1).** An English `why_it_matters` note
   extracted from an English resource was pasted into a zh-CN reply as English
   prose. `coaching_patches` now only appends reason/action text in the reply's
   visible script; the source title can still stay as a technical identifier.
   Regression test: `test_coaching_reply_does_not_paste_english_principle_prose_into_chinese`.

## Remaining gaps

- Real provider (gateway/model) resource-grounded teaching is **NOT_EXECUTED**
  because no key is available in this environment.
- Real web fetch/search was not executed against the public internet in this
  round; the web-source card and URL link are deterministic UI evidence only.
- PDF/EPUB page anchors, images, formulas and tables were not re-verified in the
  installed GUI this round; server provenance fields exist but need a real
  document fixture.
- Cross-session reading-position resume and multi-document comparison remain to
  be exercised in the next round.
- The loopback fixture is test-only; it is not a substitute for real model
  teaching quality or source-relevance judgment.

## PDF / EPUB page-level citations and rendered assets

### Passed — installed GUI PDF

`GROUNDING_GUI_FORMAT=pdf node scripts/verify-resource-grounding-gui.mjs`

- Two-page PDF with an embedded image and a formula line.
- Search resolved the second-page passage to `¶page2@11`.
- Chip click opened the canonical Markdown at `Ln 11` (the page-2 marker line).
- Canonical content checks: `<!-- page: 2 -->`, a qualified image ref, and the
  formula text.
- Markdown preview rendered the image and the page text.
- Evidence: `output/resource-grounding-gui/2026-11-10T06-12-48-696Z/report.json`
  (`ok: true`, screenshot `04-format-preview.png`).

### Passed — installed GUI EPUB

`GROUNDING_GUI_FORMAT=epub node scripts/verify-resource-grounding-gui.mjs`

- Two-chapter EPUB with a table, an embedded image and MathML.
- Search resolved the Foundations passage to `¶h1@3`; chip click opened the
  canonical Markdown at `Ln 3`.
- Canonical content checks: Markdown table row, qualified image ref, `$E = m c 2$`.
- Markdown preview rendered the table, the image, and a KaTeX formula
  (`katex=1` in the measured facts).
- Evidence: `output/resource-grounding-gui/2026-11-10T06-15-47-824Z/report.json`
  (`ok: true`; screenshots `04-format-preview.png`, `05-format-formula.png`).

### Fixed while verifying

1. **EPUB never entered the canonical Markdown pipeline.** `.epub` was not
   canonicalizable, so it had no canonical body, page/chapter anchors, tables or
   images. Added `epub-v1`: spine order, headings, paragraphs, lists, Markdown
   tables, extracted images and MathML-to-`$...$` text.
2. **Canonical image references were broken.** Assets are stored at
   `markdown/assets/<resource_id>/<file>` but Markdown refs pointed at
   `assets/<file>`, so the preview showed broken images. `build_canonical_document`
   now qualifies every asset ref with the resource id; the artifact test asserts
   the stored ref resolves.
