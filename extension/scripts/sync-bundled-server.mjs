#!/usr/bin/env node
// Mirror server/app into extension/bundled/server/app so the packaged sidecar
// always matches the server sources. The 7-pair integrity contract lives in
// server/tests/test_provider_source_integrity.py (SOURCE_PAIRS) and is a subset
// of this mirror.
import { cpSync, rmSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const extensionRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(extensionRoot, "..");
const source = join(repoRoot, "server", "app");
const target = join(repoRoot, "extension", "bundled", "server", "app");

if (!existsSync(source)) {
  console.error(`missing source tree: ${source}`);
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
cpSync(source, target, { recursive: true });
console.log(`mirrored server/app -> extension/bundled/server/app`);
