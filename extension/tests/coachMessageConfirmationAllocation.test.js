'use strict';

// Message UX convergence (2026-10-14), behaviour guard.
//
// The grounding downgrade (DESIGN.md §2.5) must stay visible — but the user
// rejected a "confirm before acting" marker trailing every text of the turn
// ("没有必要每一个文字末尾都要放"). These tests render the real bubble and
// count the marker: per message there is at most one badge and exactly one
// confirmation note, and a turn without the downgrade renders none at all.
//
// The icon-label and narrow-sidebar rules are pinned as CSS contracts (the
// regression they guard is layout, which only the geometry probe can measure;
// these assertions keep the declarations from drifting away).

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
const test = require('node:test');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview');
const srcRoot = path.join(webviewRoot, 'src');
const runtime = Module.createRequire(path.join(webviewRoot, 'package.json'));
const React = runtime('react');
const { renderToStaticMarkup } = runtime('react-dom/server');
const { buildSync } = runtime('esbuild');

const cache = new Map();

function load(relativePath) {
  if (cache.has(relativePath)) {
    return cache.get(relativePath);
  }
  const filename = path.join(srcRoot, relativePath);
  const { outputFiles } = buildSync({
    entryPoints: [filename],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
    external: ['react', 'react-dom', 'react/jsx-runtime', '*?worker&inline'],
  });
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const requireModule = mod.require.bind(mod);
  mod.require = (id) => id.endsWith('?worker&inline')
    ? class BrowserWorkerOnly { constructor() { throw new Error('browser-only worker'); } }
    : requireModule(id);
  mod._compile(outputFiles[0].text, filename);
  cache.set(relativePath, mod.exports);
  return mod.exports;
}

function renderBubble(props) {
  const { CoachMessageBubble } = load('components/coach/CoachMessageBubble.tsx');
  return renderToStaticMarkup(React.createElement(CoachMessageBubble, {
    language: 'en-US',
    onMessageAction() {},
    onArtifactOpen() {},
    ...props,
  }));
}

const BADGE = 'Confirm first';
const NOTE = 'This next step is not backed by the reply or your code yet — confirm it before acting.';

function countOccurrences(haystack, needle) {
  return haystack.split(needle).length - 1;
}

function nextStepArtifact(metadata) {
  return {
    kind: 'next_step',
    title: 'Continue practice',
    recommendedAction: 'task',
    summary: 'Keep going',
    verification: ['Boundary case passes'],
    metadata,
  };
}

test('downgraded latest reply renders the marker once: one note, at most one badge', () => {
  const html = renderBubble({
    message: {
      id: 'downgraded-latest',
      role: 'assistant',
      author: 'Trainer',
      timestamp: '10:00',
      body: 'Start with the boundary check.',
      parts: [{
        type: 'coach_visible_status',
        status: 'done',
        summary: 'Checked',
        nextStep: 'Run pytest to confirm the boundary',
      }],
      artifacts: [nextStepArtifact({ next_step_requires_confirmation: true })],
    },
    isLatestAssistant: true,
  });

  assert.equal(countOccurrences(html, NOTE), 1, 'the confirmation note renders exactly once');
  assert.ok(countOccurrences(html, BADGE) <= 1, 'the badge never repeats');
  assert.equal(countOccurrences(html, 'data-next-step-requires-confirmation="true"'), 1);
});

test('downgraded earlier reply carries the note on its card, once', () => {
  const html = renderBubble({
    message: {
      id: 'downgraded-earlier',
      role: 'assistant',
      author: 'Trainer',
      timestamp: '09:58',
      body: 'Start with the boundary check.',
      artifacts: [nextStepArtifact({ requires_confirmation: true })],
    },
    isLatestAssistant: false,
  });

  assert.equal(countOccurrences(html, NOTE), 1, 'the confirmation note renders exactly once');
  assert.equal(
    countOccurrences(html, 'data-next-step-requires-confirmation="true"'),
    1,
    'the downgrade is carried by one element only',
  );
});

test('several flagged artifacts still produce one note for the whole message', () => {
  const html = renderBubble({
    message: {
      id: 'two-artifacts',
      role: 'assistant',
      author: 'Trainer',
      timestamp: '09:58',
      body: 'Two candidates.',
      artifacts: [
        nextStepArtifact({ requiresConfirmation: true }),
        { kind: 'review', title: 'Review result', summary: 'Look back', metadata: { next_step_requires_confirmation: true } },
      ],
    },
    isLatestAssistant: false,
  });

  assert.equal(countOccurrences(html, NOTE), 1, 'one note for the message, not one per artifact');
  assert.equal(
    countOccurrences(html, 'data-next-step-requires-confirmation="true"'),
    1,
    'only the allocated carrier renders the downgrade',
  );
  assert.equal(
    countOccurrences(html, BADGE),
    0,
    'an earlier reply offers no next-action surface, so no badge is repeated into the fold',
  );
});

test('the allocated action surface carries the badge; other surfaces stay clean', () => {
  const { CoachArtifactBlock } = load('components/coach/CoachArtifactBlock.tsx');
  const artifact = nextStepArtifact({});

  const carrier = renderToStaticMarkup(React.createElement(CoachArtifactBlock, {
    artifact,
    compact: true,
    slim: true,
    language: 'en-US',
    nextStepConfirmation: true,
    onOpen() {},
  }));
  assert.equal(countOccurrences(carrier, BADGE), 1);
  assert.match(carrier, /data-next-step-requires-confirmation="true"/);

  const other = renderToStaticMarkup(React.createElement(CoachArtifactBlock, {
    artifact,
    compact: true,
    slim: true,
    language: 'en-US',
    onOpen() {},
  }));
  assert.equal(countOccurrences(other, BADGE), 0, 'a non-carrier surface renders no marker');
});

