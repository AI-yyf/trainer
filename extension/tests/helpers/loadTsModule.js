'use strict';

/**
 * Minimal CommonJS loader for the webview's TypeScript sources.
 *
 * Tests that used to transpile a single self-contained copy.ts now need to
 * follow its locale modules. This resolves relative imports recursively and
 * delegates everything else to Node's require, so a test can load a module
 * tree without a bundler.
 */

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const typescript = require(require.resolve('typescript', {
  paths: [path.resolve(__dirname, '..', '..', 'webview')],
}));

const WEBVIEW_ROOT = path.resolve(__dirname, '..', '..', 'webview');

function resolveRelative(fromDirectory, specifier) {
  const base = path.resolve(fromDirectory, specifier);
  const candidates = [
    `${base}.ts`,
    `${base}.tsx`,
    path.join(base, 'index.ts'),
    path.join(base, 'index.tsx'),
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`cannot resolve ${specifier} from ${fromDirectory}`);
  }
  return found;
}

function loadTsModule(entryPath, cache = new Map()) {
  const resolved = path.resolve(entryPath);
  const cached = cache.get(resolved);
  if (cached) {
    return cached.exports;
  }

  const source = fs.readFileSync(resolved, 'utf8');
  const output = typescript.transpileModule(source, {
    compilerOptions: {
      module: typescript.ModuleKind.CommonJS,
      target: typescript.ScriptTarget.ES2020,
      jsx: typescript.JsxEmit.ReactJSX,
    },
  }).outputText;

  const module = { exports: {} };
  cache.set(resolved, module);
  const localRequire = (specifier) => {
    if (specifier.startsWith('.')) {
      return loadTsModule(resolveRelative(path.dirname(resolved), specifier), cache);
    }
    return require(specifier);
  };

  vm.runInNewContext(
    output,
    { exports: module.exports, module, require: localRequire },
    { filename: resolved },
  );
  return module.exports;
}

module.exports = { loadTsModule, WEBVIEW_ROOT };
