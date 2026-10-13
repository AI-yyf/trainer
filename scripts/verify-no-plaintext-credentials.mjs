#!/usr/bin/env node
// Deterministic plaintext-credential gate.
//
// Scans tracked source scopes for credential-shaped literals and plaintext
// credential transport. Exits non-zero on any violation. Findings print
// `file:line [rule]` ONLY — never the matched value.
//
// Synthetic-fixture convention (documented allowlist): this repository's test
// fixtures use descriptive all-lowercase, hyphen-separated placeholder values
// (e.g. `sk-test-...`, `sk-fixture-...`, `Bearer test-key`) and explicit
// FAKE/redacted markers. Random-looking mixed-case/digit values are treated as
// suspected real credentials. Example/placeholder hosts are allowed
// (localhost, 127.0.0.1, example.com, *.invalid).
//
// Run: node scripts/verify-no-plaintext-credentials.mjs
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const SKIP_DIR_NAMES = new Set([
  "node_modules",
  ".git",
  ".venv",
  ".venv-mac",
  "dist",
  "__pycache__",
  ".zcode",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  "coverage",
  "test-results",
  "playwright-report",
  "htmlcov",
  "artifacts",
  "out",
  // Gitignored local runtime state (never part of the committed deliverable).
  ".trainer",
  "output",
  "tmp",
]);

// Binary/native artifacts never carry reviewable source text.
const SKIP_PATH_PREFIXES = [
  "extension/bundled/bin/",
  "extension/bundled/remote/",
  "extension/dist/",
];

const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".icns",
  ".woff", ".woff2", ".ttf", ".otf", ".eot",
  ".pdf", ".zip", ".vsix", ".gz", ".tgz", ".jar",
  ".dylib", ".so", ".dll", ".node", ".exe", ".bin", ".wasm",
  ".dat", ".db", ".sqlite", ".pyc", ".pyo", ".class", ".map",
]);

const MAX_FILE_BYTES = 2 * 1024 * 1024;

const ALLOWED_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  "example.com",
  "example.org",
  "example.net",
]);

function isAllowedHost(hostname, { allowSingleLabel = false } = {}) {
  const host = (hostname ?? "").toLowerCase();
  if (!host) return true; // relative URL / no host
  if (ALLOWED_HOSTS.has(host)) return true;
  if (host.endsWith(".invalid") || host.endsWith(".example") || host.endsWith(".test")) return true;
  // Single-label hosts (`http://test`) are the standard httpx/requests test
  // idiom and are not routable in practice; allowed for endpoint assignments.
  if (allowSingleLabel && !host.includes(".")) return true;
  return false;
}