test('a turn without the downgrade renders no marker at all', () => {
  const html = renderBubble({
    message: {
      id: 'plain',
      role: 'assistant',
      author: 'Trainer',
      timestamp: '09:57',
      body: 'Here is the explanation.',
      parts: [{
        type: 'coach_visible_status',
        status: 'done',
        summary: 'Checked',
        nextStep: 'Run pytest to confirm the boundary',
      }],
      artifacts: [nextStepArtifact({})],
    },
    isLatestAssistant: true,
    nextStepRequiresConfirmation: false,
  });

  assert.equal(countOccurrences(html, NOTE), 0, 'no confirmation copy on an ordinary reply');
  assert.equal(countOccurrences(html, BADGE), 0);
  assert.equal(countOccurrences(html, 'data-next-step-requires-confirmation="true"'), 0);
});

test('the turn-level flag alone still marks a next-step artifact', () => {
  // The host stamps coachTurn/nextStepHint/stream-frame carriers too; when the
  // artifact metadata is absent the flag alone must keep the downgrade visible.
  const html = renderBubble({
    message: {
      id: 'turn-flag',
      role: 'assistant',
      author: 'Trainer',
      timestamp: '09:56',
      body: 'One more step.',
      artifacts: [nextStepArtifact({})],
    },
    isLatestAssistant: true,
    nextStepRequiresConfirmation: true,
  });

  assert.equal(countOccurrences(html, NOTE), 1);
});

test('confirmation allocation is single-shot and reads the first next-step line', () => {
  const lib = load('lib/nextStepConfirmation.ts');

  assert.equal(
    lib.resolveNextStepConfirmationOwner({ requiresConfirmation: false, hasStatusNextStep: true, hasArtifactNextStep: true }),
    null,
  );
  assert.equal(
    lib.resolveNextStepConfirmationOwner({ requiresConfirmation: true, hasStatusNextStep: true, hasArtifactNextStep: true }),
    'status-line',
  );
  assert.equal(
    lib.resolveNextStepConfirmationOwner({ requiresConfirmation: true, hasStatusNextStep: false, hasArtifactNextStep: true }),
    'artifact',
  );
  assert.equal(
    lib.resolveNextStepConfirmationOwner({ requiresConfirmation: true, hasStatusNextStep: false, hasArtifactNextStep: false }),
    null,
  );
  assert.equal(
    lib.statusNextStepPartIndex([
      { type: 'markdown' },
      { type: 'coach_visible_status', nextStep: '   ' },
      { type: 'coach_visible_status', nextStep: 'Run the tests' },
      { type: 'coach_visible_status', nextStep: 'Then ship' },
    ]),
    2,
    'only the first next-step line is the carrier',
  );
  assert.equal(lib.statusNextStepPartIndex(undefined), -1);
});

test('the five quick-action icons feed a CSS label instead of a title tooltip', () => {
  const source = fs.readFileSync(
    path.join(srcRoot, 'components', 'coach', 'CoachMessageBubble.tsx'),
    'utf8',
  );

  for (const action of ['copy', 'share', 'save-resource', 'training-card', 'retry']) {
    assert.ok(
      source.includes(`data-action-label={messageActionLabels`),
      `expected the ${action} action to carry a label attribute`,
    );
  }
  assert.equal(
    countOccurrences(source, 'data-action-label={'),
    6,
    'five shortcuts plus the next-action reveal',
  );
  assert.doesNotMatch(source, /title=\{messageActionLabels/, 'the native tooltip stays removed');
});

test('icon labels are one delayed line that the reduced-motion fallback keeps', () => {
  const styles = readStylesSource();
  const base = styles.match(/\.message-bubble__icon-action\[data-action-label\]::after\s*\{[\s\S]*?\n\}/);
  const shown = styles.match(/\.message-bubble__icon-action\[data-action-label\]:hover:not\(:disabled\)::after,[\s\S]*?\n\}/);

  assert.ok(base, 'expected the CSS label rule');
  assert.match(base[0], /content:\s*attr\(data-action-label\)/);
  assert.match(base[0], /white-space:\s*nowrap/);
  assert.match(base[0], /opacity:\s*0/);
  assert.match(base[0], /visibility:\s*hidden/);
  assert.doesNotMatch(base[0], /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'label uses tokens only');
  assert.ok(shown, 'expected the hover/focus reveal rule');
  assert.match(shown[0], /:focus-visible::after/);
  assert.match(shown[0], /140ms/, 'the label arrives after a short delay');
  assert.match(styles, /prefers-reduced-motion[\s\S]{0,240}\.message-bubble__icon-action\[data-action-label\]::after\s*\{\s*transition:\s*none;/);
});

test('the icon row never wraps or shrinks and the next-action bar wraps instead', () => {
  const styles = readStylesSource();
  const tools = styles.match(/\.coach-conversation-view \.message-bubble__tools\s*\{[\s\S]*?\n\}/);
  const quickTools = styles.match(/\.coach-conversation-view \.message-bubble__quick-tools\s*\{[\s\S]*?\n\}/);
  const iconAction = styles.match(/\.coach-conversation-view \.message-bubble__icon-action\s*\{[\s\S]*?\n\}/);

  assert.ok(tools && quickTools && iconAction, 'expected the quick-tool layout rules');
  assert.match(tools[0], /flex-wrap:\s*wrap/);
  assert.match(quickTools[0], /flex:\s*none/);
  assert.match(quickTools[0], /flex-wrap:\s*nowrap/);
  assert.match(iconAction[0], /flex:\s*none/);
  assert.match(styles, /\.coach-conversation-view \.message-bubble__icon-action svg\s*\{\s*flex:\s*none;/);
});
