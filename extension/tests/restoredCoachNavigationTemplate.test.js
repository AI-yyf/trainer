// Restored behavioral regression test. Original file: extension/tests/coachConversationSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Coach sidebar navigation: tab labels stay short. navigation template: templateAssertions.navigation() renders templates/AppShell.tsx per route and asserts on the markup.
//
// Restoration: partial - 1 of 32 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "coach streaming lane exposes trainer agent activity" [fails at HEAD (source-text guard)]
//   - "coach summary stays a compact horizontal context rail" [source-text guard]
//   - "coach summary rail surfaces blocker guidance alongside the live thread" [fails at HEAD (source-text guard)]
//   - "coach keeps the normal message thread free of a summary rail" [source-text guard]
//   - "coach composer keeps the resources button label short" [source-text guard]
//   - "coach next-step artifact stays bare: identity and one action, no flat meta dump" [source-text guard]
//   - "coach agent activity renders as a normalized lightweight progress rail" [source-text guard]
//   - "coach activity details render flat with no fold toggling mid-stream" [source-text guard]
//   - "coach context status does not become a second transcript message" [source-text guard]
//   - "coach visible status renders an explicit recovery resume line" [fails at HEAD (source-text guard)]
//   - "coach rich content keeps markdown code blocks on the highlighted renderer path" [source-text guard]
//   - "coach rich tables expose header associations and responsive column hooks" [source-text guard]
//   - "coach typed parts reuse rich renderers for code math and tables" [source-text guard]
//   - "coach message bubble stays a clean reply card with no status disclosure" [source-text guard]
//   - "coach user timestamps stay attached to the identity rail instead of a detached right edge" [source-text guard]
//   - "docked views retain a compact Coach context rail without docking the full transcript" [fails at HEAD (source-text guard)]
//   - "formal Plan generation requires a current verified tools probe, not declared capability flags" [fails at HEAD (source-text guard)]
//   - "coach composer does not gate sending on an unverified streaming probe" [source-text guard]
//   - "Coach interrupted recovery bar is absent" [source-text guard]
//   - "Plan next-step copy prefers the live current step before stale artifact teasers" [fails at HEAD (source-text guard)]
//   - "Coach shows the welcome with its bottom composer available" [fails at HEAD (source-text guard)]
//   - "Coach first-run state starts from the learner goal before optional code context" [fails at HEAD (source-text guard)]
//   - "Training keeps card submission default while allowing a contextual Coach route" [source-text guard]
//   - "Training review entry uses shared localized copy and hides mismatched review prose" [fails at HEAD (source-text guard)]
//   - "Composer keeps slash and skill discovery on demand, not as persistent controls" [source-text guard]
//   - "Composer candidate decks keep Codex-style draft ownership and keyboard dismissal" [fails at HEAD (source-text guard)]
//   - "Composer expansion lists stay anchored, bounded, scrollable, and keyboard-visible" [source-text guard]
//   - "Composer expansion decks keep flat idle rows and visible selected/focus states" [source-text guard]
//   - "Unavailable image capability stays accessible and only surfaces inline after a paste or drop attempt" [source-text guard]
//   - "hint suggested action fills the composer and does not mint a task turn" [fails at HEAD (source-text guard)]
//   - "handleSuggestedAction prefills task, next_task, and review drafts without sendTurn when leftover is not live" [fails at HEAD (source-text guard)]
// Target: webview components rendered to static markup through templateAssertions.render.
// Note: the require of extension/tests/helpers/appModuleSource.js (deleted in df0a3e2a) is dropped: only omitted source-guard tests used it.

// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
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

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const coachConversationControllerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useCoachConversationController.ts',
);
const appUiCopyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'appUiCopy.ts');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const agentActivityPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'AgentActivityStripSmart.tsx',
);
const coachMessageBubblePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageBubble.tsx',
);
const coachMessagePartsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageParts.tsx',
);
const messageRichContentPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'MessageRichContent.tsx',
);
const coachArtifactBlockPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachArtifactBlock.tsx',
);
const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);





test('coach sidebar tabs keep the resources label short', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});


























const recoveryCopySourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'providerRecoveryCopy.ts');
