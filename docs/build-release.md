# Build, version, and release contract

`extension/package.json` owns the Trainer product version. The root workspace
manifest and root/extension npm lock metadata carry that same version. README
source badges and citation metadata describe the checked-out source; download
links use the latest **published** Release. A source version or tag does not prove
that an accepted release exists.

The Python distribution (`trainer-sidecar`, currently 0.1.0) and Remote Workspace
Companion (currently 1.0.0) have independent component versions. They do not
describe the product version. Companion interoperability is checked through
protocol v2 capabilities and the packaged Companion's own manifest/entrypoint.

Run `npm run verify:version` before changing version metadata or packaging.
Release tag `vX.Y.Z` must match the product manifest exactly.

## Frozen dependencies

Node dependencies come from the checked-in npm locks. Python dependencies come
from the existing universal `server/uv.lock`; `--frozen` bootstrap requires that
lock and uv and never falls back to resolving open-ended pip ranges. Ordinary
non-frozen development bootstrap remains available.

```sh
npm ci
uv sync --project server --frozen --extra dev --extra build --python 3.12
npm run check
npm run package:vsix
```

CI uses uv 0.12.10. Native packaging requires the locked PyInstaller 6.22.2 and
uses VSCE 4.0.0. A missing or different PyInstaller blocks packaging and gives the
frozen environment command; the build never silently installs a different tool.

Dependency versions are frozen. Native binaries and ZIP containers are **not
claimed to be byte-identical across rebuilds**: OS libraries, interpreter builds,
packaging timestamps, and toolchains affect those bytes. Source hashes, resolved
Python package versions, target identity, and archive hashes make each artifact
traceable and reproducible from its recorded inputs.

## One packaging dependency chain

`package:vsix` owns the complete preparation chain on its native platform:

```text
product/tag version gate
  → TypeScript extension build + current Python source mirror
  → production webview build
  → native Sidecar + source/lock manifest
  → current Sidecar source/lock mirror
  → Remote Companion TypeScript build → Companion VSIX → bundled copy
  → foreign-target cleanup + packaged symlink materialization
  → actual bundled Sidecar health/runtime smoke
  → input parity/manifest/Companion archive verification
  → VSCE target-specific VSIX
  → final archive target/required-entry verification
  → .vsix.build.json with source commit, dirty state, versions and hashes
```

No caller needs a historical native binary or Companion artifact. Nightly and
cross-platform jobs install the locked build dependencies and use this same
entrypoint. VSCE's automatic prepublish hook rechecks prepared inputs instead of
starting a second native build. A direct VSCE invocation runs the full preparation
hook.

`TRAINER_REUSE_VERIFIED_SIDECAR_BINARY=1` is an explicit local shortcut. It is
accepted only if the native executable exists and its manifest matches the
current Python source **and** dependency lock. Workflows use the default fresh
build. Missing files, corrupt archives, outdated Companion versions, source
drift, foreign runtimes, or failed runtime smoke stop packaging.

## Release gates and evidence

Formal publishing depends on all native build jobs. Ruff, Pyright, TypeScript,
extension regressions, backend regressions on **all three release platforms**,
browser teaching journeys, and actual frozen runtime smoke are blocking. Windows
and macOS pytest failures cannot be converted into successful platform probes.

Each job uploads its exact target VSIX and `.vsix.build.json`. Before publishing,
`scripts/verify-release-artifacts.mjs` requires exactly `darwin-arm64`, `linux-x64`,
and `win32-x64`, with matching tag/product version, exact Git source commit, clean
source state, archive size and SHA-256, target metadata, required runtime entries,
and recorded Python build environment. Reports and generated checklists are
evidence only for the checks that actually ran.

Preview fixtures establish interaction/layout behavior. Scripted model responses
establish deterministic runtime integration. Neither proves real-model teaching
quality or a real Remote-SSH window. Native installation, live model journeys,
and Local Brain + Remote Hands acceptance must be recorded separately; a skipped
check is never a pass. See `docs/remote-ssh-acceptance.md` and the current maturity
acceptance record for those results.

The cross-platform workflow runs build, test, and native packaging on pushes and
pull requests. To require installed VS Code acceptance on all three hosted
platforms, dispatch it on the intended source ref with `run_vsix_host_e2e=true`:

```sh
gh workflow run cross-platform-verify.yml --ref main -f run_vsix_host_e2e=true
```

This mode provisions Microsoft VS Code 1.127.0 into an isolated runner temporary
directory. Its official update metadata must contain the pinned version, source
commit, and SHA-256; archive bytes are verified before extraction, and the CLI's
version/commit must match. Linux uses Xvfb when no display is present. Both the
isolated installation/runtime smoke and installed host journeys reuse the exact
VSIX already built and uploaded by that job. `trainer-installed-host-<runner>`
artifacts retain Code provenance, install output, the host report, and available
screenshots even when a host journey fails. Native window capture currently runs
on Windows; macOS/Linux report explicit capture skips while behavior checks run.
The host harness exercises activation and basic
flows through the installed extension and native Sidecar with a deterministic
local provider; it does not establish live-model teaching quality.

Ordinary push/PR jobs still record an explicit manual host gate. A dispatch that
requests host acceptance fails when provisioning or host capability is absent;
it does not convert missing support into a successful skipped check. Python
dependencies are cached by uv only, since frozen installation never populates
pip's cache.

Generating or downloading an artifact does not authorize publishing. No formal
Release should be created while a required gate remains unresolved.
