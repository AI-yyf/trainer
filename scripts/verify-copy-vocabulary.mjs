#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const SCAN_TARGETS = [
  "extension/webview/src/lib/i18n",
  "extension/webview/src/components/learning",
  "extension/webview/src/components/training",
  "extension/webview/src/components/settings/settingsText.ts",
  "extension/webview/src/templates/templateCopy.ts",
  "extension/webview/src/lib/chromeSidePanelTransport.ts",
];

const BANNED_TERMS = [
  { term: "练习记录确认", regex: /练习记录确认/g },
  { term: "到期队列", regex: /到期队列/g },
  { term: "事件账本", regex: /事件账本/g },
  { term: "能力投影", regex: /能力投影/g },
  { term: "计划修订号", regex: /计划修订号/g },
  { term: "候选卡库", regex: /候选卡库/g },
  { term: "训练卡库", regex: /训练卡库/g },
  { term: "确认入库", regex: /确认入库/g },
  { term: "后续和回看", regex: /后续和回看/g },
  { term: "UI proxy", regex: /\bUI proxy\b/g },
  { term: "event ledger", regex: /\bevent ledger\b/gi },
  { term: "skill projection", regex: /\bskill projection\b/gi },
  { term: "plan revision", regex: /\bplan revision\b/gi },
  { term: "candidate library", regex: /\bcandidate library\b/gi },
  { term: "chunk anchor", regex: /¶chunk:/g },
];

const COPY_ONLY_BANNED_TERMS = [
  { term: "insufficient_evidence", regex: /\binsufficient_evidence\b/g },
  { term: "no_recall_evidence", regex: /\bno_recall_evidence\b/g },
];

const COPY_TABLE_PATHS = [
  "extension/webview/src/lib/i18n",
  "extension/webview/src/components/settings/settingsText.ts",
  "extension/webview/src/templates/templateCopy.ts",
  "extension/src/commands/hostCommandCopy.ts",
  "extension/src/commands/providerHostCopy.ts",
  "extension/webview/src/lib/chromeSidePanelTransport.ts",
];

const CODE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".mjs", ".cjs"]);

function collectFiles(targetPath) {
  const full = path.join(root, targetPath);
  if (!fs.existsSync(full)) return [];
  const stat = fs.statSync(full);
  if (stat.isFile()) return [full];
  const entries = fs.readdirSync(full, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const child = path.join(full, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(path.relative(root, child)));
    } else if (CODE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(child);
    }
  }
  return files;
}

/**
 * Replace JS/TS line and block comments with spaces/newlines while preserving
 * line numbers so violations report exact file:line coordinates without false
 * positives on internal engineering comments.
 */
function stripCommentsPreserveLines(source) {
  let out = "";
  let i = 0;
  const n = source.length;
  let quote = null;
  while (i < n) {
    const ch = source[i];
    const next = i + 1 < n ? source[i + 1] : "";
    if (quote) {
      out += ch;
      if (ch === "\\" && i + 1 < n) {
        out += next;
        i += 2;
        continue;
      }
      if (ch === quote) {
        quote = null;
      }
      i += 1;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === "`") {
      quote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === "/" && next === "/") {
      out += "  ";
      i += 2;
      while (i < n && source[i] !== "\n") {
        out += " ";
        i += 1;
      }
      continue;
    }
    if (ch === "/" && next === "*") {
      out += "  ";
      i += 2;
      while (i < n && !(source[i] === "*" && source[i + 1] === "/")) {
        out += source[i] === "\n" ? "\n" : " ";
        i += 1;
      }
      if (i < n) {
        out += "  ";
        i += 2;
      }
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

const files = Array.from(new Set([...SCAN_TARGETS, ...COPY_TABLE_PATHS].flatMap(collectFiles)));
const copyFiles = new Set(COPY_TABLE_PATHS.flatMap(collectFiles));
const violations = [];

for (const file of files) {
  const rel = path.relative(root, file);
  const raw = fs.readFileSync(file, "utf8");
  const clean = stripCommentsPreserveLines(raw);
  const lines = clean.split("\n");
  const activeTerms = copyFiles.has(file) ? [...BANNED_TERMS, ...COPY_ONLY_BANNED_TERMS] : BANNED_TERMS;
  lines.forEach((line, index) => {
    for (const { term, regex } of activeTerms) {
      regex.lastIndex = 0;
      if (regex.test(line)) {
        violations.push(`${rel}:${index + 1}: banned learner-visible term "${term}" -> ${line.trim()}`);
      }
    }
  });
}

if (violations.length > 0) {
  console.error(`[verify-copy-vocabulary] FAIL ${violations.length} violation(s):`);
  for (const v of violations) {
    console.error(`  ${v}`);
  }
  process.exit(1);
}

console.log(`[verify-copy-vocabulary] OK scanned ${files.length} files, 0 banned-term violations`);
