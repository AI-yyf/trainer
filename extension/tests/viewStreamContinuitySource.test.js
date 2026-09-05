'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('view rails keep an active stream visible after switching away from its source view', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const railStart = source.indexOf('  const renderContextualResultRail =');
  const railEnd = source.indexOf('  const renderDockedView =', railStart);
  assert.ok(railStart >= 0 && railEnd > railStart, 'expected contextual result rail implementation');
  const railSource = source.slice(railStart, railEnd);

  assert.match(
    railSource,
    /const liveValue = streaming\.isStreaming\s*\?\s*[\s\S]*?streaming\.streamedContent \|\| streamingPlaceholderBody/,
  );
  assert.match(
    railSource,
    /const isResourcesContextWorthSurfacing =\s*!isResources \|\| streaming\.isStreaming \|\| lastTurnView === "resources";/,
  );
  assert.match(source, /renderContextualResultRail\("plan"\)/);
  assert.match(source, /renderContextualResultRail\("resources"\)/);
  assert.match(source, /renderContextualResultRail\("training"\)/);
});

test('resource limit copy is shown only when the library reaches its upload limit', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /const RESOURCE_UPLOAD_LIMIT = 100;/);
  assert.match(
    source,
    /data\.resources\.length >= RESOURCE_UPLOAD_LIMIT \? \([\s\S]*?t\.maxFilesHint[\s\S]*?\) : null/,
  );
});

