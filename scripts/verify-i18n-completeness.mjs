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
const COMMANDS_SRC = path.join(ROOT, "extension", "src", "commands");
const APP_UI_COPY_PATH = path.join(WEBVIEW_SRC, "lib", "i18n", "appUiCopy.ts");
const SETTINGS_TEXT_PATH = path.join(WEBVIEW_SRC, "components", "settings", "settingsText.ts");
const HOST_COMMAND_COPY_PATH = path.join(COMMANDS_SRC, "hostCommandCopy.ts");
const PROVIDER_HOST_COPY_PATH = path.join(COMMANDS_SRC, "providerHostCopy.ts");
const WORKSPACE_ADMISSION_PATH = path.join(COMMANDS_SRC, "workspaceAdmissionCommands.ts");
const REMOTE_VERIFICATION_PATH = path.join(COMMANDS_SRC, "remoteVerificationCommands.ts");
const HOST_COMMAND_GUARD_FILES = [
  WORKSPACE_ADMISSION_PATH,
  path.join(COMMANDS_SRC, "resourceCommands.ts"),
  REMOTE_VERIFICATION_PATH,
  path.join(COMMANDS_SRC, "remoteCompanionCommands.ts"),
  path.join(COMMANDS_SRC, "remoteProjectAdmission.ts"),
];

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

// 3. Verify HOST_COMMAND_COPY completeness, call sites, and script integrity.
const hostCopySource = fs.readFileSync(HOST_COMMAND_COPY_PATH, "utf8");
const hostCopyEntries = parseLocaleRecord(hostCopySource, "HOST_COMMAND_COPY");
if (hostCopyEntries.size === 0) {
  errors.push("[hostCommandCopy] Failed to parse HOST_COMMAND_COPY entries.");
}
const allLocales = ["zh-CN", ...REQUIRED_NON_ZH_LOCALES];
for (const [key, locales] of hostCopyEntries.entries()) {
  const missing = allLocales.filter((loc) => !(locales.get(loc) || "").trim());
  if (missing.length > 0) {
    errors.push(`[hostCommandCopy] Missing/empty locales (${missing.join(", ")}) for key ${JSON.stringify(key)}`);
  }
}
checkScriptIntegrity("hostCommandCopy", hostCopyEntries);

const checkedHostKeys = new Set();
const hostKeyTokenRe = new RegExp(strLit, "g");
for (const file of walkTsFiles(COMMANDS_SRC)) {
  if (file === HOST_COMMAND_COPY_PATH) continue;
  const rel = path.relative(ROOT, file);
  const src = fs.readFileSync(file, "utf8");
  const idxRe = /\bhostCommandCopy\s*\(/g;
  let im;
  while ((im = idxRe.exec(src)) !== null) {
    // Extract the second argument expression (up to top-level ',' or ')').
    let i = im.index + im[0].length;
    let depth = 1;
    let inStr = null;
    let argIndex = 0;
    let secondStart = -1;
    let secondEnd = -1;
    for (; i < src.length && depth > 0; i++) {
      const ch = src[i];
      if (inStr) {
        if (ch === "\\") {
          i++;
        } else if (ch === inStr) {
          inStr = null;
        }
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") {
        inStr = ch;
        continue;
      }
      if (ch === "(" || ch === "{" || ch === "[") {
        depth++;
      } else if (ch === ")" || ch === "}" || ch === "]") {
        depth--;
        if (depth === 0 && argIndex === 1 && secondEnd === -1) {
          secondEnd = i;
        }
      } else if (ch === "," && depth === 1) {
        argIndex++;
        if (argIndex === 1) {
          secondStart = i + 1;
        } else if (argIndex === 2 && secondEnd === -1) {
          secondEnd = i;
          break;
        }
      }
    }
    if (secondStart >= 0 && secondEnd > secondStart) {
      const argExpr = src
        .slice(secondStart, secondEnd)
        // Strip equality comparison operands like `kind === 'file'` before extracting key literals.
        .replace(/[=!]==?\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, " ");
      hostKeyTokenRe.lastIndex = 0;
      let km;
      while ((km = hostKeyTokenRe.exec(argExpr)) !== null) {
        const key = decodeJsString(km[1] ?? km[2] ?? "");
        if (!key) continue;
        checkedHostKeys.add(key);
        if (!hostCopyEntries.has(key)) {
          errors.push(`[hostCommandCopy] Missing table entry for key ${JSON.stringify(key)} (used in ${rel})`);
        }
      }
    }
  }
}

// 4. Verify locale-keyed object tables (providerHostCopyTable, ADMISSION_HOST_COPY, REMOTE_VERIFICATION_SUMMARY_COPY).
function extractObjectLiteralBlock(source, varName) {
  const declRe = new RegExp(`(?:export\\s+)?const\\s+${varName}\\b`);
  const m = declRe.exec(source);
  if (!m) {
    throw new Error(`Could not find const ${varName}`);
  }
  const eqIdx = source.indexOf("=", m.index);
  const openBrace = source.indexOf("{", eqIdx);
  let depth = 0;
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
    if (ch === '"' || ch === "'" || ch === "`") {
      inStr = ch;
    } else if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) {
        return source.slice(openBrace, i + 1);
      }
    }
  }
  throw new Error(`Unclosed object literal for ${varName}`);
}

