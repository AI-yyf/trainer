#!/usr/bin/env node
// Mirror the sidecar bundle targets from server/ into extension/bundled/server/
// so the packaged sidecar always matches the server sources.
//
// The mirror contract (which files ship) has ONE source of truth:
// resolveSidecarBundleTargets().copyTargets in bundle-sidecar.mjs — the same
// list verify-package.mjs checks for byte-exact parity before any VSIX is
// built. This script mirrors every target so `npm run build` can never leave
// the bundled tree drifting from server sources (the integrity pairs in
// server/tests/test_provider_source_integrity.py are a subset of this).
import { cpSync, existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export async function syncBundledServer({
  extensionDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const bundleModule = await import(
    pathToFileURL(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "bundle-sidecar.mjs")).href
  );
  const { sourceServerDir, targetServerDir, copyTargets } =
    bundleModule.resolveSidecarBundleTargets({ extensionDir, repoRoot });

  if (!existsSync(sourceServerDir)) {
    throw new Error(`missing source tree: ${sourceServerDir}`);
  }
  for (const { source } of copyTargets) {
    if (!existsSync(source)) {
      throw new Error(`missing bundled source: ${source}`);
    }
  }

  rmSync(targetServerDir, { recursive: true, force: true });
  for (const { source, target } of copyTargets) {
    cpSync(source, target, { recursive: true });
  }
  return { sourceServerDir, targetServerDir, copyTargets };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  syncBundledServer()
    .then(({ copyTargets }) => {
      console.log(
        `mirrored ${copyTargets.length} bundle targets from server/ -> extension/bundled/server/`,
      );
    })
    .catch((error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    });
}
