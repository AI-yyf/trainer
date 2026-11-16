'use strict';

// Short windows compress the dock while keeping selected context visible.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const composerCss = fs.readFileSync(
  path.resolve(__dirname, '..', 'webview', 'src', 'styles', 'sections', 'composer.css'),
  'utf8',
);

test('short windows compress the anchor padding and shrink the frame', () => {
  assert.match(composerCss, /@media \(max-height: 700px\)/);
  assert.match(composerCss, /\.composer__attachments\[data-dock-anchor="true"\]\s*\{\s*padding-block: 0;/);
  assert.match(composerCss, /min-height: 30px;/);
});

test('very short windows also quiet suggestion chips and shrink further', () => {
  assert.match(composerCss, /@media \(max-height: 520px\)/);
  assert.match(composerCss, /max-block-size: 20vh/);
});
