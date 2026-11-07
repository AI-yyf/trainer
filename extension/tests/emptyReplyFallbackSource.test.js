'use strict';

/** A finished assistant turn with no body/parts/status must not render blank. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const bubble = fs.readFileSync(
  path.join(root, 'extension/webview/src/components/coach/CoachMessageBubble.tsx'),
  'utf8',
);
const copy = fs.readFileSync(
  path.join(root, 'extension/webview/src/lib/i18n/segments/coachMessageBubbleCopy.ts'),
  'utf8',
);

test('an empty finished assistant turn gets an actionable fallback line', () => {
  assert.match(
    bubble,
    /const emptyReplyFallback =\s*message\.role === "assistant" &&\s*!streaming &&\s*!hasBody &&\s*!hasParts &&\s*!hasRunningActivities &&\s*!fallbackStatusSummary &&\s*!children;/,
  );
  assert.match(bubble, /data-empty-reply-fallback="true"/);
  assert.match(bubble, /这一轮没有返回可显示的回复。可以重试或换一种问法。/);
});

test('the empty reply fallback is localized in all eight languages', () => {
  const start = copy.indexOf('"这一轮没有返回可显示的回复。可以重试或换一种问法。"');
  assert.notEqual(start, -1);
  const block = copy.slice(start, copy.indexOf('},', start));
  for (const language of ['en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(block, new RegExp(`"${language}":`));
  }
});