// A value is an accepted synthetic placeholder when it is either an explicit
// marker word value, or a descriptive all-lowercase hyphen/digit sequence
// (`sk-test-n...`, `sk-bundled-stream-secret`). Real keys are mixed-case
// random strings and never match this shape.
function isSyntheticPlaceholder(rest) {
  const value = rest.trim();
  if (!value) return true;
  if (/^(test|fake|dummy|sample|example|placeholder|redacted|fixture)/i.test(value)) return true;
  if (/^(xxx+|\.\.\.|\*+|\$\{)/i.test(value)) return true;
  return /^[a-z][a-z0-9]*(-[a-z0-9]+)+$/.test(value) || /^[a-z][a-z0-9]{5,}$/.test(value);
}

function looksRandomSecret(value) {
  const v = value.trim();
  if (v.length < 24) return false;
  if (!/^[A-Za-z0-9+/=_.-]+$/.test(v)) return false;
  const hasUpper = /[A-Z]/.test(v);
  const hasLower = /[a-z]/.test(v);
  const hasDigit = /[0-9]/.test(v);
  return hasUpper && hasLower && hasDigit && !/^[A-Z0-9_]+$/.test(v);
}

const SK_VALUE = /\bsk-[A-Za-z0-9_-]{16,}/g;
const BEARER_VALUE = /\bBearer\s+([A-Za-z0-9._~+/=-]{16,})/g;
const JWT_VALUE = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b/g;
const CREDENTIAL_ASSIGNMENT =
  /(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd)\s*[:=]\s*(['"])([^'"]{12,})\1/gi;
const HTTP_CREDENTIAL_QUERY =
  /http:\/\/([^/"'\s]+)[^\s"']*[?&](?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|key)=/gi;
const HTTP_BASE_URL = /\b(?:base[_-]?url|endpoint|provider[_-]?url|api[_-]?url)\b[^\n]{0,40}?["'`]?(http:\/\/[^"'`\s)]+)/gi;

function lineViolations(line, lineNumber, findings) {
  let match;
  SK_VALUE.lastIndex = 0;
  while ((match = SK_VALUE.exec(line)) !== null) {
    const rest = match[0].slice(3);
    if (!isSyntheticPlaceholder(rest)) {
      findings.push({ lineNumber, rule: "sk-key-literal" });
    }
  }
  BEARER_VALUE.lastIndex = 0;
  while ((match = BEARER_VALUE.exec(line)) !== null) {
    if (!isSyntheticPlaceholder(match[1])) {
      findings.push({ lineNumber, rule: "bearer-literal" });
    }
  }
  JWT_VALUE.lastIndex = 0;
  while ((match = JWT_VALUE.exec(line)) !== null) {
    if (!/fake|fixture|example|dummy|sample|test/i.test(match[0])) {
      findings.push({ lineNumber, rule: "jwt-literal" });
    }
  }
  CREDENTIAL_ASSIGNMENT.lastIndex = 0;
  while ((match = CREDENTIAL_ASSIGNMENT.exec(line)) !== null) {
    const value = match[2];
    if (value.startsWith("http") || value.startsWith("${")) continue;
    if (/^[A-Z][A-Z0-9_]+$/.test(value)) continue; // environment variable name
    if (/^\*+$/.test(value)) continue; // explicit redaction marker
    if (/^sk-/.test(value) || /^eyJ/.test(value)) continue; // covered by their own rules
    if (looksRandomSecret(value) && !isSyntheticPlaceholder(value)) {
      findings.push({ lineNumber, rule: "api-credential-assignment" });
    }
  }
  HTTP_CREDENTIAL_QUERY.lastIndex = 0;
  while ((match = HTTP_CREDENTIAL_QUERY.exec(line)) !== null) {
    if (!isAllowedHost(match[1])) {
      findings.push({ lineNumber, rule: "http-credential-transport" });
    }
  }
  HTTP_BASE_URL.lastIndex = 0;
  while ((match = HTTP_BASE_URL.exec(line)) !== null) {
    let hostname = "";
    try {
      hostname = new URL(match[1]).hostname;
    } catch {
      hostname = "";
    }
    if (!isAllowedHost(hostname, { allowSingleLabel: true })) {
      findings.push({ lineNumber, rule: "http-provider-endpoint" });
    }
  }
  return findings;
}

function* walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  entries.sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    const relative = path.relative(repoRoot, full).split(path.sep).join("/");
    if (entry.isDirectory()) {
      if (SKIP_DIR_NAMES.has(entry.name)) continue;
      if (SKIP_PATH_PREFIXES.some((prefix) => `${relative}/`.startsWith(prefix))) continue;
      yield* walk(full);
      continue;
    }
    if (!entry.isFile()) continue;
    if (SKIP_PATH_PREFIXES.some((prefix) => relative.startsWith(prefix))) continue;
    if (BINARY_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) continue;
    yield { full, relative };
  }
}

const violations = [];
let scanned = 0;
for (const { full, relative } of walk(repoRoot)) {
  let stats;
  try {
    stats = statSync(full);
  } catch {
    continue;
  }
  if (stats.size > MAX_FILE_BYTES) continue;
  let text;
  try {
    text = readFileSync(full, "utf8");
  } catch {
    continue;
  }
  if (text.includes("\u0000")) continue; // binary content in a text-named file
  scanned += 1;
  const lines = text.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.length > 20000) continue;
    const findings = [];
    lineViolations(line, index + 1, findings);
    for (const finding of findings) {
      violations.push(`${relative}:${finding.lineNumber} [${finding.rule}]`);
    }
  }
}

if (violations.length > 0) {
  process.stderr.write(
    `Plaintext credential gate failed: ${violations.length} finding(s). Values are never printed.\n`,
  );
  for (const violation of violations) {
    process.stderr.write(`  ${violation}\n`);
  }
  process.exit(1);
}
process.stdout.write(
  `Plaintext credential gate passed (${scanned} files scanned, 0 findings; synthetic fixtures allowed by documented convention).\n`,
);
