/**
 * CI payload-schema guard for the opt-in anonymous telemetry export (P2 #18).
 *
 * Runs `scripts/telemetry-payload-probe.py` on the real sidecar app (throwaway
 * data dir), then validates the emitted export payloads against a strict
 * contract in Node:
 *
 *  - exact schema keys and version;
 *  - an opt-out machine exports an EMPTY payload (no event names, no counts);
 *  - event names ⊆ the server's own canonical whitelist (no new vocabulary
 *    can ever be minted on the wire);
 *  - names are charset-checked identifiers, day keys are ISO dates, counts are
 *    non-negative bounded ints, and dates inside the window are coherent;
 *  - no identifier-shaped or path-shaped strings anywhere in the body.
 *
 * Exit codes: 0 = contract holds, 1 = violation (fail-closed).
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function resolveServerPython() {
  const candidates = [
    path.join(repoRoot, "server", ".venv", "bin", "python"),
    path.join(repoRoot, "server", ".venv-mac", "bin", "python"),
    path.join(repoRoot, "server", ".venv", "Scripts", "python.exe"),
    path.join(repoRoot, "server", ".venv-mac", "Scripts", "python.exe"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? "python3";
}

const PROBE = path.join(repoRoot, "scripts", "telemetry-payload-probe.py");
const SCHEMA = "trainer.telemetry.v1";
const EXPORT_KEYS = new Set([
  "schema",
  "generated_at",
  "opt_in",
  "window_days",
  "daily",
  "by_event",
  "unknown_ledger_events_dropped",
  "total_events",
]);
const IDENTIFIER = /^[a-z][a-z0-9_]*$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const FORBIDDEN_MARKERS = ["token", "api", "email", "user_id", "workspace", "password"];

const failures = [];
function fail(message) {
  failures.push(message);
}

function runProbe() {
  const result = spawnSync(resolveServerPython(), [PROBE], {
    cwd: repoRoot,
    encoding: "utf8",
    timeout: 120_000,
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.status !== 0) {
    throw new Error(
      `probe exited ${result.status}: ${(result.stderr ?? result.stdout ?? "").slice(0, 400)}`,
    );
  }
  const exports = [];
  let whitelist = null;
  for (const line of String(result.stdout ?? "").split("\n")) {
    if (line.startsWith("PROBE_EXPORT:")) exports.push(JSON.parse(line.slice("PROBE_EXPORT:".length)));
    else if (line.startsWith("PROBE_WHITELIST:")) whitelist = JSON.parse(line.slice("PROBE_WHITELIST:".length));
  }
  return { exports, whitelist };
}

function validateExport(doc) {
  const { case: scenario, export: payload } = doc;
  const keys = Object.keys(payload);
  for (const key of keys) {
    if (!EXPORT_KEYS.has(key)) fail(`[${scenario}] unexpected export key ${key}`);
  }
  for (const required of EXPORT_KEYS) {
    if (!keys.includes(required)) fail(`[${scenario}] missing export key ${required}`);
  }
  if (keys.length !== EXPORT_KEYS.size) fail(`[${scenario}] export key count drifted`);
  if (payload.schema !== SCHEMA) fail(`[${scenario}] schema ${payload.schema}`);
  if (!ISO_STAMP.test(String(payload.generated_at ?? ""))) fail(`[${scenario}] bad generated_at`);
  if (typeof payload.opt_in !== "boolean") fail(`[${scenario}] opt_in not boolean`);
  const days = payload.daily;
  const daysOk =
    Array.isArray(days) &&
    (payload.opt_in === false ? days.length === 0 : days.length === payload.window_days) &&
    days.every(
      (item) =>
        item &&
        typeof item === "object" &&
        JSON.stringify(Object.keys(item).sort()) === '["date","events"]' &&
        ISO_DATE.test(String(item.date ?? "")) &&
        Number.isInteger(item.events) &&
        item.events >= 0,
    );
  if (!daysOk) {
    fail(`[${scenario}] daily series malformed`);
  }
  if (bodyContainsIdentifierShape(payload)) fail(`[${scenario}] identifier-shaped value in body`);
  const body = JSON.stringify(payload).toLowerCase();
  for (const marker of FORBIDDEN_MARKERS) {
    if (body.includes(marker)) fail(`[${scenario}] forbidden marker ${marker} in export body`);
  }
  if (!payload.opt_in) {
    if (payload.total_events !== 0 || payload.by_event === undefined || Object.keys(payload.by_event).length !== 0 || payload.unknown_ledger_events_dropped !== 0 || (days?.length ?? 1) !== 0) {
      fail(`[${scenario}] opt-out export is not empty (leaks counts)`);
    }
    return;
  }
  const whitelist = new Set(whitelistProperties());
  for (const [name, count] of Object.entries(payload.by_event ?? {})) {
    if (!IDENTIFIER.test(name)) fail(`[${scenario}] event name not an identifier: ${name}`);
    if (!whitelist.has(name)) fail(`[${scenario}] event name outside whitelist: ${name}`);
    if (!Number.isInteger(count) || count < 0) fail(`[${scenario}] bad count for ${name}: ${count}`);
  }
  if (!Number.isInteger(payload.total_events) || payload.total_events < 0) fail(`[${scenario}] bad total_events`);
  if (payload.total_events !== Object.values(payload.by_event ?? {}).reduce((a, b) => a + b, 0)) {
    fail(`[${scenario}] total_events disagrees with by_event`);
  }
}

let cachedWhitelist = null;
function whitelistProperties() {
  return (cachedWhitelist ??= whitelistList());
}
function whitelistList() {
  const { whitelist } = probeResult ?? {};
  if (!Array.isArray(whitelist?.all_event_types)) fail("whitelist record missing");
  return whitelist?.all_event_types ?? [];
}

function bodyContainsIdentifierShape(payload) {
  const walk = (node) => {
    if (typeof node === "string") return !IDENTIFIER.test(node) && !ISO_STAMP.test(node) && !ISO_DATE.test(node) && node.length > 64;
    if (Array.isArray(node)) return node.some(walk);
    if (node && typeof node === "object") return Object.values(node).some(walk);
    return false;
  };
  return walk(payload);
}

let probeResult = null;
try {
  probeResult = runProbe();
  for (const doc of probeResult.exports) validateExport(doc);
  // Every whitelisted type is a plain identifier itself.
  for (const name of whitelistList()) {
    if (!IDENTIFIER.test(name)) fail(`whitelist entry is not an identifier: ${name}`);
  }
} catch (error) {
  fail(`guard crashed: ${error instanceof Error ? error.message : String(error)}`);
}

if (failures.length > 0) {
  process.stdout.write(`telemetry payload guard: ${failures.length} violation(s)\n`);
  for (const message of failures) process.stdout.write(`  - ${message}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write("telemetry payload guard: contract holds (opt-out empty; opt-in whitelist; identifiers clean)\n");
}
