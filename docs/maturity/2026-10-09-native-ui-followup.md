# Native UI and installed-host follow-up — 2026-10-09

The T + coach-whistle icon is already on main. This follow-up fixes three
additional defects observed in the actual clean `28188fa3c1d786d3243c09a785d682148e2d1cc4`
macOS installation. It also adds bounded diagnostics for the remaining Linux
and Windows installed-host failures. Source verification and native acceptance
are separate gates; no formal Release has been created.

## Actual native findings and repairs

| Observed failure | Repair |
| --- | --- |
| Explicit Light produces a white background but actual shell text still inherits Code's dark-theme foreground. | The Trainer shell explicitly owns its semantic `--fg-0` foreground. Tests append the actual host root rule after the bundle and measure consumer colors and contrast, rather than checking tokens alone. |
| At an actual 340 px native sidebar width, saved-provider actions leave the model only 2 px wide and 343.75 px tall. | The canonical inner content and action group wrap; the provider list has a readable flex basis. The model and all controls remain available. |
| English Learning says “Current practice is complete” while the same restored card is still at Try 2/5 with Continue practice. | Empty active and return-pending card titles receive distinct in-progress copy in all eight languages. A real title stays authoritative; resolving or executing the action does not alter phase, evidence or card identity. |

Original failing native screenshots and computed DOM receipts are preserved in
`output/maturity/native-product-clean28188/`. Focused layout tests also retain
the original failures and an unsuccessful intermediate wrapper fix. The first
Learning regression failed before the fallback repair and passed afterward.

The clean-28188 native run already proved first connection auto-discovery,
actual catalog/connection/tool/stream probes, cancellation of a delayed model
list across a new session, restored technical focus in Chinese and English,
and ordinary three-destination navigation without another Sidecar launch or
provider request. Its owned folder-picker fixture exercised the real public
choose/adopt handlers and admission, but does not prove the native OS picker.
Its provider was a deterministic fixture, so these are infrastructure results.
The three failures above remain failures of that old package; the new source
requires a fresh committed package and installed native recheck.

## Source verification

- Full `npm run verify`: exit 0, including build/source sync, the complete
  extension suite, strict TypeScript, Ruff and whole-backend Pyright with zero
  diagnostics. Backend: **3,284 passed + 28 subtests**, 86.36 s and 53 dependency
  warnings. The elapsed time is one sample, not a claimed backend speedup.
- Full Playwright: **379 passed**, 1.2 minutes, on isolated port 4211.
- Focused native-root theme and provider-row browser checks: **14 passed**,
  covering Chinese/English theme ink at 340/460 px and Chinese/English/German
  provider controls at 299/340/460 px.
- Learning action regressions: **31 passed**, including all eight languages,
  active/return-pending empty titles, the original card action and stale-action
  rejection after completion.
- Actual language services report zero diagnostics for the two edited CSS
  files, the Learning TypeScript files and the focused browser-test files.
- Final related installed-host/provisioning/diagnostic regressions:
  **124 passed**, zero skipped. These include the actual compiled HTTP client
  against a local server, real HTTP 401 behavior, authentication rotation,
  immediate request execution and owned-process/symlink rejection. Synthetic
  process metadata checks are not native Windows startup acceptance.
- Refreshed strict performance probe: worst warm navigation p90 **38 ms**
  against a 100 ms budget; zero synthetic stream tasks above 50 ms. The previous
  sample was 37 ms. A single-machine difference of this size is noise, and this
  probe does not measure actual provider latency.

Full verification logs are in `output/maturity/native-ui-followup/`. The
tracked performance baseline was refreshed because provider geometry changed.

## Cross-platform installed-host facts

Ordinary [CI 37815164426](https://github.com/AI-yyf/trainer/actions/runs/37815164426)
passed for clean 28188. In the full
[cross-platform run 37815268063](https://github.com/AI-yyf/trainer/actions/runs/37815268063),
all three Server jobs and all three UI jobs passed. macOS packaging, isolated
installation and actual host checks passed: **27 executed checks**, with seven
screenshot checks explicitly skipped. Linux and Windows host acceptance remain
failed. Successful package, manifest and direct frozen-binary checks do not
establish actual extension-host acceptance.

Linux progressed through activation, restart, authenticated health, admission,
memory, resources, sandbox and language persistence, then stalled at provider
save until the ten-minute launcher timeout. A headless credential-service
problem is a hypothesis, not yet a demonstrated cause. The harness now collects
the official OSCrypt backend logs and a same-session SecretService presence
probe, and exercises the isolated driver's real SecretStorage store/get/delete
round trip with a bound per stage. It records booleans and step times and
redacts the synthetic diagnostic item. Trainer's public provider save remains
unchanged. No insecure password-store fallback or fake successful report is
introduced.

Windows' original official-Code extraction timed out. The single package-job
retry successfully extracted and verified official Code, installed the package
and exercised the native binary directly, then failed at the actual host's
twenty-second restart health boundary. Direct native smoke took less than
13.8 seconds including its other work; that does not justify merely increasing
the host timeout. An independent harness defect also omitted Windows instance
authentication even for a ready process. The actual startup cause still needs
bounded owned-launch and health facts.

The isolated Windows driver temporarily observes the installed package's real
authentication setter and retains the genuine HTTP client instance, without
reading or exporting its token. Original calls, arguments and results are
forwarded. Before each diagnostic request it requires the ready public state,
the actual owned executable/PID/parent/creation time/port from CIM, an observed
isolated launch, and a current client generation. Wrappers are restored on
completion. Startup receipts contain only bounded health outcome metadata,
safe launch arguments and environment-presence booleans. This instrumentation
does not establish a successful Windows launch, bypass authentication, or
change the production process manager or provider.
An unsuccessful public restart now stops the driver immediately, and the
launcher checks a failed driver report before fixture request totals, preserving
the original startup failure instead of masking it with a later assertion.

A new manual diagnostic scope runs only the selected platform's Package and
actual Host checks, requires host E2E to be enabled, and identifies itself as
partial. Push, PR and the default manual scope retain all nine jobs. Diagnostic
concurrency is separate from a full verification run. A passing partial run
cannot establish full cross-platform or release acceptance.

## Actual Remote-SSH and model boundary

The clean-28188 installed Remote-SSH run used the packaged frozen Sidecar and
the actual Linux companion on an owned 141s fixture. Exit 0/7, cancellation,
timeout, disconnect/reconnect, canonical URI and symlink boundaries, A/B
isolation, Return migration, repeated Return and two subsequent restarts were
checked. A direct read-only SQLite backup retains both original evidence IDs
and all five fields of the matching remote verification artifact. The older
unrelated evidence row remains unbound. Fixture provider responses do not prove
real-model teaching quality. Owned processes, fixtures and the added companion
were cleaned up; the user's existing window and project were preserved.

The latest real GPT-4o transport returned HTTP 402 `quota_exhausted` with a
localized recovery and no evidence. The requested twenty to thirty genuine
teaching journeys and real-model native training remain unaccepted until the
user supplies available quota or chooses another connection. No further paid
retries or purchases have been made.
