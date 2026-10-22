'use strict';

// Source contract for T-0022: short windows collapse secondary dock chrome so
// the primary action and learning content keep their space.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const composerCss = fs.readFileSync(
  path.resolve(__dirname, '..', 'webview', 'src', 'styles', 'sections', 'composer.css'),
  'utf8',
);

test('short windows collapse dock anchor, send preference and shrink the frame', () => {
  assert.match(composerCss, /@media \(max-height: 700px\)/);
  assert.match(composerCss, /\.template-context\[data-dock-anchor="true"\]/);
  assert.match(composerCss, /\[data-dock-send-preference="true"\]/);
  assert.match(composerCss, /min-height: 30px;/);
});

test('very short windows also quiet suggestion chips and shrink further', () => {
  assert.match(composerCss, /@media \(max-height: 520px\)/);
  assert.match(composerCss, /max-block-size: 20vh/);
});
