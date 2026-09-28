#!/usr/bin/env node
// CSS section syntax validator (§四十八).
//
// The bundled stylesheet is split into styles/sections/*.css behind one
// manifest. A single unbalanced block anywhere in those files used to reach
// production as a Vite/esbuild `Expected "}" to go with "{"` warning with all
// following rules silently dropped (a view-entrance rule once sat unclosed
// for weeks). This gate keeps that class of breakage out of the tree.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webviewRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "webview",
  "src",
);

/** Strip comments and quoted strings so braces inside them cannot mislead the scan. */
function stripCssNoise(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''");
}

/**
 * Returns a list of problems for one CSS file. Empty array means clean.
 */
export function validateCssSource(css) {
  const problems = [];
  const cleaned = stripCssNoise(css);
  let depth = 0;
  let line = 1;
  for (const character of cleaned) {
    if (character === "\n") {
      line += 1;
      continue;
    }
    if (character === "{") {
      depth += 1;
    } else if (character === "}") {
      depth -= 1;
      if (depth < 0) {
        problems.push(`unexpected closing brace at line ${line}`);
        depth = 0;
      }
    }
  }
  if (depth > 0) {
    problems.push(`${depth} unclosed block(s) at end of file`);
  }
  return problems;
}

/**
 * Validates every section in manifest order. Returns [{file, problems}].
 */
export function validateCssSections({ webviewRoot: root = webviewRoot } = {}) {
  const manifestPath = path.join(root, "styles", "sections", "manifest.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const results = [];
  for (const entry of manifest) {
    const file = path.join(root, entry.file);
    const css = fs.readFileSync(file, "utf8");
    const problems = validateCssSource(css);
    if (problems.length > 0) {
      results.push({ file: entry.file, problems });
    }
  }
  return results;
}

function main() {
  const results = validateCssSections();
  if (results.length === 0) {
    console.log("css sections: all balanced");
    return;
  }
  for (const { file, problems } of results) {
    for (const problem of problems) {
      console.error(`styles/sections/${file}: ${problem}`);
    }
  }
  process.exit(1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
