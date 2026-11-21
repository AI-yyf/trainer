#!/usr/bin/env node
/**
 * Hard 8-language i18n completeness and script-integrity regression gate.
 *
 * Verifies:
 *   1. Every literal `appUiCopy(lang, "...")` call across `extension/webview/src`
 *      has all 7 non-Chinese locales (`en-US`, `es-ES`, `fr-FR`, `de-DE`,
 *      `ja-JP`, `ko-KR`, `pt-BR`) defined and non-empty in `APP_UI_TEXT`.
 *   2. Every literal `settingsText(lang, zh, en)` call (including multiline and
 *      single-quoted calls) across `extension/webview/src` has a matching
 *      `${zh}\u0000${en}` entry in `SETTINGS_TEXT` with all 7 non-Chinese
 *      locales defined and non-empty.
 *   3. No cross-script corruption in `appUiCopy.ts` or `settingsText.ts`
 *      (e.g. Hangul leaked into `ja-JP`, or CJK/Kana/Hangul leaked into Latin
 *      locales `en-US`, `es-ES`, `fr-FR`, `de-DE`, `pt-BR`).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = process.cwd();
const WEBVIEW_SRC = path.join(ROOT, "extension", "webview", "src");
const APP_UI_COPY_PATH = path.join(WEBVIEW_SRC, "lib", "i18n", "appUiCopy.ts");
const SETTINGS_TEXT_PATH = path.join(WEBVIEW_SRC, "components", "settings", "settingsText.ts");

const REQUIRED_NON_ZH_LOCALES = [
  "en-US",
  "es-ES",
  "fr-FR",
  "de-DE",
  "ja-JP",
  "ko-KR",
  "pt-BR",
];
const LATIN_LOCALES = new Set(["en-US", "es-ES", "fr-FR", "de-DE", "pt-BR"]);

function decodeJsString(raw) {
  return raw
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, "\\");
}

function walkTsFiles(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkTsFiles(full, out);
    } else if (entry.isFile() && /\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function parseLocaleRecord(source, exportName) {
  const startIdx = source.indexOf(`export const ${exportName}`);
  if (startIdx < 0) {
    throw new Error(`Could not find export ${exportName}`);
  }
  const openBrace = source.indexOf("{", source.indexOf("=", startIdx));
  let depth = 0;
  let endIdx = -1;
  let inStr = null;
  for (let i = openBrace; i < source.length; i++) {
    const ch = source[i];
    if (inStr) {
      if (ch === "\\") {
        i++;
      } else if (ch === inStr) {
        inStr = null;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      inStr = ch;
    } else if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) {
        endIdx = i + 1;
        break;
      }
    }
  }
  const block = source.slice(openBrace, endIdx);
  const entries = new Map();
  const entryRe = /^\s*"((?:[^"\\]|\\.)+)"\s*:\s*\{([\s\S]*?)^\s*\},/gm;
  let match;
  while ((match = entryRe.exec(block)) !== null) {
    const key = decodeJsString(match[1]);
    const body = match[2];
    const locales = new Map();
    const locRe = /"(zh-CN|en-US|es-ES|fr-FR|de-DE|ja-JP|ko-KR|pt-BR)"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
    let lm;
    while ((lm = locRe.exec(body)) !== null) {
      locales.set(lm[1], decodeJsString(lm[2]));
    }
    entries.set(key, locales);
  }
  return entries;
}

const errors = [];

const appUiSource = fs.readFileSync(APP_UI_COPY_PATH, "utf8");
const settingsTextSource = fs.readFileSync(SETTINGS_TEXT_PATH, "utf8");

const appUiEntries = parseLocaleRecord(appUiSource, "APP_UI_TEXT");
const settingsEntries = parseLocaleRecord(settingsTextSource, "SETTINGS_TEXT");

// 1. Scan all literal appUiCopy and settingsText call sites across webview/src.
const strLit = `(?:"((?:[^"\\\\]|\\\\.)*)"|'((?:[^'\\\\]|\\\\.)*)')`;
const appCallRe = new RegExp(`appUiCopy\\(\\s*[^,]+,\\s*${strLit}\\s*,?\\s*\\)`, "gs");
const settingsCallRe = new RegExp(
  `settingsText\\(\\s*[^,]+,\\s*${strLit}\\s*,\\s*${strLit}\\s*,?\\s*\\)`,
  "gs",
);

const allFiles = walkTsFiles(WEBVIEW_SRC);
const checkedAppKeys = new Set();
const checkedSettingsKeys = new Set();

for (const file of allFiles) {
  const rel = path.relative(ROOT, file);
  const src = fs.readFileSync(file, "utf8");

  if (file !== APP_UI_COPY_PATH) {
    appCallRe.lastIndex = 0;
    let m;
    while ((m = appCallRe.exec(src)) !== null) {
      const key = decodeJsString(m[1] ?? m[2] ?? "");
      if (!key || checkedAppKeys.has(key)) continue;
      checkedAppKeys.add(key);
      const locales = appUiEntries.get(key);
      if (!locales) {
        errors.push(`[appUiCopy] Missing entry for ${JSON.stringify(key)} (used in ${rel})`);
        continue;
      }
      const missing = REQUIRED_NON_ZH_LOCALES.filter((loc) => !(locales.get(loc) || "").trim());
      if (missing.length > 0) {
        errors.push(
          `[appUiCopy] Incomplete locales (${missing.join(", ")}) for ${JSON.stringify(key)} (used in ${rel})`,
        );
      }
    }
  }

  if (file !== SETTINGS_TEXT_PATH) {
    settingsCallRe.lastIndex = 0;
    let m;
    while ((m = settingsCallRe.exec(src)) !== null) {
      const zh = decodeJsString(m[1] ?? m[2] ?? "");
      const en = decodeJsString(m[3] ?? m[4] ?? "");
      const pair = `${zh}\u0000${en}`;
      if (checkedSettingsKeys.has(pair)) continue;
      checkedSettingsKeys.add(pair);
      const locales = settingsEntries.get(pair) ?? settingsEntries.get(zh);
      if (!locales) {
        errors.push(
          `[settingsText] Missing entry for ${JSON.stringify(zh)} | ${JSON.stringify(en)} (used in ${rel})`,
        );
        continue;
      }
      const missing = REQUIRED_NON_ZH_LOCALES.filter((loc) => !(locales.get(loc) || "").trim());
      if (missing.length > 0) {
        errors.push(
          `[settingsText] Incomplete locales (${missing.join(", ")}) for ${JSON.stringify(zh)} (used in ${rel})`,
        );
      }
    }
  }
}

// 2. Check cross-script integrity across every parsed record entry.
function checkScriptIntegrity(tableName, entries) {
  for (const [key, locales] of entries.entries()) {
    for (const [loc, value] of locales.entries()) {
      if (loc === "ja-JP" && /[\uac00-\ud7af]/.test(value)) {
        errors.push(`[${tableName}] Hangul leaked into ja-JP for ${JSON.stringify(key)}: ${JSON.stringify(value)}`);
      }
      if (LATIN_LOCALES.has(loc) && /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(value)) {
        errors.push(`[${tableName}] CJK/Kana/Hangul leaked into ${loc} for ${JSON.stringify(key)}: ${JSON.stringify(value)}`);
      }
    }
  }
}

checkScriptIntegrity("appUiCopy", appUiEntries);
checkScriptIntegrity("settingsText", settingsEntries);

if (errors.length > 0) {
  console.error(`i18n completeness gate FAILED with ${errors.length} issue(s):`);
  for (const err of errors.slice(0, 60)) {
    console.error(`  - ${err}`);
  }
  if (errors.length > 60) {
    console.error(`  ... and ${errors.length - 60} more.`);
  }
  process.exit(1);
}

console.log(
  `i18n completeness PASS: ${checkedAppKeys.size} appUiCopy call sites (${appUiEntries.size} table entries), ` +
    `${checkedSettingsKeys.size} settingsText call sites (${settingsEntries.size} table entries), ` +
    `0 missing locales, 0 cross-script leaks.`,
);
