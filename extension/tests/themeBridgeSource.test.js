'use strict';

const test = require('node:test');
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
  return fs.readFileSync(sourcePath, 'utf8');
}

function createThemeFixture() {
  const observers = [];
  const createStyle = () => ({
    values: {},
    setProperty(name, value) {
      this.values[name] = value;
    },
  });
  const createElement = () => ({
    attributes: {},
    dataset: {},
    style: createStyle(),
    getAttribute(name) {
      return this.attributes[name] ?? null;
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

test('theme bridge preserves host variable indirection instead of freezing computed colors', () => {
  const themeSource = readSource(themeSourcePath);
  const stylesSource = readSource(stylesSourcePath);

  assert.match(themeSource, /--trainer-fallback-bg-0/);
  assert.doesNotMatch(themeSource, /getComputedStyle/);
  assert.match(stylesSource, /:root,\s*body\s*\{/);
  assert.match(stylesSource, /--bg-0:\s*var\(--vscode-sideBar-background,/);
  assert.match(stylesSource, /--accent:\s*var\(--vscode-button-background,/);
  assert.match(stylesSource, /--focus-ring:\s*var\(--vscode-focusBorder,/);
  assert.match(stylesSource, /--success:\s*var\(--vscode-testing-iconPassed,/);
  assert.match(stylesSource, /--warning:\s*var\(--vscode-editorWarning-foreground,/);
  assert.match(stylesSource, /--danger:\s*var\(--vscode-errorForeground,/);
  assert.doesNotMatch(stylesSource, /--accent:\s*#/);
});

test('host-themed interactive states avoid fixed white and retain visible keyboard focus', () => {
  const stylesSource = readSource(stylesSourcePath);
  const userBadgeRule = /\.message-bubble-v2--user \.message-bubble-v2__badge\s*\{[^}]*\}/;

  assert.match(stylesSource, userBadgeRule);
  assert.doesNotMatch(stylesSource, /\.message-bubble-v2--user \.message-bubble-v2__badge\s*\{[^}]*\bwhite\b/);
  assert.match(stylesSource, /\.message-bubble-v2--user \.message-bubble-v2__badge\s*\{[^}]*color:\s*var\(--fg-0\)/);

  for (const selector of [
    '.resources-library-hero__root',
    '.resources-library-tree__node',
    '.resources-sandbox-row__main',
    '.resources-sandbox-tree__node',
    '.coach-plan-view__stage-row',
    '.settings-provider-profile',
    '.settings-model-limit-row__model',
  ]) {
    const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    assert.match(
      stylesSource,
      new RegExp(`${escapedSelector}:focus-visible\\s*\\{[^}]*outline:\\s*1px solid var\\(--focus-ring\\);[^}]*outline-offset:`),
    );
  }
});

test('startup installs host theme observation for VS Code family theme changes', () => {
  const themeSource = readSource(themeSourcePath);
  const mainSource = readSource(mainSourcePath);

  assert.match(themeSource, /new MutationObserver\(sync\)/);
  assert.match(themeSource, /function resolveHostThemeName/);
  assert.match(themeSource, /vscode-high-contrast-light/);
  assert.match(themeSource, /data-vscode-theme-kind/);
  assert.match(themeSource, /const resolvedTheme = resolveHostThemeName\(activeFallbackTheme\)/);
  assert.match(themeSource, /applyFallbackTheme\(resolvedTheme\)/);
  assert.match(themeSource, /root\.dataset\.theme = resolvedTheme/);
  assert.match(mainSource, /installWorkbenchHostThemeBridge\(\)/);
});

test('host light classes and theme kinds switch missing-token fallbacks to light', () => {
  for (const [attribute, value] of [
    ['class', 'vscode-high-contrast-light'],
    ['data-vscode-theme-kind', 'light'],
  ]) {
    const { body, observers, root, theme } = createThemeFixture();

    theme.applyWorkbenchTheme('dark');
    theme.installWorkbenchHostThemeBridge();
    assert.equal(root.style.values['--trainer-fallback-bg-1'], 'dark-bg1');

    body.attributes[attribute] = value;
    observers.at(-1).callback();

    assert.equal(root.style.values['--trainer-fallback-bg-0'], 'light-bg0');
    assert.equal(root.style.values['--trainer-fallback-bg-1'], 'light-bg1');
    assert.equal(root.dataset.theme, 'light');
    assert.equal(root.style.colorScheme, 'light');
  }
});

test('selected fallback remains in effect when no host theme category is present', () => {
  const { root, theme } = createThemeFixture();

  theme.applyWorkbenchTheme('light');

  assert.equal(root.style.values['--trainer-fallback-bg-0'], 'light-bg0');
  assert.equal(root.dataset.theme, 'light');
  assert.equal(root.style.colorScheme, 'light');
});
