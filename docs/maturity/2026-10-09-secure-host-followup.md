# Installed task focus and secure host follow-up

This round follows clean `fbb9b88f7278d6c73f04d6ddd5155fb2d43d064a`.
It preserves the accepted T/whistle icon and the three primary destinations.
It changes one training presentation rule and the isolated native-test harness;
the production Sidecar, provider, process manager and evidence model are unchanged.
No formal Release is created.

## Actual installed UI findings

The clean-fbb darwin-arm64 package is 115252709 bytes, SHA256
`462c7f1f10ad614eed23b052027bab17f52f2e7abad12bfbe6867ad728c7750e`.
Its build receipt identifies clean fbb source and the unchanged 155-file Sidecar
snapshot `b861323d5ca24f6d48d41642c2e1bf546fa3566182933df04660c8c7612eabe9`.
All 1595 installed artifact files matched, with VS Code's package-management
metadata checked separately. Package checks establish artifact identity, not
teaching quality or every native interaction.

In the actual owned VS Code window, twelve theme conditions passed
(Chinese/English, 340/460 pixels, Light/Dark/Auto), as did six saved-provider
layout conditions (Chinese/English at 299/340/460 pixels). The model remained
readable and every toolbar control remained inside its bar and reachable by
real hit testing. English Learning displayed the in-progress practice title;
Continue returned to the same card in Try 2/5. Seven ordinary navigation visits
and Continue preserved the Sidecar PID and all provider request counts.

Switching to Chinese exposed a real remaining defect: Task details displayed
the localized conversation summary instead of the selected card's exact
`workspace_id isolation` focus. Session, card, attempt and phase remained
unchanged; the evidence queue stayed empty and no capability was promoted.
The actual failed screenshot and state remain in
`output/maturity/native-product-cleanfbb9b88/`, including
`acceptance-findings.md` and `chinese-focus-failure-facts.json`.

The cause was precedence in `App.tsx`: language-aligned coaching/learner text
won before the identity-matched card fact. The card's focus now wins whenever
its identity matches the active training card. Language-aware contextual text
remains a fallback when no matching card fact exists. This changes displayed
information, not training identity, transitions, verification or persistence.

Four preview regressions cover both languages and recovered/non-recovered
states with unrelated same-language summaries, then leave and resume the same
card. Two failed before the fix; all four pass afterwards. Full browser
regression passes 381/381. Strict TypeScript and actual TypeScript Language
Service checks pass; the edited JavaScript receives syntax/module diagnostics,
with `checkJs: false` recorded explicitly. A fresh installed package and native
Chinese/English recheck are still required for this source change.

## Linux: demonstrated credential-service failure

The automatic push verification for fbb passed all nine jobs:
[run 37823107761](https://github.com/AI-yyf/trainer/actions/runs/37823107761).
Its actual installation and extension-host checks were explicitly skipped.
The separately requested Linux host diagnostic
[run 37823166295](https://github.com/AI-yyf/trainer/actions/runs/37823166295)
failed and is retained as failed.

That actual Code session had no D-Bus session address or Secret Service owner.
Official OSCrypt output selected `BASIC_TEXT`, reported encryption unavailable,
and prompted because an OS keyring could not be identified. The isolated
driver's genuine SecretStorage store timed out after 15005 ms, before Trainer's
public provider save. This demonstrates a runner credential-service problem;
it does not demonstrate a provider-save defect or justify a longer timeout.

The Linux test launcher now prepares an owned fresh D-Bus/Xvfb session with
private XDG directories and a foreground GNOME Secret Service daemon. A random,
nonempty password is sent only through stdin. Admission requires the exact
owned daemon, an unlocked persistent default collection, a genuine private
store/read/delete round trip and GNOME's encrypted keyring file format.
Only that prepared session selects `gnome-libsecret` in Code. The helper removes
its owned processes and temporary scope; it preserves HOME and existing user
keyrings. Trainer's public SecretStorage save and original host deadlines remain
unchanged. Helper tests do not establish native Linux acceptance; a new cloud
run must exercise the real backend and public save.

## Windows: bounded identity diagnostics

The requested Windows diagnostic
[run 37823172005](https://github.com/AI-yyf/trainer/actions/runs/37823172005)
is also retained as failed. Its actual public Sidecar restart reached ready in
3873 ms and the real Trainer log records successful health. The subsequent
driver probe failed its identity fence in 3 ms. The earlier twenty-second
startup failure was not reproduced and is not claimed resolved.

The harness now compares canonical Windows paths using Windows case semantics
and requires a unique already-loaded HTTP client module. Missing or ambiguous
cache identity fails closed. It observes the genuine authentication setter's
call count without reading or exporting its token, delegates original calls,
and restores wrappers. Safe stage receipts identify whether failure occurred
at launch, canonical path, CIM PID/parent/image/command, current state or the
authenticated request. No CIM output, token or response body is exported.
These changes preserve all existing process, workspace and generation fences.
The exact cloud failure remains unaccepted until the new stage receipts and
installed host run confirm it.

## Diagnostic archive integrity

The original Linux `host-failure/diagnostics.json` is invalid JSON because
redaction ran over an already-serialized JSON string and consumed escaped log
syntax. The original 317905-byte file remains untouched, SHA256
`0fc4b23ce37d0b19b7a5a94e08443610ad73070b7d933c4d62ea8cd478459b1b`.
New capture redacts string values recursively before serialization, preserving
field structure and scalar types without mutating the input. The actual escaped
log shape now parses in a regression; the old failure is not rewritten.

## Performance and acceptance boundary

Final `npm run verify` passes: build, strict TypeScript, complete extension
tests, Ruff, Pyright (zero diagnostics), 3284 backend tests and 28 subtests.
The backend suite took 86.15 seconds and reported 53 dependency warnings.
Linux helper behavior tests pass 16/16, with its related checks 67/67;
Windows/diagnostic related checks pass 127/127. These sets overlap their
respective full extension suite and are not added together as independent
coverage. Actual JavaScript Language Service diagnostics are zero with
`checkJs: false`; syntax, YAML parsing and `git diff --check` pass. The final
ten edited/new files contain zero matches for the private test API key.

The refreshed strict probe observes worst warm-navigation p90 37 ms and zero
streaming long tasks over 50 ms. The previous sample was 38 ms; this difference
is ordinary single-sample noise and is not claimed as a speed improvement.
The tracked baseline records this source round.

The previous actual Remote-SSH run at clean 28188 remains scoped to its exact
package and unchanged backend bytes. Its cancellation, timeout, disconnect,
reconnect, isolation and persisted remote artifact facts remain valid; it is not
relabeled as a native run of this newer UI.

Read-only OpenRouter credit verification at 2026-10-08T18:22:05Z returned zero
available credits. No further paid retries or purchases were made. The required
twenty to thirty genuine teaching journeys remain unaccepted. Preview fixtures,
scripted providers, native package checks and actual SSH infrastructure cannot
substitute for that teaching evidence.
