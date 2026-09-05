'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const stylesSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const tokensSourcePath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'tokens.ts');
const webviewContentSourcePath = path.resolve(
  __dirname,
  '..',
  'src',
  'core',
  'webviewContent.ts',
);

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test('webview typography tokens stay on one VS Code-sized scale', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');
  const tokensSource = fs.readFileSync(tokensSourcePath, 'utf8');

  assert.match(stylesSource, /--trainer-font-3xs:\s*max\(11px, calc\(var\(--trainer-font-ui\) - 2px\)\);/);
  assert.match(stylesSource, /--trainer-font-2xs:\s*max\(12px, calc\(var\(--trainer-font-ui\) - 1px\)\);/);
  assert.match(stylesSource, /--trainer-font-xs:\s*var\(--trainer-font-ui\);/);
  assert.match(tokensSource, /sizeSm:\s*"13px"/);
});

test('shared eyebrow styles no longer reintroduce uppercase or heavier emphasis', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  assert.match(
    stylesSource,
    /\.eyebrow\s*\{[\s\S]*?font-size:\s*var\(--trainer-font-2xs\);[\s\S]*?font-weight:\s*400;[\s\S]*?text-transform:\s*none;[\s\S]*?letter-spacing:\s*0;/,
  );
  assert.match(
    stylesSource,
    /\.trainer-startup-error__eyebrow,\s*\.trainer-startup-shell__eyebrow\s*\{[\s\S]*?font-size:\s*var\(--trainer-font-3xs\);[\s\S]*?font-weight:\s*400;[\s\S]*?letter-spacing:\s*0;[\s\S]*?text-transform:\s*none;/,
  );
});

test('fallback webview surfaces match the same calm typography scale', () => {
  const source = fs.readFileSync(webviewContentSourcePath, 'utf8');

  assert.match(source, /\.trainer-webview-fallback__eyebrow\s*\{[\s\S]*?font-size:\s*13px;[\s\S]*?letter-spacing:\s*0;/);
  assert.match(source, /\.trainer-webview-fallback__card p\s*\{[\s\S]*?font-size:\s*13px;/);
  assert.match(source, /\.trainer-webview-recovery__eyebrow\s*\{[\s\S]*?font-size:\s*13px;[\s\S]*?letter-spacing:\s*0;/);
  assert.match(source, /\.trainer-webview-recovery__title\s*\{[\s\S]*?font-size:\s*13px;/);
  assert.match(source, /\.trainer-webview-recovery__copy,[\s\S]*?\.trainer-webview-recovery__status\s*\{[\s\S]*?font-size:\s*13px;/);
  assert.doesNotMatch(source, /font-size:\s*18px;/);
});

test('missing-bundle fallback stays a single-column recovery surface', () => {
  const source = fs.readFileSync(webviewContentSourcePath, 'utf8');

  assert.match(source, /class="trainer-webview-recovery"/);
  assert.match(source, /data-recovery/);
  assert.match(source, /Check Trainer startup/);
  assert.match(source, /reload the VS Code window and open Trainer again/);
  assert.match(source, /type: 'request\/bootstrap'/);
  assert.match(source, /default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-\$\{nonce\}'/);
  assert.match(source, /html = html\.replace\(\/\<script\(\?!\[\^>\]\*\\bnonce=\)/);
  assert.doesNotMatch(source, /class="shell"/);
  assert.doesNotMatch(source, /<div class="item">Memory<\/div>/);
  assert.doesNotMatch(source, /<div class="item">Weaknesses<\/div>/);
  assert.doesNotMatch(source, /<div class="item">Reviews<\/div>/);
  assert.doesNotMatch(source, /\[data-command\]/);
  assert.doesNotMatch(source, /grid-template-columns:/);
});

test('view-owned headings and title-like copy stay capped at the same VS Code-sized track', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');
  const selectors = [
    '.header-switcher__item',
    '.section-block__header h2',
    '.workbench-pane__heading h2',
    '.settings-sheet__header h2',
    '.settings-section__title',
    '.resource-library-view__title',
    '.resource-library-row__copy h3',
    '.resource-library-authority__summary-copy strong',
    '.practice-card__title',
    '.training-state__title',
    '.training-active-card-route__pill-title',
    '.card-title',
    '.tip-title',
    '.rhythm-title',
    '.memory-title',
    '.schedule-title',
    '.resources-inline-context__title',
    '.flash-create-form__title',
    '.flash-empty__title',
    '.flash-complete__title',
    '.humanized-empty-state__title',
    '.coach-plan-view__decision-copy strong',
    '.coach-plan-view__blocked-copy > strong',
    '.coach-plan-view__read-rail-item strong',
    '.coach-plan-view__now-card strong',
    '.coach-plan-view__stage-topline strong',
    '.training-next-move strong',
    '.training-verification-return strong',
    '.coach-turn-recap__title',
    '.coach-turn-recap__fact-value',
    '.coach-conversation-view__summary-pill strong',
    '.coach-conversation-view__summary-token strong',
    '.settings-availability-strip__copy > strong',
  ];

  for (const selector of selectors) {
    assert.match(
      stylesSource,
      new RegExp(`${escapeRegex(selector)}[\\s\\S]*?font-size:\\s*var\\(--trainer-font-xs\\);`),
    );
  }

  assert.match(
    stylesSource,
    /\.message-bubble-v2__badge-icon\s*\{[\s\S]*?font-size:\s*var\(--trainer-font-3xs\);/,
  );
  assert.doesNotMatch(stylesSource, /\.message-bubble-v2__badge-icon\s*\{[\s\S]*?font-size:\s*10px;/);
});

test('in-view summary copy stays visually quieter than the view title track', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');
  const selectors = [
    '.training-current h2',
    '.training-current h3',
    '.practice-card__title',
    '.practice-card__next-hop-title',
    '.practice-card__section-label',
    '.training-next-move strong',
    '.training-verification-return strong',
    '.training-state__title',
    '.training-active-card-route__pill-title',
    '.coach-plan-view__main-card-lead',
    '.coach-plan-view__decision-copy strong',
    '.coach-plan-view__blocked-copy > strong',
    '.coach-plan-view__now-card strong',
    '.coach-plan-view__stage-topline strong',
    '.coach-plan-view__goal-title',
    '.resource-library-row__copy h3',
    '.resource-library-authority__summary-copy strong',
    '.coach-turn-recap__title',
    '.coach-turn-recap__fact-value',
    '.coach-empty-state__lead',
    '.coach-empty-state__copy h3',
    '.coach-super-entry__copy h3',
    '.coach-super-entry__status strong',
    '.coach-conversation-view__summary-pill strong',
    '.coach-conversation-view__summary-token strong',
    '.composer-presencebar__provider strong',
    '.command-deck__header strong',
    '.command-deck__body strong',
    '.skill-deck__header strong',
    '.skill-deck__body strong',
    '.settings-section__title',
    '.settings-availability-strip__copy > strong',
    '.settings-sheet__summary-card-value',
    '.settings-setup-check strong',
    '.coach-plan-view__empty-outline-row strong',
    '.resources-library-stat strong',
    '.training-active-card-route__factor strong',
    '.settings-field label',
    '.coach-empty-state__starter-title',
    '.settings-sheet__simple-row > strong',
  ];

  for (const selector of selectors) {
    assert.match(
      stylesSource,
      new RegExp(`${escapeRegex(selector)}[\\s\\S]*?color:\\s*var\\(--fg-1\\);`),
    );
  }
});

test('pane titles stay as the strongest text track in each of the five views', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');
  const selectors = [
    '.section-block__header h2',
    '.workbench-pane__heading h2',
    '.settings-sheet__header h2',
    '.coach-conversation-view__heading',
    '.resource-library-view__title',
  ];

  for (const selector of selectors) {
    assert.match(
      stylesSource,
      new RegExp(`${escapeRegex(selector)}[\\s\\S]*?color:\\s*var\\(--fg-0\\)\\s*!important;`),
    );
  }
});

test('secondary outline labels stay calm and do not reintroduce uppercase emphasis', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  assert.match(
    stylesSource,
    /\.coach-plan-view__empty-outline-row span\s*\{[\s\S]*?text-transform:\s*none;[\s\S]*?letter-spacing:\s*0;/,
  );
});

test('webview source keeps visible typography at regular weight', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');
  const heavyWeightMatches = [...stylesSource.matchAll(/font-weight:\s*(500|600|650|700)\s*;/g)].map(
    (match) => match[0],
  );

  assert.deepEqual(heavyWeightMatches, []);
});

test('webview source keeps literal font sizes on the VS Code track', () => {
  const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
  const hits = [];

  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const target = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(target);
        continue;
      }
      if (!/\.(css|ts|tsx)$/.test(entry.name)) {
        continue;
      }
      const source = fs.readFileSync(target, 'utf8');
      for (const line of source.split(/\r?\n/)) {
        if (
          /font-size:\s*(?:[0-9]|1[4-9]|[2-9][0-9])px/.test(line) ||
          /fontSize\s*:\s*["']?(?:[0-9]|1[4-9]|[2-9][0-9])px/.test(line)
        ) {
          const normalized = line.trim();
          if (normalized !== 'font-size: 0;') {
            hits.push(`${path.relative(webviewRoot, target)}: ${normalized}`);
          }
        }
      }
    }
  }

  walk(webviewRoot);
  assert.deepEqual(hits, []);
});
