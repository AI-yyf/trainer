# Installed follow-up — 2026-10-09

The T + coach-whistle mark is integrated into main at
`576fd9f1b3be87dc918fea6c4fa728b3696991a0`. Its clean macOS artifact was
115,246,944 bytes, SHA-256
`c3fbae188a5ac1909eb143635ea04d93bec4008850f5a262e2cf58c4aae62103`.
That installation exposed the defects below; it is not final native acceptance.
Original failures and fixture data are retained in ignored `output/maturity/`.

## Actual findings

| Finding | Cause and scope |
| --- | --- |
| A Return evidence row loses its remote artifact after restart and persistence | The artifact was an allowed extra field, but structured restore retains only declared model fields. Pre-Return restart coverage did not detect this. |
| Task Details hides the restored card's English technical focus | The language filter rejected a real card fact, and a formal-plan chrome gate hid an independent card's focus in either language. Card ID, title and phase restored correctly. |
| Selecting Light in the native Appearance setting leaves the UI dark | The host theme always wins, and semantic colors still read injected VS Code tokens before fallback tokens. Native computed background stayed `#181818`. |
| Windows host capability rejects an already provisioned, runnable Code CLI | The CMD probe and its dispatcher omit verbatim argument handling and escape the quoted path twice. |
| Linux installed-host E2E times out without a final driver report | Installation, frozen Sidecar health and manifest checks passed. The ten-minute launcher timeout failed; deleted temporary logs prevented diagnosis. This is not a passing Linux host result or a proven product root cause. |

The native Remote-SSH run used the installed frozen Sidecar and an owned Linux
fixture on 141s. Actual exit 7 and exit 0 runs, Reflect/Return, disconnect during
a real process, reconnect and A/B project isolation were exercised. A fixture
provider generated the card, so these are infrastructure results, not evidence
of real model teaching quality. After A/B reopening, direct SQLite inspection
revealed the artifact loss above.

## Scoped repairs and proof

`EvidenceItem.verification_artifact` is now an optional declared field, without
broadening restore filters. A missing old field is recovered only from matching
persisted trusted facts: validated handoff/latest artifacts must agree, the
completed card, workspace, summary and source must match, and exactly one row
must fall between the original verification and Return timestamps. Existing
IDs, timestamps, counts, handoff and other fields are preserved. Ambiguous,
older, unverified or mismatched rows remain unbound.

Backend regressions exercise Return, two subsequent restarts, repeated Return,
self-report replay and direct SQLite persistence. The root also loaded the
actual damaged native export: the one matching row recovered its original five
artifact fields, the older unrelated row stayed unbound, and a second restore
was stable. This source-only check did not modify the live native database.

The Windows CLI probe passes verbatim arguments through both layers. Behavior
checks fail when either layer is removed. Failed host launches now preserve
bounded isolated Code logs, launch status/stdout/stderr and driver entry-point
metadata before cleanup, with credential redaction and outside-profile symlink
rejection. The timeout and mandatory successful driver report remain intact.

The current card retains its technical focus without a formal plan and in a
different interface language. Existing stale-plan/coach/memory isolation stays
enforced. Explicit Light/Dark changes only Trainer semantic variables; Auto
removes those overrides and follows the live VS Code theme. A typed verified
training return gets a localized result title in all eight languages. Its
original summary remains in evidence disclosure, including after adoption;
the adoption action keeps the same evidence ID.

The host harness resolves report/artifact paths before changing child cwd and
also writes bounded name/state/time progress. A missing final report alone
cannot establish whether the driver never activated or stalled at a later step.

## Source verification

- Full `npm run verify`: exit 0, including build/source sync, complete extension
  tests, strict TypeScript, Ruff and whole-backend Pyright (zero diagnostics).
  Backend: **3,284 passed + 28 subtests**, 158.76 s, 53 dependency warnings.
- Full Playwright on isolated port 4199: **366 passed**, 1.3 minutes. An extra
  two-language focused run verifies that stale plan/coach/learner/memory facts
  cannot replace the restored card's exact focus or ID.
- Product focused Node checks: **59 passed**; related browser checks:
  **26 passed**; actual TypeScript Language Service: five files, zero diagnostics.
- Expanded artifact/admission/restore backend regressions: **52 passed**.
- Cloud harness/provisioning/diagnostics regressions: **80 passed**. Synthetic
  failed launch/activation probes remain explicitly failure-path tests.
- Refreshed strict performance probe: zero stream tasks above 50 ms; worst
  warm navigation p90 **37 ms** against a 100 ms budget. This is a synthetic,
  single-machine sample and does not measure upstream model latency or establish
  a general speedup.
- Source/bundled parity: **155 inputs**, SHA-256
  `b861323d5ca24f6d48d41642c2e1bf546fa3566182933df04660c8c7612eabe9`.

Logs are in `output/maturity/installed-followup-final/`. The first unsuccessful
verification is preserved as `verify.initial-failed.log`: two source guards
located declarations using the obsolete formal-plan gate. Their declaration
anchors now follow variable names; all forbidden stale-fact assertions remain.
The fresh committed-source package, native reinstallation and next cloud run
are separate remaining gates at this integration.

## Cloud and real-model boundary

The completed clean-576 dispatch is
[37809970150](https://github.com/AI-yyf/trainer/actions/runs/37809970150):
all three server jobs and all three UI jobs passed. macOS packaging, installation
and actual installed-host E2E passed. Windows and Linux package jobs failed at
the specific acceptance steps described above. Ordinary
[CI 37809526756](https://github.com/AI-yyf/trainer/actions/runs/37809526756)
passed. A workflow's successful packaging step is not host acceptance.

One post-repair real GPT-4o agent transport request returned HTTP 402 with
`stop_reason=quota_exhausted`, a localized recovery instruction and no evidence.
Twenty to thirty real teaching journeys and real-model native training remain
unaccepted pending available quota or a user-selected replacement connection.
No formal Release has been created.
