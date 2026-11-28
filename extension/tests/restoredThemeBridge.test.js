// Restored behavioral regression test. Original file: extension/tests/themeBridgeSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 3 of 6 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "theme bridge preserves host variable indirection and writes no colours"
//       CSS source-text guard: reads the webview stylesheet sections and asserts on the stylesheet text
//       (out of scope by rule). and theme source text.
//   - "host-themed interactive states avoid fixed white and retain visible keyboard focus"
//       CSS source-text guard: reads the webview stylesheet sections and asserts on the stylesheet text
//       (out of scope by rule).
//   - "startup installs host theme observation for VS Code family theme changes"
//       fails at HEAD: The input did not match the regular expression
//       /installWorkbenchHostThemeBridge\(\)/. Input: / import { mountWorkbenchApp,renderStartupFailure
//       } from "./bootstrapWorkbench";\n' +
// Target: webview TypeScript transpiled in memory with typescript.transpileModule.

'use strict';

const test = require('node:test');

// PR-7: styles.css is an @import aggregator; rules live in styles/sections/*.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const typescript = require(require.resolve('typescript', {
  paths: [path.resolve(__dirname, '..', 'webview')],
}));

const themeSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'theme.ts');
const mainSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'main.tsx');
const stylesSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

function readSource(sourcePath) {
  // PR-7: styles.css is an @import aggregator — read the split sections.
  if (sourcePath === stylesSourcePath) {
    return readStylesSource();
  }
  return fs.readFileSync(sourcePath, 'utf8');
}

function createThemeFixture() {
  const observers = [];
  const createStyle = () => ({
    values: {},
    setProperty(name, value) {
      this.values[name] = value;
    },
    removeProperty(name) {
      delete this.values[name];
    },
  });
  const createElement = () => ({
    attributes: {},
    dataset: {},
    style: createStyle(),
    getAttribute(name) {
      return this.attributes[name] ?? null;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
  });
  const root = createElement();
  const body = createElement();
  const fallbackTheme = (prefix) => ({
    bg0: `${prefix}-bg0`,
    bg1: `${prefix}-bg1`,
    bg2: `${prefix}-bg2`,
    bg3: `${prefix}-bg3`,
    fg0: `${prefix}-fg0`,
    fg1: `${prefix}-fg1`,
    fgMuted: `${prefix}-fg-muted`,
    line: `${prefix}-line`,
    accent: `${prefix}-accent`,
    accentSoft: `${prefix}-accent-soft`,
    success: `${prefix}-success`,
    warning: `${prefix}-warning`,
    danger: `${prefix}-danger`,
    focusRing: `${prefix}-focus-ring`,
    overlay: `${prefix}-overlay`,
    shadowSoft: `${prefix}-shadow-soft`,
    colorScheme: prefix,
  });
  const workbenchTokens = {
    radius: { s: '4px', m: '6px', l: '8px' },
    space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '32px' },
    type: { lineHeight: '1.5' },
    themes: {
      dark: fallbackTheme('dark'),
      light: fallbackTheme('light'),
    },
  };
  class MutationObserver {
    constructor(callback) {
      this.callback = callback;
      observers.push(this);
    }

    observe() {}

    disconnect() {}
  }
  const module = { exports: {} };
  const compiledTheme = typescript.transpileModule(readSource(themeSourcePath), {
    compilerOptions: {
      module: typescript.ModuleKind.CommonJS,
      target: typescript.ScriptTarget.ES2020,
    },
  }).outputText;
  const context = {
    document: { documentElement: root, body },
    window: {
      matchMedia: () => ({ matches: false }),
    },
    MutationObserver,
    module,
    exports: module.exports,
    require: (specifier) => {
      if (specifier.includes('shared/src/tokens')) {
        return { workbenchTokens };
      }
      throw new Error(`Unexpected module request: ${specifier}`);
    },
  };

  vm.runInNewContext(compiledTheme, context, { filename: themeSourcePath });
  return { body, observers, root, theme: module.exports };
}



test('host light classes and theme kinds switch missing-token fallbacks to light', () => {
  for (const [attribute, value] of [
    ['class', 'vscode-high-contrast-light'],
    ['data-vscode-theme-kind', 'light'],
  ]) {
    const { body, observers, root, theme } = createThemeFixture();

    theme.applyWorkbenchTheme('dark');
    theme.installWorkbenchHostThemeBridge();
    assert.equal(root.dataset.theme, 'dark');
    assert.equal(root.style.colorScheme, 'dark');

    body.attributes[attribute] = value;
    observers.at(-1).callback();

    assert.equal(root.dataset.theme, 'light');
    assert.equal(root.style.colorScheme, 'light');
    assert.equal(root.attributes['data-theme-explicit'], undefined);
  }
});

test('selected fallback remains in effect when no host theme category is present', () => {
  const { root, theme } = createThemeFixture();

  theme.applyWorkbenchTheme('light');

  assert.equal(root.dataset.theme, 'light');
  assert.equal(root.style.colorScheme, 'light');
  assert.deepEqual(
    Object.keys(root.style.values).filter((name) => name.startsWith('--trainer-fallback-')),
    [],
    'the bridge must not write colour values',
  );
});

test('explicit themes override semantic tokens on root and body without changing host variables', () => {
  for (const [selected, host] of [['light', 'vscode-dark'], ['dark', 'vscode-light']]) {
    const { body, observers, root, theme } = createThemeFixture();
    body.attributes.class = host;
    body.style.setProperty('--vscode-sideBar-background', 'host-background');
    theme.applyWorkbenchTheme(selected, false);
    theme.installWorkbenchHostThemeBridge();
    assert.equal(root.attributes['data-theme-explicit'], 'true');
    for (const element of [root, body]) {
      assert.equal(element.style.values['--bg-0'], undefined);
      assert.equal(element.style.values['--fg-0'], undefined);
    }
    body.attributes.class = host === 'vscode-dark' ? 'vscode-light' : 'vscode-dark';
    observers.at(-1).callback();
    assert.equal(root.dataset.theme, selected, 'host changes must not undo an explicit choice');
    assert.equal(body.style.values['--vscode-sideBar-background'], 'host-background');
    theme.applyWorkbenchTheme(selected, true);
    assert.equal(root.attributes['data-theme-explicit'], undefined);
    for (const element of [root, body]) {
      assert.equal(element.style.values['--bg-0'], undefined);
      assert.equal(element.style.values['--fg-0'], undefined);
    }
    assert.equal(root.dataset.theme, selected, 'auto resolves the current host family');
    body.attributes.class = host;
    observers.at(-1).callback();
    assert.equal(root.dataset.theme, selected === 'light' ? 'dark' : 'light');
  }
});
