'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}

test('composer dock unifies footer hit size, radius, gap, and icon box', () => {
  const styles = read('styles.css');
  const composer = read('components/composer/CoachComposer.tsx');
  const app = read('app/App.tsx');

  assert.match(styles, /--composer-dock-hit:\s*28px;/);
  assert.match(styles, /--composer-dock-gap:\s*4px;/);
  assert.match(styles, /--composer-dock-radius:\s*8px;/);
  assert.match(
    styles,
    /\.composer-shell--quiet \.composer__send,\s*\.composer-shell--quiet \.composer__clear-btn,\s*\.composer-shell--quiet \.icon-button\s*\{[\s\S]*?width: var\(--composer-dock-hit\);[\s\S]*?height: var\(--composer-dock-hit\);[\s\S]*?border-radius: var\(--composer-dock-radius\);/,
  );
  assert.match(
    styles,
    /\.composer-shell--quiet \.composer__send svg[\s\S]*?width:\s*16px;[\s\S]*?height:\s*16px;/,
  );
  assert.match(
    styles,
    /\.composer-shell--quiet \.composer--compact \.composer__send,\s*\.composer-shell--quiet \.composer--compact \.composer__clear-btn,\s*\.composer-shell--quiet \.composer--compact \.icon-button\s*\{[\s\S]*?width: var\(--composer-dock-hit\);[\s\S]*?height: var\(--composer-dock-hit\);/,
  );
  assert.match(
    styles,
    /\.composer-shell--quiet \.composer--compact \.composer__toolbar-divider\s*\{[\s\S]*?height:\s*16px;/,
  );
  assert.doesNotMatch(styles, /\.composer-shell--quiet \.composer__send svg\s*\{[\s\S]*?width:\s*18px;/);
  assert.doesNotMatch(composer, /compactMode \? 36 : 38/);
  assert.match(composer, /padTop \+ padBottom,\s*36,/);
  assert.match(styles, /\.composer__accessory\s*\{[\s\S]*?bottom:\s*calc\(100% \+ 6px\)/);
  assert.match(styles, /\.composer-mode-menu\s*\{[\s\S]*?bottom:\s*calc\(100% \+ 6px\)/);
  assert.doesNotMatch(styles, /\.composer-mode-menu\s*\{[\s\S]*?bottom:\s*calc\(100% \+ 8px\)/);
  assert.match(composer, /padTop \+ padBottom/);
  assert.match(composer, /<PlusIcon size=\{16\} \/>/);
  assert.match(composer, /<CloseIcon size=\{16\} \/>/);
  assert.match(composer, /<SendIcon size=\{16\} \/>/);
  assert.match(app, /id: "composer-verify-file"/);
  assert.match(app, /filesToTouch: trainingFilesToTouch/);
  assert.doesNotMatch(app, /请点“验证当前文件”/);
  assert.doesNotMatch(app, /Use Verify current file for the real pass/);
});

test('conversation markdown headings are distinguishable inside message-markdown', () => {
  const styles = read('styles.css');
  assert.match(styles, /\.trainer-shell \.message-markdown h1\s*\{[\s\S]*?font-size:\s*1\.22rem/);
  assert.match(styles, /\.trainer-shell \.message-markdown h1\s*\{[\s\S]*?font-weight:\s*700 !important/);
  assert.match(styles, /\.trainer-shell \.message-markdown h2\s*\{[\s\S]*?font-size:\s*1\.08rem/);
  assert.match(styles, /\.trainer-shell \.message-markdown h3\s*\{[\s\S]*?font-size:\s*1rem/);
  assert.match(styles, /\.message-markdown ul ul/);
  assert.doesNotMatch(
    styles,
    /\.skill-deck__section,\s*\.message-markdown h1,/,
  );
  assert.doesNotMatch(
    styles,
    /\.trainer-shell \.message-markdown h1,\s*\.trainer-shell \.message-markdown h2,\s*\.trainer-shell \.message-markdown h3,\s*\.trainer-shell \.message-markdown h4,\s*\.trainer-shell \.message-markdown strong/,
  );
});

test('compact nav labels are not ellipsized to a single character', () => {
  const styles = read('styles.css');
  const labelStart = styles.indexOf('.header-switcher__label {');
  const labelBlock = styles.slice(labelStart, labelStart + 180);
  assert.match(labelBlock, /overflow:\s*visible;/);
  assert.match(labelBlock, /text-overflow:\s*clip;/);
  assert.match(styles, /\.header-switcher--compact\s*\{[\s\S]*?gap:\s*0;/);
});