function parseLocaleKeyedTable(source, varName) {
  const block = extractObjectLiteralBlock(source, varName);
  const byLocale = new Map();
  const locHeaderRe = /['"](zh-CN|en-US|es-ES|fr-FR|de-DE|ja-JP|ko-KR|pt-BR)['"]\s*:\s*\{/g;
  let lm;
  while ((lm = locHeaderRe.exec(block)) !== null) {
    const locale = lm[1];
    const open = lm.index + lm[0].length - 1;
    let depth = 0;
    let inStr = null;
    let end = -1;
    for (let i = open; i < block.length; i++) {
      const ch = block[i];
      if (inStr) {
        if (ch === "\\") {
          i++;
        } else if (ch === inStr) {
          inStr = null;
        }
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") {
        inStr = ch;
      } else if (ch === "{") {
        depth++;
      } else if (ch === "}") {
        depth--;
        if (depth === 0) {
          end = i + 1;
          break;
        }
      }
    }
    const locBody = block.slice(open + 1, end - 1);
    const kvMap = new Map();
    const kvRe = /^\s*([a-zA-Z0-9_]+)\s*:\s*(?:\([^)]*\)\s*=>\s*)?(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`)\s*,?/gm;
    let km;
    while ((km = kvRe.exec(locBody)) !== null) {
      const k = km[1];
      const v = decodeJsString(km[2] ?? km[3] ?? km[4] ?? "");
      kvMap.set(k, v);
    }
    byLocale.set(locale, kvMap);
  }
  return byLocale;
}

function verifyLocaleKeyedTable(tableName, byLocale) {
  const zhMap = byLocale.get("zh-CN");
  if (!zhMap || zhMap.size === 0) {
    errors.push(`[${tableName}] Missing zh-CN entries.`);
    return;
  }
  for (const loc of allLocales) {
    const locMap = byLocale.get(loc);
    if (!locMap) {
      errors.push(`[${tableName}] Missing locale block ${loc}.`);
      continue;
    }
    for (const key of zhMap.keys()) {
      const value = locMap.get(key);
      if (typeof value !== "string" || !value.trim()) {
        errors.push(`[${tableName}] Missing/empty ${loc} value for key ${JSON.stringify(key)}`);
        continue;
      }
      if (loc === "ja-JP" && /[\uac00-\ud7af]/.test(value)) {
        errors.push(`[${tableName}] Hangul leaked into ja-JP for ${JSON.stringify(key)}: ${JSON.stringify(value)}`);
      }
      if (LATIN_LOCALES.has(loc) && /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(value)) {
        errors.push(`[${tableName}] CJK/Kana/Hangul leaked into ${loc} for ${JSON.stringify(key)}: ${JSON.stringify(value)}`);
      }
    }
  }
}

const providerHostSource = fs.readFileSync(PROVIDER_HOST_COPY_PATH, "utf8");
const providerHostTable = parseLocaleKeyedTable(providerHostSource, "providerHostCopyTable");
verifyLocaleKeyedTable("providerHostCopyTable", providerHostTable);

const admissionSource = fs.readFileSync(WORKSPACE_ADMISSION_PATH, "utf8");
const admissionTable = parseLocaleKeyedTable(admissionSource, "ADMISSION_HOST_COPY");
verifyLocaleKeyedTable("ADMISSION_HOST_COPY", admissionTable);

const remoteVerifySource = fs.readFileSync(REMOTE_VERIFICATION_PATH, "utf8");
const remoteVerifyTable = parseLocaleKeyedTable(remoteVerifySource, "REMOTE_VERIFICATION_SUMMARY_COPY");
verifyLocaleKeyedTable("REMOTE_VERIFICATION_SUMMARY_COPY", remoteVerifyTable);

// 5. Guard the 5 localized host command files against stray hardcoded UI message literals.
function stripCopyTablesAndComments(source) {
  let out = source;
  for (const name of ["ADMISSION_HOST_COPY", "REMOTE_VERIFICATION_SUMMARY_COPY"]) {
    try {
      const block = extractObjectLiteralBlock(out, name);
      out = out.replace(block, "/*_COPY_TABLE_STRIPPED_*/".padEnd(block.length, " "));
    } catch {
      // Not present in this file.
    }
  }
  return out;
}

const rawUiLiteralRe =
  /(?:\b(?:message|openLabel|saveLabel|title|prompt)\s*:\s*|\bshow(?:Warning|Information|Error)Message\s*\(\s*)(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`)/gs;

for (const file of HOST_COMMAND_GUARD_FILES) {
  const rel = path.relative(ROOT, file);
  const rawSrc = fs.readFileSync(file, "utf8");
  const cleaned = stripCopyTablesAndComments(rawSrc);
  rawUiLiteralRe.lastIndex = 0;
  let rm;
  while ((rm = rawUiLiteralRe.exec(cleaned)) !== null) {
    // Skip comment lines.
    const lineStart = cleaned.lastIndexOf("\n", rm.index) + 1;
    const prefix = cleaned.slice(lineStart, rm.index);
    if (/^\s*\/\//.test(prefix)) continue;
    const literal = rm[1] ?? rm[2] ?? rm[3] ?? "";
    const withoutInterp = literal.replace(/\$\{[^}]*\}/g, " ");
    if (/[A-Za-z]{4,}\s+[A-Za-z]{2,}/.test(withoutInterp) || /\p{Script=Han}/u.test(withoutInterp)) {
      const lineNum = cleaned.slice(0, rm.index).split("\n").length;
      errors.push(`[hostCommandLiteral] Unlocalized literal in ${rel}:${lineNum}: ${JSON.stringify(literal)}`);
    }
  }
}

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
    `${checkedHostKeys.size} hostCommandCopy call sites (${hostCopyEntries.size} table entries + provider/admission/remote-verify host tables), ` +
    `0 missing locales, 0 cross-script leaks, 0 stray host literals.`,
);
